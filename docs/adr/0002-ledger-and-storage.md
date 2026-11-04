# ADR 0002: Atomic credit reservations and database roles

Status: accepted for local MVP; PostgreSQL/DuckDB planned.

Context: Concurrent child agents must not independently spend the same parent capacity. External side effects cannot share a database transaction.

Decision: Reserve fixed integer resource credits on every ancestor under SQLite BEGIN IMMEDIATE before I/O. Persist UNKNOWN first and retain charges on uncertainty. PostgreSQL will become the shared authority after explicit locking/migration/fault tests. DuckDB will consume read-only analytics exports.

Consequences: Local setup is reproducible without infrastructure. Credits are conservative charges, not a monetary ledger. SQLite serializes writers; large validators block admission. No automatic retry or refund is safe without provider reconciliation. PostgreSQL and DuckDB support are designs, not shipped drivers.
