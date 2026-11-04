"""Stripe TEST-MODE billing, not supplier payout or smart-contract settlement.

Creates unconfirmed PaymentIntents only. Card data and client secrets are never
stored or exposed. Independent Stripe webhook confirmation records successful
collection. Resource credits and billing amounts remain separate ledgers.
"""
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from .core import Denied, canonical, digest

API_VERSION = '2026-10-28.endive'


class StripeTestTransport:
    def __init__(self, api_key):
        if not api_key.startswith('sk_test_'):
            raise ValueError('only Stripe test secret keys are supported')
        self.api_key = api_key

    def __call__(self, parameters, key):
        data = urllib.parse.urlencode(parameters).encode()
        request = urllib.request.Request('https://api.stripe.com/v1/payment_intents', data=data,
            headers={'Authorization': 'Bearer ' + self.api_key, 'Idempotency-Key': key,
                     'Stripe-Version': API_VERSION, 'Content-Type': 'application/x-www-form-urlencoded'},
            method='POST')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            return json.load(response)


def verify_signature(raw, header, secret, now, tolerance=300):
    """Stripe v1 signs the timestamp and unmodified request bytes."""
    parts = [part.strip().split('=', 1) for part in header.split(',')]
    timestamps = [value for name, value in parts if name == 't']
    signatures = [value for name, value in parts if name == 'v1']
    if len(timestamps) != 1 or not signatures:
        raise ValueError('invalid signature header')
    timestamp = int(timestamps[0])
    if abs(now - timestamp) > tolerance:
        raise ValueError('webhook timestamp outside tolerance')
    expected = hmac.new(secret.encode(), timestamps[0].encode() + b'.' + raw, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, signature) for signature in signatures):
        raise ValueError('invalid signature')


class StripeBilling:
    def __init__(self, guard, tenant, transport, webhook_secret, allowed_customers, clock=time.time):
        if not webhook_secret.startswith('whsec_'):
            raise ValueError('webhook endpoint secret required')
        if not allowed_customers or any(not isinstance(c, str) or not c.startswith('cus_') for c in allowed_customers):
            raise ValueError('platform-provisioned tenant customer allowlist required')
        self.allowed_customers = frozenset(allowed_customers)
        self.guard, self.tenant, self.transport = guard, tenant, transport
        self.secret, self.clock = webhook_secret, clock
        with guard.tx() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS billing(id TEXT PRIMARY KEY, ticket TEXT NOT NULL UNIQUE,
              fingerprint TEXT NOT NULL, amount BIGINT NOT NULL, currency TEXT NOT NULL,
              customer TEXT NOT NULL, provider_id TEXT UNIQUE, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS stripe_events(id TEXT PRIMARY KEY, hash TEXT NOT NULL);
            ''')

    def create(self, id, ticket, amount, currency, customer):
        """Operator-only: exact accepted deliverable, one collection intent per ticket.

        Persist UNKNOWN before provider I/O; no automatic retry even if Stripe's
        idempotency retention expires. A timeout requires provider reconciliation.
        """
        if (not isinstance(id, str) or not 0 < len(id) <= 128 or type(amount) is not int
                or not 50 <= amount <= 99999999 or currency != 'usd'
                or not isinstance(customer, str) or not customer.startswith('cus_')):
            raise ValueError('test billing requires valid ID, USD cents and Stripe customer')
        if customer not in self.allowed_customers:
            raise Denied('customer is not provisioned for this tenant')
        fingerprint = digest([self.tenant, ticket, amount, currency, customer])
        with self.guard.tx() as db:
            row = db.execute('SELECT * FROM billing WHERE id=?', (id,)).fetchone()
            if row:
                if row['fingerprint'] != fingerprint:
                    raise Denied('billing key conflict')
                if not row['provider_id']:
                    raise Denied('provider outcome unknown; reconcile via Stripe events')
                return {'id': row['provider_id'], 'state': row['state']}
            task = db.execute('SELECT * FROM tickets WHERE id=?', (ticket,)).fetchone()
            if task is None or task['state'] != 'ACCEPTED':
                raise Denied('accepted ticket required for billing')
            mandate = db.execute('SELECT body FROM mandates WHERE id=?', (task['mandate'],)).fetchone()
            if json.loads(mandate['body'])['principal'] != self.tenant:
                raise Denied('billing tenant mismatch')
            db.execute('INSERT INTO billing VALUES(?,?,?,?,?,?,NULL,?)',
                       (id, ticket, fingerprint, amount, currency, customer, 'UNKNOWN'))
            self.guard.event(db, 'billing.requested', billing=id, ticket=ticket, amount_minor=amount, currency=currency)
        parameters = {'amount': amount, 'currency': currency, 'customer': customer,
                      'payment_method_types[]': 'card', 'metadata[contractguard_tenant]': self.tenant,
                      'metadata[contractguard_billing]': id}
        # Irreversible provider call happens only after the reservation is durable.
        response = self.transport(parameters, 'cg-' + digest([self.tenant, id]))
        self.validate_object(response, id, amount, currency, customer)
        with self.guard.tx() as db:
            row = db.execute('SELECT * FROM billing WHERE id=?', (id,)).fetchone()
            if row['provider_id'] and row['provider_id'] != response['id']:
                raise Denied('provider ID conflict')
            # A webhook can arrive before the creation response. Do not overwrite it.
            if row['state'] == 'UNKNOWN':
                db.execute('UPDATE billing SET provider_id=?,state=? WHERE id=?', (response['id'], 'PENDING', id))
                self.guard.event(db, 'billing.intent_created', billing=id, provider_id=response['id'])
            row = db.execute('SELECT provider_id,state FROM billing WHERE id=?', (id,)).fetchone()
            return {'id': row['provider_id'], 'state': row['state']}

    def validate_object(self, obj, id, amount, currency, customer):
        if (obj.get('object') != 'payment_intent' or obj.get('livemode') is not False
                or not isinstance(obj.get('id'), str) or not obj['id'].startswith('pi_')
                or type(obj.get('amount')) is not int or obj['amount'] != amount
                or obj.get('currency') != currency or obj.get('customer') != customer
                or obj.get('metadata', {}).get('contractguard_tenant') != self.tenant
                or obj.get('metadata', {}).get('contractguard_billing') != id):
            raise ValueError('Stripe object does not match authorized test billing')

    def webhook(self, raw, header):
        verify_signature(raw, header, self.secret, self.clock())
        event = json.loads(raw)
        if event.get('livemode') is not False or not isinstance(event.get('id'), str):
            raise ValueError('test-mode event required')
        states = {'payment_intent.succeeded': 'SUCCEEDED',
                  'payment_intent.payment_failed': 'REQUIRES_PAYMENT_METHOD',
                  'payment_intent.canceled': 'CANCELLED'}
        if event.get('type') not in states:
            return  # Authenticated but irrelevant event; deliberately no state mutation.
        obj = event['data']['object']
        id = obj['metadata']['contractguard_billing']
        state = states[event['type']]
        with self.guard.tx() as db:
            previous = db.execute('SELECT hash FROM stripe_events WHERE id=?', (event['id'],)).fetchone()
            if previous:
                if previous['hash'] != hashlib.sha256(raw).hexdigest():
                    raise ValueError('conflicting event replay')
                return
            row = db.execute('SELECT * FROM billing WHERE id=?', (id,)).fetchone()
            if row is None:
                raise ValueError('unknown billing request')
            self.validate_object(obj, id, row['amount'], row['currency'], row['customer'])
            if row['provider_id'] and row['provider_id'] != obj['id']:
                raise ValueError('provider ID mismatch')
            if state == 'SUCCEEDED' and (obj.get('status') != 'succeeded' or obj.get('amount_received') != row['amount']):
                raise ValueError('unconfirmed amount or status')
            if state == 'CANCELLED' and obj.get('status') != 'canceled':
                raise ValueError('cancellation status mismatch')
            if row['state'] in ('SUCCEEDED', 'CANCELLED') and row['state'] != state:
                # Delayed failure events must never undo a successful collection.
                state = row['state']
            db.execute('UPDATE billing SET provider_id=?,state=? WHERE id=?', (obj['id'], state, id))
            db.execute('INSERT INTO stripe_events VALUES(?,?)', (event['id'], hashlib.sha256(raw).hexdigest()))
            self.guard.event(db, 'billing.webhook', billing=id, provider_id=obj['id'], state=state, event=event['id'])
