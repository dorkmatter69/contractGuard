import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from contractguard import Denied, Guard, Mandate, Tool
from contractguard.adapters import DeepAgentsAdapter, DeepSeekHarnessAdapter
from contractguard.extensions import DisabledPayments, ProofStatement, UnavailableZKP
from contractguard.validators import REGISTRY, episode_v1


from tests_support import Fixture


class GovernanceTests(Fixture):
    def call(self, key='k', **kwargs):
        return self.guard.execute(kwargs.get('mandate', 'root'), kwargs.get('agent', 'parent'),
                                  kwargs.get('tool', 'run'), kwargs.get('args', {}), key)

    def child(self, id='child', **kwargs):
        m = Mandate(id, 'tenant', 'worker', ('run',), 6, 190, parent='root', depth=1)
        self.guard.issue(replace(m, **kwargs))

    def test_replay_is_cached_and_bound(self):
        self.assertEqual(self.call(), self.call())
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(Denied): self.call(args={'changed': True})

    def test_identity_and_scope(self):
        for kwargs in ({'agent': 'imposter'}, {'tool': 'shell'}, {'mandate': 'missing'}):
            with self.assertRaises(Denied): self.call(**kwargs)
        self.assertEqual(self.calls, [])
        self.assertTrue(self.guard.verify_receipts())

    def test_attenuation(self):
        for kwargs in ({'tools': ('shell',)}, {'limit': 10}, {'expires': 201},
                       {'principal': 'other'}, {'depth': 2}, {'max_depth': 4}, {'policy': 'v2'}):
            with self.assertRaises(Denied): self.child(**kwargs)

    def test_shared_ancestor_budget(self):
        self.child()
        self.child('sibling')
        self.call('1', mandate='child', agent='worker')
        self.call('2', mandate='child', agent='worker')
        self.call('3', mandate='sibling', agent='worker')
        with self.assertRaises(Denied): self.call('4', mandate='sibling', agent='worker')

    def test_concurrent_connections_cannot_overspend(self):
        def invoke(i):
            g = Guard(self.guard.path, [self.tool], lambda: self.now)
            try:
                g.execute('root', 'parent', 'run', {}, str(i))
                return True
            except Denied:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(invoke, range(20))), 3)
        self.assertEqual(len(self.calls), 3)

    def test_revocation_and_expiry_apply_to_children_and_replays(self):
        self.child()
        self.call(mandate='child', agent='worker')
        self.guard.revoke('root')
        with self.assertRaises(Denied): self.call(mandate='child', agent='worker')

    def test_expiry_boundary(self):
        self.now = 200
        with self.assertRaises(Denied): self.call()

    def test_crash_retains_reservation_and_blocks_retry(self):
        def fail(args): raise RuntimeError('provider outcome unknown')
        self.guard.tools['run'] = Tool('run', 'v1', 3, fail)
        with self.assertRaises(RuntimeError): self.call()
        with self.assertRaises(Denied): self.call()
        with self.guard.tx() as db:
            self.assertEqual(db.execute("SELECT spent FROM mandates WHERE id='root'").fetchone()['spent'], 3)

    def test_restart_replay(self):
        self.call()
        self.guard = Guard(self.guard.path, [self.tool], lambda: self.now)
        self.call()
        self.assertEqual(len(self.calls), 1)

    def test_validation_binds_exact_artifact(self):
        self.guard.create_ticket('t', 'root', 'episode/v1')
        self.guard.assign('a', 't', 'parent', 190)
        self.assertEqual(self.guard.submit('a', 'parent', self.call(), REGISTRY), 'ACCEPTED')
        with self.assertRaises(Denied): self.guard.submit('a', 'parent', {}, REGISTRY)

    def test_failed_validation_cannot_accept(self):
        self.guard.create_ticket('t', 'root', 'episode/v1')
        self.guard.assign('a', 't', 'parent', 190)
        self.assertEqual(self.guard.submit('a', 'parent', {}, REGISTRY), 'REJECTED')

    def test_bad_assignment(self):
        self.guard.create_ticket('t', 'root', 'episode/v1')
        with self.assertRaises(Denied): self.guard.assign('a', 't', 'other', 190)
        self.guard.assign('a', 't', 'parent', 190)
        with self.assertRaises(Denied): self.guard.submit('a', 'other', {}, REGISTRY)
        self.now = 190
        with self.assertRaises(Denied): self.guard.submit('a', 'parent', {}, REGISTRY)

    def test_evidence_tampering(self):
        self.call()
        self.assertTrue(self.guard.verify_receipts())
        with self.guard.tx() as db:
            db.execute("UPDATE receipts SET body='{}' WHERE seq=1")
        self.assertFalse(self.guard.verify_receipts())

    def test_adapter_flow(self):
        m = replace(self.root, id='native')
        DeepSeekHarnessAdapter(self.guard).admit(m, 'ticket', 'assignment', 'episode/v1')
        result = DeepAgentsAdapter(self.guard, 'native', 'parent').call('run', {}, 'native-call')
        self.assertEqual(self.guard.submit('assignment', 'parent', result, REGISTRY), 'ACCEPTED')

    def test_extensions_fail_closed(self):
        with self.assertRaises(NotImplementedError): DisabledPayments().settle('hash', 10, 'USD', 'key')
        with self.assertRaises(NotImplementedError):
            UnavailableZKP().verify(ProofStatement('a', 'b', 'v1', 'c', 'd'), b'proof')

    def test_validator_rejects_boolean_counts(self):
        self.assertFalse(episode_v1({'episodes': 10, 'successful': True}))
        self.assertFalse(episode_v1({'episodes': 10, 'successful': 11}))

    def test_concurrent_same_key_invokes_once(self):
        def invoke(_):
            try:
                return self.call('shared')
            except Denied:
                return None  # In-flight UNKNOWN is deliberately not replayable.
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(invoke, range(16)))
        self.assertEqual(len(self.calls), 1)

    def test_validator_exception_does_not_accept(self):
        self.guard.create_ticket('t', 'root', 'broken/v1')
        self.guard.assign('a', 't', 'parent', 190)
        def broken(artifact): raise RuntimeError('validator unavailable')
        with self.assertRaises(RuntimeError):
            self.guard.submit('a', 'parent', {}, {'broken/v1': broken})
        with self.guard.tx() as db:
            self.assertEqual(db.execute("SELECT state FROM tickets WHERE id='t'").fetchone()['state'], 'RUNNING')

    def test_maximum_delegation_depth(self):
        self.child(max_depth=1)
        grandchild = Mandate('grand', 'tenant', 'worker2', ('run',), 3, 180,
                             parent='child', depth=2, max_depth=1)
        with self.assertRaises(Denied): self.guard.issue(grandchild)

    def test_nonfinite_json_fails_before_execution(self):
        with self.assertRaises(ValueError): self.call(args={'n': float('nan')})
        self.assertEqual(self.calls, [])


if __name__ == '__main__': unittest.main()
