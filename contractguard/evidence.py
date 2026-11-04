"""Portable local evidence checks and HMAC checkpoints for trusted organizations.

HMAC is shared-secret authentication, not a public signature or a ZK proof.
Keep keys and trusted checkpoints outside the database being protected.
"""
import hashlib
import hmac
from .core import canonical, digest


def verify_snapshot(snapshot):
    try:
        previous = '0' * 64
        last_seq = 0
        rows = snapshot['receipts']
        for row in rows:
            if (row['seq'] <= last_seq or row['previous'] != previous
                    or row['hash'] != digest([previous, row['body']])):
                return False
            previous, last_seq = row['hash'], row['seq']
        return snapshot['version'] == 1 and snapshot['head'] == previous and snapshot['count'] == len(rows)
    except (KeyError, TypeError, ValueError):
        return False


def checkpoint(snapshot, key):
    if len(key) < 32 or not verify_snapshot(snapshot):
        raise ValueError('valid snapshot and at least 32-byte key required')
    statement = {'version': 1, 'head': snapshot['head'], 'count': snapshot['count']}
    return {'statement': statement,
            'mac': hmac.new(key, canonical(statement).encode(), hashlib.sha256).hexdigest()}


def verify_checkpoint(snapshot, anchor, key):
    try:
        expected = checkpoint(snapshot, key)
        return (anchor['statement'] == expected['statement']
                and hmac.compare_digest(anchor['mac'], expected['mac']))
    except (ValueError, KeyError, TypeError):
        return False


def analyze(snapshot):
    """Query a verified export in an isolated in-memory DuckDB, never the ledger."""
    if not verify_snapshot(snapshot):
        raise ValueError('invalid receipt snapshot')
    import duckdb
    import json
    with duckdb.connect(':memory:') as db:
        db.execute('CREATE TABLE events(kind VARCHAR, credits BIGINT)')
        values = [(json.loads(row['body'])['kind'], json.loads(row['body']).get('cost', 0))
                  for row in snapshot['receipts']]
        if values:
            db.executemany('INSERT INTO events VALUES (?, ?)', values)
        return [{'kind': kind, 'count': count, 'credits': credits}
                for kind, count, credits in db.execute(
                    'SELECT kind,count(*),sum(credits) FROM events GROUP BY kind ORDER BY kind').fetchall()]
