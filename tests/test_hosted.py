import hashlib
import io
import json
from pathlib import Path
from contractguard import Guard, Mandate
from contractguard.hosted import HostedApplication, Tenant
from contractguard.service import Identity
from tests_support import Fixture


class HostedTests(Fixture):
    def setUp(self):
        super().setUp()
        self.other = Guard(Path(self.tmp.name) / 'other.db', [self.tool], lambda: self.now)
        self.other.issue(Mandate('root', 'tenant-b', 'parent', ('run',), 9, 200))
        self.tokens = [hashlib.sha256(value.encode()).hexdigest() for value in ('a', 'b')]
        self.app = HostedApplication({
            'tenant': Tenant(self.guard, {self.tokens[0]: Identity('operator')}, {}),
            'tenant-b': Tenant(self.other, {self.tokens[1]: Identity('operator')}, {})})

    def request(self, token, path, body):
        raw = json.dumps(body).encode()
        env = {'HTTP_AUTHORIZATION': 'Bearer ' + token, 'REQUEST_METHOD': 'POST', 'PATH_INFO': path,
               'CONTENT_LENGTH': str(len(raw)), 'CONTENT_TYPE': 'application/json', 'wsgi.input': io.BytesIO(raw),
               'HTTP_HOST': 'tenant-b.example.org', 'QUERY_STRING': 'tenant=tenant-b'}
        statuses = []
        output = b''.join(self.app(env, lambda status, headers: statuses.append(status)))
        return statuses[0], json.loads(output)

    def test_colliding_ids_are_isolated(self):
        self.request('a', '/v1/revoke', {'mandate': 'root'})
        with self.other.tx() as db:
            self.assertEqual(db.execute("SELECT revoked FROM mandates WHERE id='root'").fetchone()['revoked'], 0)

    def test_host_header_and_query_cannot_select_tenant(self):
        status, result = self.request('a', '/v1/evidence', {})
        self.assertEqual(status, '200 OK')
        self.assertIn('tenant', result['receipts'][0]['body'])
        self.assertNotIn('tenant-b', result['receipts'][0]['body'])

    def test_cross_tenant_principal_creation_denied(self):
        status, _ = self.request('a', '/v1/mandates', dict(id='new', principal='tenant-b', agent='w',
                                tools=['run'], limit=1, expires=200))
        self.assertEqual(status, '403 Forbidden')

    def test_duplicate_token_rejected(self):
        with self.assertRaises(ValueError):
            HostedApplication({'tenant': Tenant(self.guard, {self.tokens[0]: Identity('operator')}, {}),
                               'tenant-b': Tenant(self.other, {self.tokens[0]: Identity('operator')}, {})})

    def test_shared_database_rejected(self):
        with self.assertRaises(ValueError):
            HostedApplication({'tenant-b': Tenant(self.guard, {self.tokens[1]: Identity('operator')}, {})})

    def test_missing_token(self):
        self.assertEqual(self.request('bad', '/v1/evidence', {})[0], '401 Unauthorized')
