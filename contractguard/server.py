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
