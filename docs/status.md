# Implementation and release status

This file is the current implementation inventory; the original 0.1 architecture/PRD remain a design baseline.

## v0.5 execution evidence

Commit `a2b1254` passed all seven jobs in [CI run 41870669068](https://github.com/dorkmatter69/contractGuard/actions/runs/41870669068): 15 Foundry tests, 103 passing Python/database tests in the PostgreSQL/DuckDB lane (one cross-layer skip), a separate real Anvil/PostgreSQL cross-layer test, plus Python 3.11–3.14 package/test jobs. The archived transaction/gas artifact is local Anvil only. Acceptance domain v2 explicitly binds validator address and settlement nonce; validators can permanently self-revoke. A read-only finalized settlement verifier and metadata-only deployment preflight are included.

Base Sepolia remains undeployed. The proposed `contractguard-base-sepolia-test` keystore is absent and `BASE_SEPOLIA_RPC_URL` is unset. No key was read or created. See [v0.5 deployment gates](v0.5-validation.md). ZKP remains the subsequent experiment, not implemented acceptance.

## 0.4 hybrid economic architecture (historical baseline)

The owner selected rail-neutral authority with blockchain-native settlement as first-class, Stripe Billing for subscriptions, optional Stripe Connect, x402 and ERC-8004 future adapters. A separate Python monetary ledger now enforces per-rail/asset/payee mandate authority, attenuated child budgets and atomic ancestor reservations. Accepted exact artifacts can produce EIP-712 data. Authenticated economic endpoints expose these controls.

Solidity TaskEscrow, a no-value toy token, Foundry tests and a Base Sepolia/local-only deployment script are authored. Foundry/solc are absent, so they have NOT been compiled or executed locally. There is no chain observer, signer, RPC transaction adapter or deployed escrow. Source code is not a working on-chain integration claim. See [blockchain status](blockchain.md) and [ADR 0006](adr/0006-hybrid-economic-control-plane.md).

## Implemented in 0.3

The owner selected a multi-tenant hosted service and Stripe. HostedApplication selects tenant only through token ownership and dispatches to a persistently bound, isolated database. Duplicate token ownership and foreign database bindings are refused. An optional Stripe TEST-MODE collection adapter creates unconfirmed PaymentIntents for accepted tickets, restricted to platform-provisioned tenant customers. Signed raw-body webhooks bind exact request/amount/customer/tenant/provider ID, deduplicate events and handle timeout/ordering recovery. Live keys are rejected. No external Stripe request has been made; provider transport uses fixtures in tests. See [hosted setup](hosted-and-stripe.md) and [ADR 0005](adr/0005-hosted-tenants-and-stripe.md).

## Implemented in 0.2

- PostgreSQL dialect using Psycopg, BIGINT credit balances, BIGSERIAL receipt ordering, transaction-scoped advisory locking and transactional additive schema initialization. SQLite remains supported.
- Single-tenant bearer-authenticated WSGI service with operator/agent separation. Agent identity is token-bound. Service execution requires an active matching assignment. The in-process trusted SDK allows optional assignments.
- Exact-action, expiring, single-use approvals for tools configured to require them. Version, charge, key and arguments are bound.
- Ticket cancellation; cancelled tickets cannot admit further assignment-bound execution or submit artifacts. Already-admitted I/O cannot be undone.
- UNKNOWN-result reconciliation with operator-supplied independent provider reference, credits retained and result commitment audited. Operators must quiesce original workers first. Concurrent late completion cannot overwrite a reconciled result.
- Consistent receipt snapshots, portable chain checking, external HMAC checkpoints and DuckDB event/credit aggregation.
- Minimal HTTPS client without automatic retries or redirects. Demo service factory, optional deployment extras and container/Compose definitions.
- Separate OS process budget-race and crash-after-reservation tests, HTTP boundary tests, and optional real PostgreSQL/DuckDB contract tests in CI.

## Verification interpretation

Standard-library tests execute locally. Optional database/analytics tests skip when dependencies/services are absent, and this is reported explicitly. GitHub's database-contract job is required evidence before claiming PostgreSQL/DuckDB compatibility. WSGI tests invoke the actual application through WSGI environments; they do not test a deployed TLS proxy, production load, container image hardening or cloud availability.

## Open completion gates

1. Verify dependency-backed CI and container startup; review authorization and provider boundaries independently.
2. Pin and test native framework SDK versions; cover every built-in/delegated tool path. Current adapters remain explicit fixture-tested bridges.
3. Isolate agents and provider credentials; implement resource-specific policy and provider-enforced consumption limits.
4. Isolate large validators; add independent measurement provenance, asynchronous claim/complete semantics and richer artifact storage.
5. Implement backup/restore fencing, secret rotation procedures, telemetry, general migrations, lease renewal/reassignment and operational recovery drills. Schema v2 is additive only.
6. Stripe is selected. The rail split is now selected: Stripe Billing subscriptions, optional Connect suppliers, and first-class blockchain escrow. Implement actual subscriptions, verify test-account integration, and add onboarding, confirmation and monetary reconciliation before live use. Credits are not money. Generic settlement remains disabled.
7. Select a specific computation/circuit, proving system, trusted setup/key custody and public statement schema before implementing ZKP. Existing verifier remains unavailable. Escrow source/tests are authored; no compiled or deployed blockchain integration exists.
8. Select license, security contact and production support expectations before public release.

The repository is not the entire production platform described in the roadmap. Features requiring missing provider/circuit/deployment decisions remain open rather than being replaced by mock success.
