"""Read-only report collection; never substitutes a plan or fixture for chain evidence."""
import json
import re
from .chain_verification import (ExpectedSettlement, hex_value, verify_funding, verify_refund,
                                 verify_replay_rejection, verify_settlement)
from .core import digest
from .evidence import verify_snapshot


def expected_runtime(artifact, *, token=None):
    """Link the escrow's single immutable token address into compiler runtime data.

    Any additional immutable layout requires a deliberate verifier update. This
    validates deployed runtime against local compiler output, not explorer status.
    """
    output = artifact['deployedBytecode']
    code = bytearray.fromhex(output['object'].removeprefix('0x'))
    references = output.get('immutableReferences', {})
    if token is None and references:
        raise ValueError('unexpected token immutables')
    if token is not None:
        if len(references) != 1 or not re.fullmatch(r'0x[0-9a-fA-F]{40}', token):
            raise ValueError('escrow must have exactly one immutable token')
        for reference in next(iter(references.values())):
            start, length = reference['start'], reference['length']
            if length != 32 or start < 0 or start + length > len(code):
                raise ValueError('unsupported immutable layout')
            code[start:start+length] = int(token, 16).to_bytes(32, 'big')
    if not code:
        raise ValueError('empty runtime')
    return bytes(code)


def verify_offchain_context(manifest, expected):
    snapshot = manifest['evidence_snapshot']
    if not verify_snapshot(snapshot):
        raise ValueError('invalid evidence chain')
    mandate, artifact = manifest['mandate'], manifest['artifact']
    version = manifest['validator_version']
    if ('0x' + digest(mandate) != expected.mandate_hash or '0x' + digest(artifact) != expected.artifact_hash
            or '0x' + digest(version) != expected.validator_hash):
        raise ValueError('off-chain commitments do not match settlement')
    events = [json.loads(row['body']) for row in snapshot['receipts']]
    if not any(e.get('kind') == 'mandate.issued' and e.get('mandate') == mandate for e in events):
        raise ValueError('mandate issuance evidence missing')
    key = manifest['tool_call_key']
    if not any(e.get('kind') == 'call.reserved' and e.get('key') == key
               and e.get('mandate') == mandate['id'] and e.get('agent') == mandate['agent']
               and e.get('tool') in mandate['tools'] and e.get('policy') == mandate['policy']
               and e['timestamp'] < mandate['expires'] for e in events):
        raise ValueError('authorized tool evidence missing')
    if not any(e.get('kind') == 'call.completed' and e.get('key') == key
               and e.get('output_hash') == digest(artifact) for e in events):
        raise ValueError('tool artifact evidence missing')
    if not any(e.get('kind') == 'validation' and e.get('state') == 'ACCEPTED'
               and e.get('ticket') == manifest['ticket'] and e.get('mandate') == mandate['id']
               and e.get('artifact_hash') == digest(artifact) and e.get('validator') == version
               and e['timestamp'] < mandate['expires'] for e in events):
        raise ValueError('accepted evidence missing')
    # Re-run the one approved demo program rather than trusting an ACCEPTED flag.
    from .validators import REGISTRY
    if version not in REGISTRY or REGISTRY[version](artifact) is not True:
        raise ValueError('approved deterministic validation did not pass')
    return {'receipt_head': snapshot['head'], 'artifact_hash': expected.artifact_hash,
            'validator_version': version, 'deterministic_validation_reproduced': True,
            'record_trust': 'operator-supplied unsigned evidence chain; not a ZK receipt'}


def collect_report(w3, artifacts, manifest, *, require_testnet=True):
    chain = w3.eth.chain_id
    if chain != (84532 if require_testnet else 31337):
        raise ValueError('unexpected report network')
    if not re.fullmatch(r'[0-9a-f]{40}', manifest['commit']):
        raise ValueError('exact source commit required')
    expected = ExpectedSettlement(**manifest['expected'])
    refund = ExpectedSettlement(**manifest['refund_expected'])
    if (expected.chain_id != chain or refund.chain_id != chain
            or expected.escrow.lower() != refund.escrow.lower() or expected.token.lower() != refund.token.lower()
            or expected.task_id.lower() == refund.task_id.lower()):
        raise ValueError('scenario networks/contracts/tasks mismatch')
    finalized = require_testnet
    evidence = verify_offchain_context(manifest, expected)
    tx = manifest['transactions']
    deployment = {}
    for name, address in [('token', expected.token), ('escrow', expected.escrow)]:
        receipt = w3.eth.get_transaction_receipt(tx[name + '_deployment'])
        if (receipt['status'] != 1 or not receipt['contractAddress'] or receipt['to']
                or receipt['contractAddress'].lower() != address.lower()
                or w3.eth.get_block(receipt['blockNumber'])['hash'] != receipt['blockHash']):
            raise ValueError('invalid deployment receipt')
        if finalized and w3.eth.get_block('finalized')['number'] < receipt['blockNumber']:
            raise ValueError('deployment not finalized')
        runtime = expected_runtime(artifacts[name], token=expected.token if name == 'escrow' else None)
        actual = bytes(w3.eth.get_code(address, block_identifier=receipt['blockNumber']))
        if runtime != actual or bytes(w3.eth.get_code(address)) != actual:
            raise ValueError('deployed runtime differs from pinned build')
        deployment[name] = {'address': address, 'transaction_hash': hex_value(receipt['transactionHash']),
                            'block_hash': hex_value(receipt['blockHash']), 'gas_used': receipt['gasUsed'],
                            'runtime_keccak256': hex_value(w3.keccak(actual)), 'compiled_runtime_matches': True}
    scenarios = {
        'funding': verify_funding(w3, artifacts['escrow']['abi'], tx['funding'], expected, finalized=finalized),
        'settlement': verify_settlement(w3, artifacts['escrow']['abi'], tx['settlement'], expected, finalized=finalized),
        'replay_rejection': verify_replay_rejection(w3, artifacts['escrow']['abi'], tx['settlement'], tx['replay'], expected, finalized=finalized),
        'refund_funding': verify_funding(w3, artifacts['escrow']['abi'], tx['refund_funding'], refund, finalized=finalized),
        'expiry_refund': verify_refund(w3, artifacts['escrow']['abi'], tx['refund'], refund, finalized=finalized)}
    return {'format': 'contractguard-testnet-validation/v1', 'commit': manifest['commit'], 'chain_id': chain,
            'network': 'base-sepolia' if require_testnet else 'ephemeral-local-anvil',
            'public_testnet_scenarios_verified': require_testnet,
            'compiled_runtime_verified': True, 'explorer_source_publication_checked': False,
            'release_gate_complete': False, 'zkp_experiment_started': False,
            'evidence': evidence, 'deployments': deployment, 'scenarios': scenarios,
            'note': 'An independent RPC and explorer publication record are still required to close the public testnet release gate.'}
