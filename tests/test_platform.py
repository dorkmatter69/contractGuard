import hashlib
import io
import json
import unittest
from tests_support import Fixture
from contractguard import Denied, Tool
from contractguard.evidence import checkpoint, verify_checkpoint, verify_snapshot
from contractguard.service import Application, Identity


class PlatformTests(Fixture):
    def setUp(self):
        super().setUp()
        self.guard.create_ticket('ticket', 'root', 'episode/v1')
        self.guard.assign('lease', 'ticket', 'parent', 190)
        self.app = Application(self.guard, 'tenant', {
            hashlib.sha256(b'operator-secret').hexdigest(): Identity('operator'),
            hashlib.sha256(b'worker-secret').hexdigest(): Identity('agent', 'parent'),
            hashlib.sha256(b'other-secret').hexdigest(): Identity('agent', 'other'),
        }, {'episode/v1': lambda a: a == {'valid': True}})

    def request(self, path, body, token='worker-secret'):
        data = json.dumps(body).encode()
        env = {'HTTP_AUTHORIZATION': 'Bearer ' + token, 'REQUEST_METHOD': 'POST',
               'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(data)),
               'wsgi.input': io.BytesIO(data), 'PATH_INFO': path}
        statuses = []
        result = b''.join(self.app(env, lambda status, headers: statuses.append(status)))
        return statuses[0][:3], json.loads(result)

    def payload(self):
        return dict(mandate='root', tool='run', arguments={}, key='k', assignment='lease')

    def test_authenticated_execution(self):
        self.assertEqual(self.request('/v1/execute', self.payload())[0], '200')
        self.assertEqual(self.request('/v1/execute', self.payload(), 'bad')[0], '401')
        self.assertEqual(self.request('/v1/execute', self.payload(), 'other-secret')[0], '403')

    def test_identity_override_denied(self):
        self.assertEqual(self.request('/v1/execute', dict(self.payload(), agent='other'))[0], '403')

    def test_agent_cannot_administer_or_export(self):
        for route in ('/v1/evidence', '/v1/mandates', '/v1/reconcile', '/v1/approvals'):
            self.assertEqual(self.request(route, {})[0], '403')

    def test_cancellation_blocks_new_execution(self):
        self.guard.cancel('ticket')
        self.assertEqual(self.request('/v1/execute', self.payload())[0], '403')
        self.assertEqual(self.request('/v1/submit', {'assignment': 'lease', 'artifact': {}})[0], '403')

    def test_lease_expiry_blocks_execution(self):
        self.now = 190
        self.assertEqual(self.request('/v1/execute', self.payload())[0], '403')

    def test_approval_exact_action_and_single_use(self):
        self.guard.tools['run'] = Tool('run', 'v1', 3, self.run_tool, True)
        self.assertEqual(self.request('/v1/execute', self.payload())[0], '403')
        self.guard.approve('approval', 'root', 'parent', 'run', {}, 'k', 180, 'lease')
        changed = dict(self.payload(), arguments={'changed': True}, approval='approval')
        self.assertEqual(self.request('/v1/execute', changed)[0], '403')
        original = dict(self.payload(), approval='approval')
        self.assertEqual(self.request('/v1/execute', original)[0], '200')
        self.assertEqual(self.request('/v1/execute', original)[0], '200')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.request('/v1/execute', dict(original, key='other'))[0], '403')

    def test_expired_approval(self):
        self.guard.tools['run'] = Tool('run', 'v1', 3, self.run_tool, True)
        self.guard.approve('approval', 'root', 'parent', 'run', {}, 'k', 110, 'lease')
        self.now = 110
        self.assertEqual(self.request('/v1/execute', dict(self.payload(), approval='approval'))[0], '403')

    def test_confirmed_reconciliation(self):
        def fail(args): raise RuntimeError('secret provider message')
        self.guard.tools['run'] = Tool('run', 'v1', 3, fail)
        status, response = self.request('/v1/execute', self.payload())
        self.assertEqual(status, '503')
        self.assertNotIn('secret', json.dumps(response))
        self.guard.reconcile('k', {'confirmed': True}, 'provider-audit-1')
        self.assertEqual(self.request('/v1/execute', self.payload())[1]['output'], {'confirmed': True})
        with self.assertRaises(Denied): self.guard.reconcile('k', {}, 'second')

    def test_snapshot_external_checkpoint_detects_truncation(self):
        snapshot = self.guard.snapshot()
        key = b'x' * 32
        anchor = checkpoint(snapshot, key)
        self.assertTrue(verify_snapshot(snapshot))
        self.assertTrue(verify_checkpoint(snapshot, anchor, key))
        snapshot['receipts'].pop()
        snapshot['head'] = snapshot['receipts'][-1]['hash']
        snapshot['count'] -= 1
        self.assertTrue(verify_snapshot(snapshot))
        self.assertFalse(verify_checkpoint(snapshot, anchor, key))

    def test_tenant_mismatch_refused(self):
        with self.assertRaises(ValueError):
            Application(self.guard, 'other-tenant', self.app.tokens, {})

    def test_missing_assignment(self):
        body = self.payload(); del body['assignment']
        self.assertEqual(self.request('/v1/execute', body)[0], '403')

    def test_acceptance_through_service(self):
        self.assertEqual(self.request('/v1/submit', {'assignment': 'lease', 'artifact': {'valid': True}}),
                         ('200', {'state': 'ACCEPTED'}))
