"""Inspect configuration and read eth_chainId without touching key material."""
import argparse
import json
from pathlib import Path
import urllib.request
from contractguard.deployment import preflight


def rpc_chain_id(url):
    # Do not forward an authenticated RPC URL or data to a redirect destination.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl): return None
    request = urllib.request.Request(url, data=b'{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}',
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
        return int(json.load(response)['result'], 16)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--account', default='contractguard-base-sepolia-test')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = preflight(account=args.account, chain_id=rpc_chain_id)
    Path(args.output).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report['configuration_checks_passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
