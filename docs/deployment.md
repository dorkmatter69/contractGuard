# Deployment, API and databases

## Python setup

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install '.[postgres,analytics,server]'
python -m unittest discover -s tests -v
```

Optional extras require package-index access. Keep the standard-library offline path for core development.

## Service configuration

Use a separate database and service deployment per tenant. Provision separate high-entropy bearer tokens for operators and each agent; store raw tokens in your secret manager. `CONTRACTGUARD_IDENTITIES` contains SHA256 hexadecimal hashes, not the tokens themselves:

```json
{
  "<64-character operator token hash>": {"role": "operator"},
  "<64-character worker token hash>": {"role": "agent", "agent": "worker-a"}
}
```

These angle-bracket values are placeholders. Generate at least 32 random bytes per token (for example with Python `secrets.token_urlsafe(32)`), compute SHA256 of the encoded token, and substitute actual hashes. Do not commit token values. Configure `CONTRACTGUARD_TENANT` and `CONTRACTGUARD_DATABASE` (an absolute SQLite path or PostgreSQL URI). The application refuses startup if existing mandates belong to a different tenant. Use TLS and request/rate/time limits at a reverse proxy. Authorization uses static configuration; rotate/revoke tokens by replacing configuration and restarting every worker. Do not log Authorization headers.

```sh
gunicorn --bind 127.0.0.1:8080 --workers 2 'contractguard.server:create_app()'
```

The bundled factory registers only a synthetic `simulation.run` tool. It cannot provision compute or execute code. Build your own trusted factory for real tools. Never let agents modify the registry, validators, configuration or database.

## PostgreSQL and containers

Set a strong URL-safe `POSTGRES_PASSWORD`, tenant and identities in your local environment, then run `docker compose up --build -d`. Compose binds both API and database ports to loopback. The API image runs as a non-root user, read-only filesystem, no added capabilities. This is a development deployment, not a TLS endpoint or a production operations plan. PostgreSQL data persists in a named volume. Do not run `docker compose down -v` on data you need.

For a managed database, use TLS-enabled connection settings (`sslmode=verify-full` plus trusted CA configuration). Do not expose the DSN in logs or source. Guard writers serialize using one advisory lock, so validators must be short and bounded. The database role needs schema creation during initialization; separate migration and runtime roles before production. No pool, general migration engine or restore fencing exists yet.

Integration test URL must point to a disposable database with schema creation privileges:

```sh
export CONTRACTGUARD_TEST_POSTGRES='postgresql://user:password@localhost:5432/disposable_test_db'
python -m unittest discover -s tests -v
```

Tests create random schemas and drop only those schemas in cleanup. Never use your production database for tests.

## API

All routes accept POST JSON, bearer authentication, bounded bodies (64 KiB default) and return JSON with no-store caching. TLS and header limits belong at the WSGI server/proxy. Errors: 401 authentication, 403 authority/state denial, 400 invalid request, 503 unavailable execution/storage. The client does not retry or follow redirects.

| Route | Role | JSON fields |
|---|---|---|
| `/v1/mandates` | operator | Mandate fields from the core |
| `/v1/revoke` | operator | `mandate` |
| `/v1/tickets` | operator | `id`, `mandate`, `validator` |
| `/v1/assignments` | operator | `id`, `ticket`, `agent`, `expires` |
| `/v1/approvals` | operator | `id`, `mandate`, `agent`, `tool`, `arguments`, `key`, `expires`, optional `assignment` |
| `/v1/cancel` | operator | `ticket` |
| `/v1/reconcile` | operator | `key`, `output`, `reference` |
| `/v1/evidence` | operator | empty object |
| `/v1/execute` | agent | `mandate`, `tool`, `arguments`, `key`, `assignment`, optional `approval` |
| `/v1/submit` | agent | `assignment`, `artifact` |

Token-bound agent identity cannot be overridden in execute/submit payloads. Operators administer all state in their dedicated database. The raw trusted core remains a privileged API, not a network interface. Operator creation/import routes reject duplicate identifiers but do not offer transactional batch admission; inspect partial imports before retrying.

## Evidence and analytics

Call `guard.snapshot()` as operator, then `verify_snapshot(snapshot)`. Persist `checkpoint(snapshot, secret_key)` in independently controlled storage; key must be at least 32 bytes. Check future exports against that trusted saved anchor using `verify_checkpoint`. These checkpoints bind exact count/head: a newer valid export will need a new trusted anchor or historical-prefix verification. Current helper is exact-snapshot verification. HMAC holders can forge checkpoints, so it is not suitable for mutually distrustful organizations.

`analyze(snapshot)` uses DuckDB to return counts/credits by event kind. Snapshot bodies include identities, mandate metadata and reconciliation references. Sanitize references and control export access. Tool artifacts/raw outputs remain outside this export. The analytics result is not an authoritative financial balance, dashboard or monetary audit.

## Incident recovery

On UNKNOWN calls, quiesce the originating worker, consult provider logs and establish the actual result independently. Only after confirmed success use `/v1/reconcile` with output and provider evidence reference. Credits remain held; no refund, forced retry or failure-confirmation endpoint exists. Stop execution during database restore until all external effects and revoked authority are reconciled. Cancellation and revocation do not kill admitted external work; revoke provider credentials separately when necessary.
