"""Trusted control plane. Never expose this object or its DB to agent code."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Callable
from .storage import transaction


def canonical(value):
    """Restricted JSON commitment: no NaN, stable keys, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Denied(ValueError):
    pass


@dataclass(frozen=True)
class Mandate:
    id: str
    principal: str
    agent: str
    tools: tuple[str, ...]
    limit: int  # Integer resource credits; never floating point money.
    expires: int
    policy: str = 'v1'
    parent: str | None = None
    depth: int = 0
    max_depth: int = 3


@dataclass(frozen=True)
class Tool:
    name: str
    version: str
    cost: int  # Trusted fixed upper-bound charge, retained on ambiguous failures.
    invoke: Callable[[dict], object]
    requires_approval: bool = False


class Guard:
    """Transactional governance core; each method opens a fresh connection.

    BEGIN IMMEDIATE serializes admission across processes sharing the DB file.
    Agent identity must come from a trusted caller, never tool-call arguments.
    """
    def __init__(self, path, tools=(), clock=time.time):
        self.path, self.clock = str(path), clock
        self.tools = {t.name: t for t in tools}
        for t in tools:
            if type(t.cost) is not int or t.cost < 0:
                raise ValueError('invalid tool cost')
        with self.tx() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS mandates(id TEXT PRIMARY KEY, body TEXT NOT NULL,
                spent INTEGER NOT NULL DEFAULT 0, revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS calls(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                mandate TEXT NOT NULL, status TEXT NOT NULL, output TEXT);
            CREATE TABLE IF NOT EXISTS receipts(seq INTEGER PRIMARY KEY, body TEXT NOT NULL,
                previous TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY, mandate TEXT NOT NULL,
                validator TEXT NOT NULL, state TEXT NOT NULL, artifact TEXT);
            CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY, ticket TEXT NOT NULL,
                agent TEXT NOT NULL, expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                expires BIGINT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
            INSERT INTO schema_version(version) VALUES(2) ON CONFLICT DO NOTHING;
            ''')

    def tx(self):
        return transaction(self.path)

    def event(self, db, kind, **data):
        row = db.execute('SELECT hash FROM receipts ORDER BY seq DESC LIMIT 1').fetchone()
        previous = row['hash'] if row else '0' * 64
        body = canonical(dict(kind=kind, timestamp=int(self.clock()), **data))
        db.execute('INSERT INTO receipts(body,previous,hash) VALUES(?,?,?)',
                   (body, previous, digest([previous, body])))

    def chain(self, db, id):
        result = []
        while id:
            row = db.execute('SELECT * FROM mandates WHERE id=?', (id,)).fetchone()
            if row is None:
                raise Denied('unknown mandate')
            m = json.loads(row['body'])
            if row['revoked'] or self.clock() >= m['expires']:
                raise Denied('revoked or expired ancestor')
            result.append((m, row['spent']))
            id = m['parent']
        return result

    def issue(self, m: Mandate):
        if (any(not isinstance(value, str) or not value or len(value) > 256
                for value in (m.id, m.principal, m.agent, m.policy))
                or not isinstance(m.tools, (list, tuple))
                or any(not isinstance(tool, str) or not tool for tool in m.tools)
                or (m.parent is not None and not isinstance(m.parent, str))
                or type(m.limit) is not int or not 0 <= m.limit <= 2**63 - 1 or type(m.expires) is not int
                or type(m.depth) is not int or type(m.max_depth) is not int
                or not m.id or not m.principal or not m.agent or not m.policy
                or m.expires <= self.clock() or not 0 <= m.max_depth <= 32):
            raise Denied('invalid mandate')
        with self.tx() as db:
            if m.parent:
                p = self.chain(db, m.parent)[0][0]
                if (m.principal != p['principal'] or m.policy != p['policy']
                    or not set(m.tools) <= set(p['tools']) or m.limit > p['limit']
                    or m.expires > p['expires'] or m.depth != p['depth'] + 1
                    or m.depth > p['max_depth'] or m.max_depth > p['max_depth']):
                    raise Denied('delegation expands authority')
            elif m.depth != 0:
                raise Denied('root depth must be zero')
            db.execute('INSERT INTO mandates(id,body) VALUES(?,?)', (m.id, canonical(asdict(m))))
            self.event(db, 'mandate.issued', mandate=asdict(m))

    def revoke(self, id):
        with self.tx() as db:
            if db.execute('UPDATE mandates SET revoked=1 WHERE id=?', (id,)).rowcount != 1:
                raise Denied('unknown mandate')
            self.event(db, 'mandate.revoked', mandate=id)

    def execute(self, mandate, agent, tool, arguments, key, *, assignment=None, approval=None):
        """Reserve all ancestor budgets before releasing the transaction for I/O.

        A crash after reservation leaves UNKNOWN, with credits held. No automatic
        retry can repeat a side effect. Operators reconcile unknown calls manually.
        """
        arguments = json.loads(canonical(arguments))  # Snapshot mutable caller input.
        fingerprint = digest([mandate, agent, tool, arguments, assignment])
        denial = None
        with self.tx() as db:
            try:
                lineage = self.chain(db, mandate)
                m = lineage[0][0]
                if m['agent'] != agent or tool not in self.tools or tool not in m['tools']:
                    raise Denied('identity or tool scope mismatch')
                if assignment is not None:
                    self.check_assignment(db, assignment, agent, mandate)
                existing = db.execute('SELECT * FROM calls WHERE key=?', (key,)).fetchone()
                if existing:
                    if existing['fingerprint'] != fingerprint:
                        raise Denied('idempotency key conflict')
                    if existing['status'] != 'COMPLETED':
                        raise Denied('outcome unknown; reconcile before retry')
                    return json.loads(existing['output'])
                spec = self.tools[tool]
                if any(spent + spec.cost > ancestor['limit'] for ancestor, spent in lineage):
                    raise Denied('budget exhausted')
                if spec.requires_approval:
                    grant = db.execute('SELECT * FROM approvals WHERE id=?', (approval,)).fetchone()
                    if (grant is None or grant['consumed'] or grant['expires'] <= self.clock()
                            or grant['fingerprint'] != digest([fingerprint, key, spec.version, spec.cost])):
                        raise Denied('missing, expired or mismatched approval')
                    db.execute('UPDATE approvals SET consumed=1 WHERE id=?', (approval,))
                for ancestor, _ in lineage:
                    db.execute('UPDATE mandates SET spent=spent+? WHERE id=?', (spec.cost, ancestor['id']))
                db.execute('INSERT INTO calls VALUES(?,?,?,?,NULL)', (key, fingerprint, mandate, 'UNKNOWN'))
                self.event(db, 'call.reserved', key=key, mandate=mandate, agent=agent,
                           policy=m['policy'], tool=tool, version=spec.version,
                           input_hash=digest(arguments), cost=spec.cost, assignment=assignment)
            except Denied as error:
                denial = str(error)
                self.event(db, 'call.denied', mandate=mandate, request_hash=fingerprint, reason=denial)
        if denial:
            raise Denied(denial)
        try:
            output = json.loads(canonical(spec.invoke(arguments)))
        except Exception:
            with self.tx() as db:
                self.event(db, 'call.unknown', key=key)
            raise
        with self.tx() as db:
            updated = db.execute('UPDATE calls SET status=?,output=? WHERE key=? AND status=?',
                                 ('COMPLETED', canonical(output), key, 'UNKNOWN')).rowcount
            if updated != 1:
                raise Denied('call already reconciled; inspect provider result')
            self.event(db, 'call.completed', key=key, output_hash=digest(output))
        return output

    def create_ticket(self, id, mandate, validator):
        with self.tx() as db:
            self.chain(db, mandate)
            db.execute('INSERT INTO tickets VALUES(?,?,?, ?,NULL)', (id, mandate, validator, 'CREATED'))
            self.event(db, 'ticket.created', ticket=id, mandate=mandate, validator=validator)

    def assign(self, id, ticket, agent, expires):
        with self.tx() as db:
            t = db.execute('SELECT * FROM tickets WHERE id=?', (ticket,)).fetchone()
            if t is None or t['state'] != 'CREATED':
                raise Denied('ticket unavailable')
            m = self.chain(db, t['mandate'])[0][0]
            if agent != m['agent'] or not self.clock() < expires <= m['expires']:
                raise Denied('invalid assignment')
            db.execute('INSERT INTO assignments VALUES(?,?,?,?)', (id, ticket, agent, expires))
            db.execute("UPDATE tickets SET state='RUNNING' WHERE id=?", (ticket,))
            self.event(db, 'assignment.created', assignment=id, ticket=ticket, agent=agent)

    def submit(self, assignment, agent, artifact, validators):
        """Validators are operator-owned pure functions, versioned by registry key."""
        artifact = json.loads(canonical(artifact))
        with self.tx() as db:
            a = db.execute('SELECT * FROM assignments WHERE id=?', (assignment,)).fetchone()
            if a is None or a['agent'] != agent or a['expires'] <= self.clock():
                raise Denied('invalid execution lease')
            t = db.execute('SELECT * FROM tickets WHERE id=?', (a['ticket'],)).fetchone()
            self.chain(db, t['mandate'])
            if t['state'] != 'RUNNING':
                raise Denied('ticket already submitted')
            validator = validators[t['validator']]
            passed = validator(artifact) is True
            state = 'ACCEPTED' if passed else 'REJECTED'
            db.execute('UPDATE tickets SET state=?,artifact=? WHERE id=?', (state, canonical(artifact), t['id']))
            self.event(db, 'validation', ticket=t['id'], mandate=t['mandate'],
                       artifact_hash=digest(artifact), validator=t['validator'], state=state)
            return state

    def verify_receipts(self):
        """Detect edits against the current chain, not privileged full rewrites/truncation."""
        with self.tx() as db:
            previous = '0' * 64
            for row in db.execute('SELECT * FROM receipts ORDER BY seq'):
                if row['previous'] != previous or row['hash'] != digest([previous, row['body']]):
                    return False
                previous = row['hash']
            return True

    def check_assignment(self, db, assignment, agent, mandate):
        row = db.execute('SELECT a.agent,a.expires,t.mandate,t.state FROM assignments a '
                         'JOIN tickets t ON t.id=a.ticket WHERE a.id=?', (assignment,)).fetchone()
        if (row is None or row['agent'] != agent or row['mandate'] != mandate
                or row['expires'] <= self.clock() or row['state'] != 'RUNNING'):
            raise Denied('assignment inactive or mismatched')

    def approve(self, id, mandate, agent, tool, arguments, key, expires, assignment=None):
        """Operator grants one exact call, including tool version, cost and lease."""
        spec = self.tools[tool]
        if type(expires) is not int or expires <= self.clock():
            raise Denied('invalid approval expiry')
        fingerprint = digest([mandate, agent, tool, arguments, assignment])
        with self.tx() as db:
            self.chain(db, mandate)
            db.execute('INSERT INTO approvals(id,fingerprint,expires) VALUES(?,?,?)',
                       (id, digest([fingerprint, key, spec.version, spec.cost]), expires))
            self.event(db, 'approval.granted', approval=id, request_hash=fingerprint, key=key)

    def cancel(self, ticket):
        with self.tx() as db:
            count = db.execute("UPDATE tickets SET state='CANCELLED' WHERE id=? "
                               "AND state IN ('CREATED','RUNNING')", (ticket,)).rowcount
            if count != 1:
                raise Denied('ticket not cancellable')
            self.event(db, 'ticket.cancelled', ticket=ticket)

    def reconcile(self, key, output, reference):
        """Operator-only confirmed success; no refund or force-retry escape hatch.

        Quiesce the original worker before reconciliation to avoid competing results.
        A reference identifies independently checked provider evidence, not a claim
        that the SDK can authenticate that provider evidence itself.
        """
        if not isinstance(reference, str) or not reference.strip():
            raise Denied('independent provider reference required')
        body = canonical(output)
        with self.tx() as db:
            count = db.execute("UPDATE calls SET status='COMPLETED',output=? "
                               "WHERE key=? AND status='UNKNOWN'", (body, key)).rowcount
            if count != 1:
                raise Denied('call not unknown')
            self.event(db, 'call.reconciled', key=key, output_hash=digest(output), reference=reference)

    def snapshot(self):
        """Consistent operator-only export. Contains identities, not raw artifacts."""
        with self.tx() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM receipts ORDER BY seq')]
            return {'version': 1, 'receipts': rows,
                    'head': rows[-1]['hash'] if rows else '0' * 64, 'count': len(rows)}
