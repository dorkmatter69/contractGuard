"""Storage dialect boundary. PostgreSQL uses one transaction-scoped advisory lock.

All Guard writers cooperate on this lock, including receipt appends. This favors
correctness over throughput; direct SQL writers are outside the trusted protocol.
"""
import sqlite3
from contextlib import contextmanager


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=()):
        # Queries are static SDK SQL, never caller-provided text.
        return self.connection.execute(query.replace('?', '%s'), parameters)

    def executescript(self, script):
        script = script.replace('seq INTEGER PRIMARY KEY', 'seq BIGSERIAL PRIMARY KEY')
        script = script.replace('spent INTEGER', 'spent BIGINT').replace('expires INTEGER', 'expires BIGINT')
        for statement in script.split(';'):
            if statement.strip():
                self.execute(statement)


@contextmanager
def transaction(path):
    if path.startswith(('postgresql://', 'postgres://')):
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(path, autocommit=True, row_factory=dict_row, connect_timeout=10) as db:
            with db.transaction():
                db.execute("SET LOCAL lock_timeout = '30s'")
                db.execute('SELECT pg_advisory_xact_lock(746213091)')
                yield PostgresConnection(db)
        return
    if path == ':memory:':
        raise ValueError('Use a file database; connections are per transaction')
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN IMMEDIATE')
        yield SQLiteConnection(db)
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise
    finally:
        db.close()


class SQLiteConnection:
    def __init__(self, db):
        self.db = db

    def execute(self, query, parameters=()):
        return self.db.execute(query, parameters)

    def executescript(self, script):
        for statement in script.split(';'):
            if statement.strip():
                self.execute(statement)
