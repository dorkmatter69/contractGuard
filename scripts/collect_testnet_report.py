"""Read-only dual-RPC collection. Writes no success report until both agree."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from web3 import Web3
from contractguard.testnet_report import collect_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    primary, independent = os.environ['BASE_SEPOLIA_RPC_URL'], os.environ['BASE_SEPOLIA_VERIFICATION_RPC_URL']
    if (any(urlparse(url).scheme != 'https' or not urlparse(url).hostname for url in (primary, independent))
            or urlparse(primary).hostname == urlparse(independent).hostname):
        parser.error('two HTTPS RPC endpoints on different provider hosts are required')
    manifest = json.loads(Path(args.manifest).read_text())
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if manifest['commit'] != commit:
        parser.error('checkout must match the exact manifest build commit')
    artifacts = {name: json.loads(Path(path).read_text()) for name, path in {
        'token': 'contracts/out/TestUSD.sol/TestUSD.json', 'escrow': 'contracts/out/TaskEscrow.sol/TaskEscrow.json'}.items()}
    # Wallet secrets are neither read nor accepted. Redirects are not followed by
    # the explicit requests Session supplied to the read-only RPC providers.
    import requests
    reports = []
    for url in (primary, independent):
        class NoRedirectSession(requests.Session):
            def request(self, *args, **kwargs):
                kwargs['allow_redirects'] = False
                return super().request(*args, **kwargs)
        w3 = Web3(Web3.HTTPProvider(url, session=NoRedirectSession(), request_kwargs={'timeout': 20}))
        reports.append(collect_report(w3, artifacts, manifest))
    if reports[0] != reports[1]:
        raise ValueError('RPC providers disagree; no report written')
    report = reports[0]
    report['independent_rpc_agreement'] = True
    report['note'] = 'Two RPC providers agree. Record explorer source publication separately before closing v0.6.'
    Path(args.output).write_text(json.dumps(report, indent=2))


if __name__ == '__main__': main()
