# Threat model

> Baseline 0.1 design. Implemented 0.2 changes and remaining release gates are tracked in [status](status.md), [deployment](deployment.md), and [ADR 0004](adr/0004-shared-control-plane.md). Where baseline limitations differ, those documents supersede them.

## Assets and assumptions

Protect delegated authority, controlled resources, provider credentials, execution uniqueness, acceptance state and evidence. Agents, prompts, artifacts, tool outputs and inbound comments are untrusted. Operator host, configured tool/validator code, OS and database administrators are trusted in the local MVP. A malicious operator can issue authority or rewrite storage. This is a library, not an OS sandbox or authentication service.

| Threat | Implemented control | Residual risk / production requirement |
|---|---|---|
| Prompt injection widens scope | Immutable mandates; no text-to-permission conversion | Host must not issue new authority from model text without policy |
| Child escalates permissions | Parent subset, principal/policy/expiry/depth checks | No signed capability or remote identity protocol |
| Spoofed identity | Trusted bridge binds identity | Direct SDK caller can supply any string; isolate operator API |
| Sibling budget race | Atomic lineage charges under write lock | Does not constrain external spend outside fixed provider bound |
| Duplicate side effect | Durable fingerprint and UNKNOWN-before-I/O | DB restore/loss, alternate keys or direct provider calls can duplicate work |
| Failure after side effect | UNKNOWN holds credits, retry denied | Operator reconciliation required; no automated recovery implementation |
| Revoked ancestor | Rechecked on call/submission | In-flight calls continue; lease expiry does not gate mandate tool use |
| Arbitrary arguments target unauthorized resource | Trusted provider implementation required | Tool allowlist alone is insufficient for general shell/network tools |
| Forged artifact | Versioned deterministic rule on exact artifact | Supplied metrics can be lies; trusted measurement and independent rerun needed |
| Evidence edits | Hash-linked receipts | Full rewrite/suffix deletion undetected without external checkpoint |
| Secret leakage | Inputs committed instead of logged | Outputs/artifacts stored in clear; hashes are not encryption/redaction |
| Validator denial of service | Only operator-owned validator registry | Runs under DB lock; no timeout/process isolation yet |
| Tenant data exposure | Principal continuity within a mandate lineage | No tenant query API or row-level isolation; use separate DBs in MVP |
| Forged ZK proof/payment success | Unavailable backends raise | No actual proof or settlement trust established |
| Database outage/disk full | Reservation transaction must commit before I/O | Success completion can fail after I/O; preserve UNKNOWN and reconcile |

## Abuse tests and remaining work

Tests exercise identity/scope denial, attenuation, parent exhaustion, concurrency across independent connections, expiry, revocation, replay fingerprint conflicts, simulated provider failure, restarts, bad assignments, failed acceptance and receipt edits. They do not prove process isolation, cryptographic security, framework interception, power-loss durability or production load behavior.

Before multi-tenant deployment: isolate credentials and workers, authenticate all entry points, add scoped approvals, limit input/output size, configure database encryption/permissions/backups, sign and externalize receipt checkpoints, harden tool argument schemas and provider resource limits, test crash windows in separate processes, pin dependency/actions revisions and conduct an independent review.
