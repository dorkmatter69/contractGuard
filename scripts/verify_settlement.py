"""Read-only Base Sepolia verifier; no wallet secrets and no transaction broadcast."""
import argparse
import json
from pathlib import Path
from web3 import Web3
from contractguard.chain_verification import ExpectedSettlement, verify_settlement


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rpc-url', required=True)
    parser.add_argument('--expected', required=True, help='Trusted ExpectedSettlement JSON file')
    parser.add_argument('--transaction', required=True)
    parser.add_argument('--artifact', default='contracts/out/TaskEscrow.sol/TaskEscrow.json')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if not args.rpc_url.startswith('https://'):
        parser.error('HTTPS RPC required')
    expected = ExpectedSettlement(**json.loads(Path(args.expected).read_text()))
    if expected.chain_id != 84532:
        parser.error('this CLI only verifies Base Sepolia')
    artifact = json.loads(Path(args.artifact).read_text())
    w3 = Web3(Web3.HTTPProvider(args.rpc_url, request_kwargs={'timeout': 20}))
    result = verify_settlement(w3, artifact['abi'], args.transaction, expected)
    Path(args.output).write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
