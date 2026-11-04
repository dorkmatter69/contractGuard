"""Read-only independent settlement observer. No signing or transaction methods.

Caller supplies expected terms from trusted authorization records. An RPC endpoint
is still a trust dependency; use independent providers/checkpoints for higher trust.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ExpectedSettlement:
    chain_id: int
    escrow: str
    token: str
    task_id: str
    payer: str
    payee: str
    validator: str
    amount: int
    expires: int
    mandate_hash: str
    validator_hash: str
    artifact_hash: str
    settlement_nonce: int


def hex_value(value):
    return '0x' + bytes(value).hex()


def verify_settlement(w3, abi, transaction_hash, expected, *, finalized=True):
    """Verify canonical receipt, pinned terms and exact Released event on test chains.

    Finalized verification is mandatory for Base Sepolia. Local Anvil can explicitly
    disable it. Submission or latest-head confirmation alone is never called final.
    """
    if expected.chain_id not in (84532, 31337) or w3.eth.chain_id != expected.chain_id:
        raise ValueError('unexpected/non-test chain')
    if expected.chain_id == 84532 and not finalized:
        raise ValueError('Base Sepolia verification requires finalized block coverage')
    receipt = w3.eth.get_transaction_receipt(transaction_hash)
    if receipt['status'] != 1 or receipt['to'].lower() != expected.escrow.lower():
        raise ValueError('failed or wrong-target transaction')
    block = w3.eth.get_block(receipt['blockNumber'])
    if block['hash'] != receipt['blockHash']:
        raise ValueError('noncanonical receipt')
    if finalized and w3.eth.get_block('finalized')['number'] < receipt['blockNumber']:
        raise ValueError('settlement not finalized')
    contract = w3.eth.contract(address=expected.escrow, abi=abi)
    if contract.functions.token().call(block_identifier=receipt['blockNumber']).lower() != expected.token.lower():
        raise ValueError('wrong settlement token')
    task = contract.functions.tasks(expected.task_id).call(block_identifier=receipt['blockNumber'])
    addresses = (expected.payer, expected.payee, expected.validator)
    if tuple(a.lower() for a in task[:3]) != tuple(a.lower() for a in addresses):
        raise ValueError('task parties mismatch')
    if (task[3] != expected.amount or task[4] != expected.expires
            or hex_value(task[5]).lower() != expected.mandate_hash.lower()
            or hex_value(task[6]).lower() != expected.validator_hash.lower()
            or task[7] != 2 or task[8] != expected.settlement_nonce):
        raise ValueError('task terms or terminal state mismatch')
    matches = [event for event in contract.events.Released().process_receipt(receipt)
               if event['address'].lower() == expected.escrow.lower()
               and hex_value(event['args']['taskId']).lower() == expected.task_id.lower()]
    if len(matches) != 1:
        raise ValueError('one exact release event required')
    event = matches[0]['args']
    if (hex_value(event['artifactHash']).lower() != expected.artifact_hash.lower()
            or event['payee'].lower() != expected.payee.lower() or event['amount'] != expected.amount):
        raise ValueError('release event mismatch')
    return {'chain_id': expected.chain_id, 'transaction_hash': hex_value(receipt['transactionHash']),
            'block_number': receipt['blockNumber'], 'block_hash': hex_value(receipt['blockHash']),
            'gas_used': receipt['gasUsed'], 'escrow': expected.escrow, 'token': expected.token,
            'task_id': expected.task_id, 'artifact_hash': expected.artifact_hash,
            'settlement_nonce': expected.settlement_nonce,
            'finalized': finalized, 'verified': True}
