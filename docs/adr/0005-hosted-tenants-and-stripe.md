# ADR 0005: Hosted tenant isolation and Stripe test billing

Status: implemented for offline contract testing; no live Stripe verification.

## Context

The owner selected a multi-tenant hosted service and Stripe. This supersedes single-tenant deployment as the product target, while retaining database-per-tenant as the isolation mechanism. The payment provider alone does not determine whether the product bills customers, pays suppliers or operates a marketplace.

## Decision

A hosted WSGI router maps bearer token hashes to a tenant before dispatch. Each tenant has an independent Guard database with persistent tenant binding, validators and token/role mapping. The existing authenticated Application handles tenant operations. Duplicate token ownership and shared-database tenant mismatches are refused. Provisioning remains trusted platform configuration; API callers cannot choose database URLs, credentials or token ownership.

Start Stripe with a test-only customer collection path, pending confirmation of supplier payout requirements. StripeTestTransport rejects live keys and creates unconfirmed PaymentIntents with an explicit API version. A persistent billing request binds accepted ticket, amount in USD cents, customer and tenant. Each ticket can be billed once. The platform configures a customer allowlist per tenant; tenant operators cannot add arbitrary Stripe customers through the API. There is no automatic confirmation, client-secret exposure, card handling, Stripe Connect transfer or supplier payout.

Persist UNKNOWN before provider I/O. Derive an opaque tenant-qualified Stripe idempotency key. Never automatically retry an UNKNOWN request, including beyond Stripe's retention window. Signed raw-body Stripe webhook events authenticate updates, require test mode, match tenant/customer/amount/intent, record deduplicated event IDs and avoid downgrading successful collections on delayed failure events. Creation responses never themselves establish payment success. A matching signed event can recover an intent whose creation timed out.

## Consequences

The service can host multiple organizations while preserving separate state stores. This increases provisioning, backup and connection-management costs. For PostgreSQL, use separate databases and narrowly scoped roles rather than request-provided search paths. Shared-table RLS, self-service signup, SSO, invitation management, subscription billing, customer onboarding UI and Connect are not implemented.

Only test-mode billing exists; real settlement requires provider/account onboarding, chosen charging model, customer consent and payment-method confirmation flow, refund/dispute handling, monetary reconciliation and production security verification. Credits are still not a monetary ledger. ZKP remains disabled pending a specified computation/circuit.
