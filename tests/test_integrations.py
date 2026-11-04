"""Real optional dependencies: never substitute mocks for database compatibility."""
import os
import unittest
from urllib.parse import quote
from uuid import uuid4
from test_guard import GovernanceTests
from test_economics import EconomicTests
from tests_support import Fixture
from contractguard import Guard
from contractguard.evidence import analyze


class PostgresFixture:
    def setUp(self):
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
        self.database_url = base + ('&' if '?' in base else '?') + 'options=' + quote('-csearch_path=' + schema)
        super().setUp()


@unittest.skipUnless(os.environ.get('CONTRACTGUARD_TEST_POSTGRES'), 'PostgreSQL test URL not configured')
class PostgresContractTests(PostgresFixture, GovernanceTests):
    pass


@unittest.skipUnless(os.environ.get('CONTRACTGUARD_TEST_POSTGRES'), 'PostgreSQL test URL not configured')
class PostgresEconomicTests(PostgresFixture, EconomicTests):
    pass


del GovernanceTests, EconomicTests


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
