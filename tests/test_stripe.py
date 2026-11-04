import copy
import hashlib
import hmac
import json
import io
from contractguard import Denied
from contractguard.stripe_billing import StripeBilling, StripeTestTransport
from tests_support import Fixture


class StripeTests(Fixture):
    def setUp(self):
        super().setUp()
        self.guard.create_ticket('t', 'root', 'v1')
        self.guard.assign('a', 't', 'parent', 190)
        self.guard.submit('a', 'parent', {}, {'v1': lambda artifact: True})
        self.requests = []
        self.secret = 'whsec_test_fixture_only'
        self.response = {'object': 'payment_intent', 'id': 'pi_fixture', 'livemode': False,
                         'amount': 100, 'currency': 'usd', 'customer': 'cus_fixture',
                         'metadata': {'contractguard_tenant': 'tenant', 'contractguard_billing': 'b'}}
        def transport(params, key):
            self.requests.append((params, key))
            return copy.deepcopy(self.response)
        self.billing = StripeBilling(self.guard, 'tenant', transport, self.secret, {'cus_fixture'}, lambda: self.now)

    def create(self, **kwargs):
        return self.billing.create(**dict(dict(id='b', ticket='t', amount=100, currency='usd', customer='cus_fixture'), **kwargs))

    def event(self, type='payment_intent.succeeded', id='evt_fixture', **updates):
        obj = copy.deepcopy(self.response)
        obj.update(status='succeeded', amount_received=100)
        obj.update(updates)
        return {'id': id, 'livemode': False, 'type': type, 'data': {'object': obj}}

    def deliver(self, event, timestamp=None, secret=None):
        raw = json.dumps(event).encode()
        timestamp = self.now if timestamp is None else timestamp
        mac = hmac.new((secret or self.secret).encode(), str(timestamp).encode() + b'.' + raw, hashlib.sha256).hexdigest()
        self.billing.webhook(raw, f't={timestamp},v1={mac}')

    def state(self):
        with self.guard.tx() as db:
            return db.execute("SELECT state FROM billing WHERE id='b'").fetchone()['state']

    def test_create_is_pending_not_settled(self):
        self.assertEqual(self.create(), {'id': 'pi_fixture', 'state': 'PENDING'})
        self.assertNotIn('confirm', self.requests[0][0])
        self.create()
        self.assertEqual(len(self.requests), 1)

    def test_operator_billing_route_and_agent_denial(self):
        from contractguard.hosted import HostedApplication, Tenant
        from contractguard.service import Identity
        app = HostedApplication({'tenant': Tenant(self.guard, {
            hashlib.sha256(b'operator').hexdigest(): Identity('operator'),
            hashlib.sha256(b'worker').hexdigest(): Identity('agent', 'parent')}, {}, self.billing)})
        raw = json.dumps(dict(id='b', ticket='t', amount=100, currency='usd', customer='cus_fixture')).encode()
        for token, expected in (('worker', '403 Forbidden'), ('operator', '200 OK')):
            status = []
            environ = dict(HTTP_AUTHORIZATION='Bearer ' + token, REQUEST_METHOD='POST',
                           CONTENT_TYPE='application/json', CONTENT_LENGTH=str(len(raw)),
                           PATH_INFO='/v1/billing/intents')
            environ['wsgi.input'] = io.BytesIO(raw)
            list(app(environ, lambda code, headers: status.append(code)))
            self.assertEqual(status, [expected])
        self.assertEqual(len(self.requests), 1)

    def test_hosted_webhook_requires_signature(self):
        from contractguard.hosted import HostedApplication, Tenant
        from contractguard.service import Identity
        app = HostedApplication({'tenant': Tenant(self.guard, {
            hashlib.sha256(b'operator').hexdigest(): Identity('operator')}, {}, self.billing)})
        self.create()
        raw = json.dumps(self.event()).encode()
        status = []
        environ = dict(REQUEST_METHOD='POST', CONTENT_LENGTH=str(len(raw)),
                       PATH_INFO='/webhooks/stripe/tenant', HTTP_STRIPE_SIGNATURE='t=100,v1=wrong')
        environ['wsgi.input'] = io.BytesIO(raw)
        list(app(environ, lambda code, headers: status.append(code)))
        self.assertEqual(status, ['400 Bad Request'])
        self.assertEqual(self.state(), 'PENDING')

    def test_foreign_customer_denied_before_provider(self):
        with self.assertRaises(Denied): self.create(customer='cus_foreign')
        self.assertEqual(self.requests, [])

    def test_argument_change_denied(self):
        self.create()
        with self.assertRaises(Denied): self.create(amount=101)

    def test_signed_success_and_duplicate_event(self):
        self.create(); self.deliver(self.event()); self.deliver(self.event())
        self.assertEqual(self.state(), 'SUCCEEDED')
        with self.guard.tx() as db:
            self.assertEqual(db.execute('SELECT count(*) AS n FROM stripe_events').fetchone()['n'], 1)

    def test_tampered_signature_and_expired_signature(self):
        self.create()
        for kwargs in ({'secret': 'whsec_wrong'}, {'timestamp': -1000}):
            with self.assertRaises(ValueError): self.deliver(self.event(), **kwargs)
        self.assertEqual(self.state(), 'PENDING')

    def test_cross_tenant_or_amount_rejected(self):
        self.create()
        for updates in ({'metadata': {'contractguard_tenant': 'evil', 'contractguard_billing': 'b'}},
                        {'amount': 101}, {'livemode': True}, {'customer': 'cus_other'}, {'amount_received': 99}):
            with self.assertRaises(ValueError): self.deliver(self.event(**updates))
        self.assertEqual(self.state(), 'PENDING')

    def test_delayed_failure_cannot_undo_success(self):
        self.create(); self.deliver(self.event())
        self.deliver(self.event('payment_intent.payment_failed', 'evt_late_failure', status='requires_payment_method'))
        self.assertEqual(self.state(), 'SUCCEEDED')

    def test_timeout_never_blindly_retries(self):
        def fail(params, key): raise TimeoutError('provider outcome ambiguous')
        self.billing.transport = fail
        with self.assertRaises(TimeoutError): self.create()
        with self.assertRaises(Denied): self.create()
        self.deliver(self.event())
        self.assertEqual(self.create()['state'], 'SUCCEEDED')

    def test_no_unaccepted_ticket_billing(self):
        self.guard.create_ticket('not-accepted', 'root', 'v1')
        with self.assertRaises(Denied): self.create(ticket='not-accepted')
        self.assertEqual(self.requests, [])

    def test_live_key_refused(self):
        with self.assertRaises(ValueError): StripeTestTransport('sk_live_do_not_use')

    def test_out_of_order_webhook_before_create_response(self):
        def early(params, key):
            self.deliver(self.event())
            return copy.deepcopy(self.response)
        self.billing.transport = early
        self.assertEqual(self.create()['state'], 'SUCCEEDED')

    def test_conflicting_event_replay(self):
        self.create(); self.deliver(self.event())
        with self.assertRaises(ValueError): self.deliver(self.event(amount_received=99))
