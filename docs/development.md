# Development and operations

> Baseline 0.1 design. Implemented 0.2 changes and remaining release gates are tracked in [status](status.md), [deployment](deployment.md), and [ADR 0004](adr/0004-shared-control-plane.md). Where baseline limitations differ, those documents supersede them.

## Local setup

Use Python 3.11 or newer. Run `python3 -m unittest discover -s tests -v` and `python3 -m contractguard` from repository root. Optional editable installation and command are in the README. No `.env`, API key or network service is required. For a persistent workflow, pass a filesystem path to `Guard`; `:memory:` is unsupported because methods use separate connections.

## Adding a tool

Register a `Tool(name, immutable_version, fixed_credit_charge, callable)` from trusted host code. Validate arguments in the callable against permitted resource IDs and safe schemas. Bound external consumption at the provider, use scoped credentials, cap output size and propagate the request identity to a provider idempotency API when implementing future providers. The present callable interface takes only arguments; do not pretend it supplies provider idempotency automatically. Do not log secret inputs. The host must handle credential distribution independently.

## Adding a validator

Add a pure function to an operator-controlled registry with a fresh immutable version key. Pin data/model/environment versions into that key or a future richer acceptance schema. Test both passing and failing artifacts, malformed values and boundary thresholds. A validator exception leaves the ticket RUNNING; an ordinary false result ends it REJECTED. No worker-supplied executable validator is permitted. The example compares integer counts; it does not invoke tests in an untrusted checkout.

## Harness wiring

Bind `DeepAgentsAdapter` to a mandate and authenticated agent in the host. Pass stable framework invocation IDs to `call`. Register wrappers that route protected operations to that method. Built-in filesystem, shell and delegated tools need their own interception and credential isolation; fixture tests are not live SDK tests. Native SDK imports are intentionally absent until versions are selected and tested.

For DeepSeek, authenticate and normalize native Mandate/Ticket/Assignment records in trusted host code, then call `DeepSeekHarnessAdapter.admit`. The mapping performs three separate transactions; partial admission is possible. On error inspect persisted state instead of blind replay. Native event schemas/transport are future adapter work. Never treat GitHub issue authorship or issue text alone as authorization.

## Inspect and recover

SQLite tables are `mandates`, `calls`, `receipts`, `tickets`, `assignments`. Use read-only inspection for normal operations. `Guard.verify_receipts()` checks local chain continuity. Retain a trusted external checkpoint before relying on integrity claims.

For UNKNOWN calls: stop retries, identify the provider operation from independent provider logs, establish whether it ran, and reconcile the accounting under a documented operator change procedure. This MVP intentionally supplies no force-retry/refund switch. Do not change UNKNOWN to COMPLETED without independently confirmed output. Never delete an idempotency record to retry a consequential action. Provider-aware reconciliation is a milestone requirement.

Revocation is `guard.revoke(mandate_id)` and cascades logically through ancestor checks. It stops new admissions, not in-flight provider work. Revoke provider credentials separately when necessary. Restoring an older database may resurrect revoked authority and lose idempotency records; keep execution disabled until an operator reconciles provider history and authority changes. No migrations or automated restore protocol are implemented.

## CI and contribution

CI checks standard-library tests, demo, installation and installed command on four Python versions. Add a regression test for new security behavior; avoid network requirements in unit tests. Keep future adapters explicitly unavailable until integration tests exist. Never add real credentials, billing data, `.db` files or secret artifacts to Git. New dependencies require justification and version management. Choose a license before public redistribution; no license has been inferred on the owner's behalf.
