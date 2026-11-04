# Security

This is a local reference MVP. Review [the threat model](docs/threat-model.md) before use. Do not connect unrestricted payment/cloud credentials or execute untrusted code in the operator process.

For vulnerabilities, use this repository's private vulnerability reporting feature if enabled; otherwise contact the repository owner privately through an established channel. Do not publish credentials or exploit details in a public issue. No security response SLA is promised.


Hosted deployments use token-bound routing and a separate persistently bound database per tenant. Stripe is test-mode only; tenant customer allowlists are configured by the platform, and signed webhooks must match exact stored amounts and identities. Do not treat offline fixture tests as Stripe integration verification. Live keys are refused. Refer to docs/hosted-and-stripe.md for remaining hosted/payment release gates.


Solidity escrow source is experimental and uncompiled/unexecuted in this environment. It trusts an EOA validator and configured standard token; no audit, ZKP, dispute handling, pause mechanism, chain observer, signer or mainnet deployment is provided. Never fund it with actual assets. Monetary reservations do not prove wallet solvency or external settlement. See docs/blockchain.md.
