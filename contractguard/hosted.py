"""Hosted routing with database-per-tenant isolation and token-bound tenant choice.

Provisioning is operator configuration, never an API accepting database URLs.
Each Application persistently binds its database to its tenant identifier.
"""
import hashlib
import hmac
from dataclasses import dataclass
from .service import Application
from .core import canonical


@dataclass(frozen=True)
class Tenant:
    guard: object
    tokens: dict
    validators: dict
    billing: object | None = None


class HostedApplication:
    def __init__(self, tenants):
        self.apps, self.routes, self.billing = {}, {}, {}
        for tenant, config in tenants.items():
            if config.billing is not None and (config.billing.tenant != tenant or config.billing.guard is not config.guard):
                raise ValueError('billing configuration crosses tenant boundary')
            self.apps[tenant] = Application(config.guard, tenant, config.tokens, config.validators, billing=config.billing)
            self.billing[tenant] = config.billing
            for token in config.tokens:
                if token in self.routes:
                    raise ValueError('a token must belong to exactly one tenant')
                self.routes[token] = tenant

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path.startswith('/webhooks/stripe/'):
            tenant = path.removeprefix('/webhooks/stripe/')
            billing = self.billing.get(tenant)
            if billing is None:
                return self.error(start_response, '404 Not Found', 'endpoint unavailable')
            try:
                length = int(environ.get('CONTENT_LENGTH', '0'))
                if environ.get('REQUEST_METHOD') != 'POST' or not 0 < length <= 262144:
                    raise ValueError('invalid webhook request')
                raw = environ['wsgi.input'].read(length)
                if len(raw) != length:
                    raise ValueError('incomplete body')
                billing.webhook(raw, environ.get('HTTP_STRIPE_SIGNATURE', ''))
                return self.error(start_response, '200 OK', 'received')
            except (ValueError, KeyError, TypeError):
                return self.error(start_response, '400 Bad Request', 'invalid webhook')
            except Exception:
                return self.error(start_response, '503 Service Unavailable', 'temporarily unavailable')
        header = environ.get('HTTP_AUTHORIZATION', '')
        candidate = hashlib.sha256(header[7:].encode()).hexdigest() if header.startswith('Bearer ') else ''
        for token, tenant in self.routes.items():
            if hmac.compare_digest(token, candidate):
                # Tenant comes only from a trusted token mapping. Host headers,
                # request fields and query strings cannot change the database.
                return self.apps[tenant](environ, start_response)
        return self.error(start_response, '401 Unauthorized', 'unauthorized')

    @staticmethod
    def error(start_response, status, message):
        data = canonical({'message': message}).encode()
        start_response(status, [('Content-Type', 'application/json'), ('Content-Length', str(len(data))),
                                ('Cache-Control', 'no-store')])
        return [data]
