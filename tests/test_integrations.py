"""Real optional dependencies: never substitute mocks for database compatibility."""
import os
import unittest
from urllib.parse import quote
from uuid import uuid4
from test_guard import GovernanceTests
from tests_support import Fixture
from contractguard import Guard
from contractguard.evidence import analyze


@unittest.skipUnless(os.environ.get('CONTRACTGUARD_TEST_POSTGRES'), 'PostgreSQL test URL not configured')
class PostgresContractTests(GovernanceTests):
    def setUp(self):
        super().setUp()
        import psycopg
        from psycopg import sql
        base = os.environ['CONTRACTGUARD_TEST_POSTGRES']
        schema = 'test_' + uuid4().hex
        with psycopg.connect(base, autocommit=True) as db:
            db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        def cleanup():
            with psycopg.connect(base, autocommit=True) as db:
                db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        self.addCleanup(cleanup)
        url = base + ('&' if '?' in base else '?') + 'options=' + quote('-csearch_path=' + schema)
        self.guard = Guard(url, [self.tool], lambda: self.now)
        self.guard.issue(self.root)


del GovernanceTests


class DuckDBTests(Fixture):
    def test_verified_analytics(self):
        try:
            import duckdb
        except ImportError:
            self.skipTest('DuckDB not installed')
        self.guard.execute('root', 'parent', 'run', {}, 'call')
        result = {r['kind']: r for r in analyze(self.guard.snapshot())}
        self.assertEqual(result['call.reserved']['credits'], 3)
        self.assertEqual(result['call.completed']['count'], 1)
