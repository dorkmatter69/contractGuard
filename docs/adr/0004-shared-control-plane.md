# ADR 0004: Shared control plane and authenticated service

Status: implemented in 0.2 development; optional integrations awaiting execution evidence.

Supersedes the planned-only PostgreSQL/DuckDB status and the unauthenticated/mandate-only service limitations in the baseline documents.

## Decision

Add an optional Psycopg backend selected by a PostgreSQL URL. Every core transaction takes the same PostgreSQL transaction-scoped advisory lock before reading authority or appending receipts. This serializes cooperating writers across hosts and avoids lineage lock-order deadlocks. It intentionally trades throughput for a simple, testable invariant. SQLite remains the default offline backend. Both now execute schema statements inside the existing transaction instead of SQLite executescript's implicit commit.

Schema version 2 is additive: approvals and schema-version tables are added to existing 0.1 databases. The core columns are unchanged. Legacy call fingerprints do not include assignment; reusing their keys now yields a conflict rather than rerunning them. Back up before upgrading and retain old request/output audit records. Version recording is not a general migration framework or restore fencing protocol.

The service is one tenant per database/deployment. Bearer token hashes map to operator or bound agent identities. Every agent execution requires a matching active assignment, checked in the reservation transaction. Operator methods are inaccessible to agent tokens. TLS terminates upstream. Hosted multi-tenancy with row-level security remains out of scope.

Tools can require approvals that bind exact mandate/agent/arguments/assignment/idempotency key/tool version/cost. Grants expire and are consumed atomically with reservation. A completed replay does not consume another approval. Operator reconciliation can confirm an UNKNOWN result with an independent provider audit reference; it cannot refund credits, force retry or attest that the provider evidence is authentic.

Evidence exports include chain count/head; external HMAC checkpoints authenticate them within a shared-secret organization. A saved trusted anchor detects suffix truncation; recreating a checkpoint from a tampered database does not. This is not a public signature. DuckDB reads verified exports into its own in-memory database, never authoritative balances.

## Consequences

PostgreSQL service throughput is serialized at transaction boundaries; provider I/O remains outside the lock. Validation still runs under the lock. Token revocation requires configuration reload and worker restart. No automatic provider retry, monetary ledger, ZKP circuit or blockchain functionality is implied. Test installation and database behavior in CI before calling these integrations verified.
