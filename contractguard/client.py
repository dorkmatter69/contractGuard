"""Minimal authenticated HTTP client. No implicit retries of side effects."""
import json
import urllib.request
from .core import canonical


class Client:
    def __init__(self, url, token, timeout=30):
        if not url.startswith('https://') and not url.startswith(('http://127.0.0.1:', 'http://localhost:')):
            raise ValueError('HTTPS required outside localhost')
        self.url, self.token, self.timeout = url.rstrip('/'), token, timeout

    def post(self, path, **body):
        if not path.startswith('/v1/') or '?' in path or '#' in path:
            raise ValueError('invalid API path')
        request = urllib.request.Request(self.url + path, data=canonical(body).encode(),
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}, method='POST')
        # Reject redirects rather than forwarding bearer credentials to a new host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=self.timeout) as response:
            return json.load(response)
