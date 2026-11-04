"""Small authenticated WSGI boundary. Run behind TLS and a production WSGI host.

One service/database per tenant. Tokens identify principals, never request fields.
No credentials or arbitrary tool registration are accepted over this interface.
"""
import hashlib
import hmac
import json
from dataclasses import dataclass
from .core import Denied, Mandate, canonical


@dataclass(frozen=True)
class Identity:
    role: str
    agent: str | None = None


class Application:
    def __init__(self, guard, tenant, tokens, validators, max_body=65536):
        # tokens maps SHA256 token hashes to immutable identities; no raw tokens stored.
        if not tenant or not tokens or any(i.role not in ('operator', 'agent') for i in tokens.values()):
            raise ValueError('tenant and valid token identities required')
        if any(i.role == 'agent' and not i.agent for i in tokens.values()):
            raise ValueError('agent identity required')
        self.guard, self.tenant, self.tokens = guard, tenant, dict(tokens)
        self.validators, self.max_body = dict(validators), max_body
        with guard.tx() as db:
            for row in db.execute('SELECT body FROM mandates'):
                if json.loads(row['body'])['principal'] != tenant:
                    raise ValueError('database belongs to another tenant')

    def authenticate(self, header):
        if not header.startswith('Bearer '):
            raise PermissionError('unauthorized')
        token_hash = hashlib.sha256(header[7:].encode()).hexdigest()
        for expected, identity in self.tokens.items():
            if hmac.compare_digest(token_hash, expected):
                return identity
        raise PermissionError('unauthorized')

    def dispatch(self, identity, path, body):
        g = self.guard
        if identity.role == 'operator':
            if path == '/v1/mandates':
                if body['principal'] != self.tenant:
                    raise Denied('tenant mismatch')
                g.issue(Mandate(**body))
            elif path == '/v1/revoke':
                g.revoke(body['mandate'])
            elif path == '/v1/tickets':
                if body['validator'] not in self.validators:
                    raise Denied('unknown validator')
                g.create_ticket(**body)
            elif path == '/v1/assignments':
                g.assign(**body)
            elif path == '/v1/approvals':
                g.approve(**body)
            elif path == '/v1/cancel':
                g.cancel(body['ticket'])
            elif path == '/v1/reconcile':
                g.reconcile(**body)
            elif path == '/v1/evidence':
                return g.snapshot()
            else:
                raise Denied('route unavailable')
            return {'ok': True}
        if identity.role != 'agent':
            raise Denied('role denied')
        # Reject caller identity overrides, including unknown fields.
        if path == '/v1/execute':
            allowed = {'mandate', 'tool', 'arguments', 'key', 'assignment', 'approval'}
            if set(body) - allowed or not body.get('assignment'):
                raise Denied('assignment required; identity comes from token')
            return {'output': g.execute(agent=identity.agent, **body)}
        if path == '/v1/submit':
            if set(body) != {'assignment', 'artifact'}:
                raise Denied('invalid submission fields')
            return {'state': g.submit(agent=identity.agent, validators=self.validators, **body)}
        raise Denied('operator role required')

    def __call__(self, environ, start_response):
        status = '200 OK'
        try:
            identity = self.authenticate(environ.get('HTTP_AUTHORIZATION', ''))
            if environ.get('REQUEST_METHOD') != 'POST':
                raise Denied('POST required')
            if environ.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
                raise ValueError('application/json required')
            length = int(environ.get('CONTENT_LENGTH', '0'))
            if length <= 0 or length > self.max_body:
                raise ValueError('invalid body size')
            raw = environ['wsgi.input'].read(length)
            if len(raw) != length:
                raise ValueError('incomplete body')
            body = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
            if not isinstance(body, dict):
                raise ValueError('object required')
            result = self.dispatch(identity, environ.get('PATH_INFO', ''), body)
        except PermissionError:
            status, result = '401 Unauthorized', {'error': 'unauthorized'}
        except Denied as error:
            status, result = '403 Forbidden', {'error': str(error)}
        except (ValueError, TypeError, KeyError):
            status, result = '400 Bad Request', {'error': 'invalid request'}
        except Exception:
            # Provider/DB exceptions never leak credentials or arguments to clients.
            status, result = '503 Service Unavailable', {'error': 'operation unavailable; inspect operator logs before retry'}
        payload = canonical(result).encode()
        start_response(status, [('Content-Type', 'application/json'), ('Content-Length', str(len(payload))),
                                ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff')])
        return [payload]
