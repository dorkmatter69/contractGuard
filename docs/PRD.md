# Product requirements

> Baseline 0.1 design. Implemented 0.2 changes and remaining release gates are tracked in [status](status.md), [deployment](deployment.md), and [ADR 0004](adr/0004-shared-control-plane.md). Where baseline limitations differ, those documents supersede them.

## Problem and users

Operators need to delegate work to agents while bounding authority and resource use and retaining verifiable acceptance evidence. Initial users are agent platform developers and internal workflow teams. The first demonstrator is a synthetic episode-validation workflow; it establishes no robotics performance claim or commercial demand.

## MVP requirements and acceptance

| Requirement | Acceptance / implementation |
|---|---|
| Framework independence | Core has no harness imports or runtime dependencies |
| Least privilege | Child cannot broaden tools, tenant, policy, expiry, limit or depth |
| Hierarchical budgets | Concurrent reservations charge every ancestor; tests admit exactly three 3-credit calls under a 9-credit root |
| Gateway | Identity/scope/expiry checked before registered tools run |
| Recovery | Completed calls replay; uncertain calls are not automatically retried |
| Evidence | Linked events bind request/output hashes and tool/policy versions; simple tampering detected |
| Acceptance | Trusted deterministic validator binds exact submitted JSON to ticket/mandate/version |
| Adapters | Local fixtures exercise Deep Agents bridge and normalized DSH admission |
| Extensions | ZKP/payments throw explicitly rather than returning simulated success |

## Non-goals for 0.1

No autonomous procurement, real currency, escrow, cryptographic capability tokens, real proof generation, blockchain deployment, framework interception guarantee, hosted API, dashboard or production SLA. No PostgreSQL/DuckDB runtime adapter yet. Human approvals and compensation are deferred rather than represented as bypassable boolean flags.

## Milestones

1. **0.1 local reference (implemented):** core gateway, durable credit reservations, receipts, deterministic acceptance, fixture adapters, offline demo, tests, docs and CI definition.
2. **0.2 shared control plane (planned):** authenticated service, PostgreSQL backend/migrations, tenant isolation, transactional outbox, assignment-bound tool calls, lease renewal/cancellation, scoped approvals, crash recovery CLI and backup/restore fencing. Exit: multi-process races and fault injection pass; no credential bypass in integration environment.
3. **0.3 integration pilot (planned):** pin and test real Deep Agents/DSH versions, isolate providers and validators, argument-level resource policy, object storage, signed checkpoints, read-only DuckDB export/analytics. Exit: representative workflow demonstrates accepted value and complete traceability.
4. **0.4 optional commerce (planned):** one sandbox payment provider, double-entry monetary ledger, quote binding, idempotent settlement, unknown-outcome reconciliation and approval scopes. Exit: replay/duplicate charge/timeout tests pass; no unresolved funds handling risks.
5. **Research track (unscheduled):** one narrowly specified ZKP circuit with public statement binding and malicious-proof tests; audited settlement contracts only if a multi-party trust need is demonstrated.

## Metrics

Measure accepted deliverables per human intervention, cost per accepted deliverable, denied action rate, uncertain-call backlog, trace completeness and authorization latency. Future service targets: p95 decision under 30 ms and 99.9% availability are **unmeasured goals**, not commitments. Local unit-test duration is not a production benchmark.

## Production release gates

Independent threat review, authenticated tenant boundaries, all protected tool paths mediated, agent credential isolation, provider-enforced maximum resource consumption, revocation semantics documented, reconciliation and restore drills, signed evidence checkpoints, real framework end-to-end tests and operational incident procedures. Do not market the initial repository as production-ready.
