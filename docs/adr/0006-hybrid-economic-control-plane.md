# ADR 0006: Rail-neutral authority, blockchain-native settlement

Status: selected architecture; economic authorization implemented/tested in Python; Solidity source/tests authored, not locally compiled or deployed.

## Decision

ContractGuard's economic control plane decides authority independently of payment transport. Resource credits, monetary commitments, customer billing and actual external settlement are different records. No Stripe callback grants tool permission or accepts an artifact.

First-class economic rails are EVM escrow, x402 and optional Stripe Connect. Monetary budgets bind mandate, rail, exact asset and authorized payees. Delegation attenuates limits/payees and reservations atomically charge all ancestors. Reservations persist before execution and remain held until a future verified reconciliation flow; they are not statements of wallet balance or provider payment success. Per-rail pools must be provisioned independently; no FX or shared-wallet solvency inference exists.

The first blockchain prototype targets Base Sepolia and a public-mint toy ERC-20. Solidity TaskEscrow uses a fixed token, immutable funded terms, payer-namespaced nonce IDs, EIP-712 domain-separated EOA validator signatures, low-s signature enforcement, checks-effects-interactions and a reentrancy guard. A valid acceptance releases funds to the pinned payee once; after expiry the payer can refund once. No admin or proxy can rewrite terms. There is no dispute mechanism or emergency pause in the initial source.

The Python coordinator prepares typed data for an accepted exact artifact and matching reserved terms. It neither signs nor broadcasts. A trusted observer/signer must independently verify the actual canonical funded task and pinned validator address before signing; no RPC observer is implemented yet. The economic reservation ID is not the on-chain task ID. The latter comes from the confirmed Funded event and must be correlated by the observer.

## Rail mapping

| Capability | Selected implementation | Shipped status |
|---|---|---|
| SaaS subscriptions | Stripe Billing | Planned; existing per-ticket PaymentIntent sample is not a subscription |
| Optional fiat supplier payouts | Stripe Connect | Interface/design only |
| Stablecoin escrow and outcome settlement | EVM token adapter + Solidity TaskEscrow | Source/tests and typed-data preparation; uncompiled here, no RPC/broadcast/deployment |
| Pay-per-use agent APIs | x402 | Fail-closed interface only |
| Agent identity/reputation | ERC-8004 | Reference/interface only; not authority |
| Monetary/resource authorization | Off-chain transactional ledgers | Implemented; distinct credits vs base-unit monetary caps |
| Acceptance | Deterministic validation + EIP-712 trusted EOA | Python preparation tested; contract tests awaiting Foundry |
| Proof settlement | ZKP verifier + escrow | Future backend/circuit; not implemented |

## Consequences

Stripe is a billing rail, not ContractGuard's trust root. Blockchain settlement is a first-class design/code path without pretending that all execution runs on-chain. The prototype uses trusted attestations, not a cryptographic proof that a simulation happened. Key compromise, validator dishonesty, chain reorgs, token freezes and deadline disputes remain explicit risks. Testnet/local deployment only; no mainnet or actual funds before independent security/economic validation.
