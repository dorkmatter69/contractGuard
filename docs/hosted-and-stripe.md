# Hosted tenants and Stripe

The selected hybrid rail architecture is in [ADR 0006](adr/0006-hybrid-economic-control-plane.md). Stripe is customer billing; Solidity escrow and stablecoin settlement are a separate first-class path. This document describes the existing test-only PaymentIntent sample, not SaaS subscriptions or supplier settlement.

## Current scope

The target is a multi-tenant hosted platform. The implementation uses a shared authenticated front door with an independently bound database per tenant. Test-mode Stripe billing is optional for each tenant. It is not a production SaaS release, supplier payout implementation, escrow system or subscription platform.

The native harness adapters remain fixture bridges. ZKP remains unavailable because no computation/circuit has been selected. The status and baseline documents distinguish these boundaries.

## Hosted registry

Set `CONTRACTGUARD_TENANTS` to a JSON mapping. The following example uses placeholders, not valid credentials:

```json
{
  "organization-a": {
    "database": "postgresql://tenant_a_role:REPLACE@db/tenant_a?sslmode=verify-full",
    "identities": {
      "REPLACE_WITH_SHA256_OPERATOR_TOKEN_HASH": {"role": "operator"},
      "REPLACE_WITH_SHA256_AGENT_TOKEN_HASH": {"role": "agent", "agent": "worker-a"}
    },
    "stripe_api_key_env": "ORG_A_STRIPE_TEST_KEY",
    "stripe_webhook_secret_env": "ORG_A_STRIPE_WEBHOOK_SECRET",
    "stripe_customers": ["cus_REPLACE_WITH_TENANT_CUSTOMER"]
  },
  "organization-b": {
    "database": "postgresql://tenant_b_role:REPLACE@db/tenant_b?sslmode=verify-full",
    "identities": {
      "REPLACE_WITH_DIFFERENT_SHA256_TOKEN_HASH": {"role": "operator"}
    }
  }
}
```

Supply high-entropy raw tokens to clients through a secret manager; the registry holds their SHA256 hashes. Supply the Stripe secrets through the referenced secret environment variables. Do not commit real registry credentials. The bundled registry factory only registers the synthetic simulation tool. Start with:

```sh
gunicorn --bind 127.0.0.1:8080 --workers 2 'contractguard.server:create_hosted_app()'
```

Place TLS, request/time limits and rate limiting upstream. Configure host/domain routing only for presentation; it grants no tenant authority. Tenant context always comes from the token. There is no cross-tenant platform superadmin HTTP role. Configure/reload tenants using a trusted deployment process. Use separate PostgreSQL databases and separate least-privilege roles. Merely separating schemas under one broadly privileged role is not an equivalent defense against compromised database credentials.

The existing Compose file remains a single-tenant development example. For hosted operation provision multiple tenant databases and secrets before launching the hosted factory. No cloud deployment has been performed. Choose hosting region, managed database, TLS/domain and secret-management services before public exposure.

## Stripe test-mode flow

1. Create a Stripe test customer and provision its `cus_...` ID in the tenant's platform-controlled `stripe_customers` allowlist. Create test API and webhook endpoint secrets through Stripe; never paste secret keys in chat or source.
2. Configure `/webhooks/stripe/<tenant-id>` for that tenant with its matching endpoint secret. This endpoint verifies Stripe signatures instead of bearer tokens. Its tenant path selects a secret, not authority to mutate another tenant.
3. Complete and accept a governed ticket. With that tenant's operator token, POST `/v1/billing/intents`:

```json
{"id":"billing-001","ticket":"accepted-ticket-001","amount":100,"currency":"usd","customer":"cus_TENANT_CUSTOMER"}
```

4. The adapter creates an **unconfirmed** test PaymentIntent. It returns an intent ID and PENDING state, not payment success. No automatic confirmation or saved-card charge occurs. Confirm test intents through your Stripe test tooling; a customer-facing confirmation/payment UI is not included.
5. A `payment_intent.succeeded` event must have a valid current signature, matching tenant metadata, allowed request/customer, exact amount/currency/provider ID, test mode and confirmed amount received. Only then is the local collection record marked SUCCEEDED. This is customer collection, not supplier settlement.

Malformed/stale/forged/cross-tenant events fail without state changes. Duplicate event IDs are handled idempotently; delayed failure events cannot downgrade successful collection. Unknown requests and intent mismatches are refused. Keep endpoint secrets isolated per tenant and rotate them operationally; overlapping-secret rotation is not yet implemented. Webhook endpoint logs must not retain raw card/payment data.

Provider timeouts leave UNKNOWN. Repeating the local billing request does not issue another provider call. A correctly bound signed event can reconcile its provider ID/result. If no event arrives, independently inspect Stripe and build an audited provider lookup/reconciliation workflow; do not delete local billing rows or issue a new ID for the same ticket. The one-ticket uniqueness constraint prevents accidental rebilling, but deleting/restoring database records defeats it.

## Boundaries and remaining work

Stripe is selected, but live-mode credentials are deliberately refused by this adapter. Customer onboarding/consent, client-side confirmation, subscriptions, taxes, refunds, chargebacks, fees, currency expansion and account reconciliation remain open. Supplier payments require a defined Stripe Connect account/onboarding/charge model and separate implementation. Stripe PaymentIntents do not turn resource credits into escrow or attest task truth.

Tests use a deterministic injected transport and locally signed fixture events. They exercise actual database/state/signature logic, but they do not establish Stripe API compatibility, account configuration or live webhook delivery. No Stripe account credentials were available and no API request was made.

References: [PaymentIntent creation](https://docs.stripe.com/api/payment_intents/create), [idempotent requests](https://docs.stripe.com/api/idempotent_requests), [webhook handling](https://docs.stripe.com/events/manage-webhook-endpoints), [Stripe Connect](https://docs.stripe.com/connect). Implementation pins API version `2026-10-28.endive`; verify against the provisioned account in a sandbox before enabling hosted billing.
