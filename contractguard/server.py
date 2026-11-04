"""Configured demo service factory: gunicorn 'contractguard.server:create_app()'.

Only a synthetic, bounded tool is registered. Replace it in a trusted host module
for real work; never import untrusted tool code or accept tool registration via API.
"""
import json
import os
from .core import Guard, Tool
from .service import Application, Identity
from .validators import REGISTRY


def create_app():
    identities = json.loads(os.environ['CONTRACTGUARD_IDENTITIES'])
    if any(len(key) != 64 or any(c not in '0123456789abcdef' for c in key) for key in identities):
        raise ValueError('identity keys must be SHA256 hexadecimal token hashes')
    guard = Guard(os.environ['CONTRACTGUARD_DATABASE'], [
        Tool('simulation.run', 'v1', 3, lambda args: {'episodes': 10, 'successful': 9})
    ])
    return Application(guard, os.environ['CONTRACTGUARD_TENANT'],
                       {key: Identity(**value) for key, value in identities.items()}, REGISTRY)


def create_hosted_app():
    """One immutable registry, isolated database and Stripe secrets per tenant.

    Registry provisioning is an administrative deployment operation. There is no
    untrusted self-service database or credential configuration endpoint.
    """
    from .hosted import HostedApplication, Tenant
    from .stripe_billing import StripeBilling, StripeTestTransport
    registry = json.loads(os.environ['CONTRACTGUARD_TENANTS'])
    tenants = {}
    for tenant, config in registry.items():
        guard = Guard(config['database'], [
            Tool('simulation.run', 'v1', 3, lambda args: {'episodes': 10, 'successful': 9})])
        billing = None
        if 'stripe_api_key_env' in config:
            billing = StripeBilling(guard, tenant,
                StripeTestTransport(os.environ[config['stripe_api_key_env']]),
                os.environ[config['stripe_webhook_secret_env']], config['stripe_customers'])
        tokens = config['identities']
        if any(len(key) != 64 or any(c not in '0123456789abcdef' for c in key) for key in tokens):
            raise ValueError('identity keys must be SHA256 hexadecimal token hashes')
        tenants[tenant] = Tenant(guard, {key: Identity(**value) for key, value in tokens.items()}, REGISTRY, billing)
    if not tenants:
        raise ValueError('at least one tenant required')
    return HostedApplication(tenants)
