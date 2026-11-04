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


def verify_refund(w3, abi, transaction_hash, expected, *, finalized=True):
    """Check expired-task refund, immutable terms and exact Refunded event."""
    receipt, contract = _receipt(w3, abi, transaction_hash, expected, finalized)
    if receipt['status'] != 1:
        raise ValueError('refund transaction failed')
    task = contract.functions.tasks(expected.task_id).call(block_identifier=receipt['blockNumber'])
    _terms(task, expected)
    if task[7] != 3 or w3.eth.get_block(receipt['blockNumber'])['timestamp'] < expected.expires:
        raise ValueError('task not refunded after expiry')
    events = [event for event in contract.events.Refunded().process_receipt(receipt)
              if event['address'].lower() == expected.escrow.lower()
              and hex_value(event['args']['taskId']).lower() == expected.task_id.lower()]
    if (len(events) != 1 or events[0]['args']['payer'].lower() != expected.payer.lower()
            or events[0]['args']['amount'] != expected.amount):
        raise ValueError('refund event mismatch')
    return _result(receipt, expected, 'expiry_refund', finalized)


def verify_replay_rejection(w3, abi, original_tx, replay_tx, expected, *, finalized=True):
    """A failure is replay evidence only for exact original calldata/from/to.

    A random reverted transaction or off-chain exception is insufficient. The
    reverted replay must be mined after the verified successful release, with
    sufficient gas; out-of-gas failure alone is not accepted as replay rejection.
    """
    verify_settlement(w3, abi, original_tx, expected, finalized=finalized)
    receipt, contract = _receipt(w3, abi, replay_tx, expected, finalized)
    first, replay = w3.eth.get_transaction(original_tx), w3.eth.get_transaction(replay_tx)
    original_receipt = w3.eth.get_transaction_receipt(original_tx)
    if (receipt['status'] != 0 or receipt['blockNumber'] <= original_receipt['blockNumber']
            or bytes(replay['input']) != bytes(first['input'])
            or replay['from'].lower() != first['from'].lower()
            or replay['to'].lower() != first['to'].lower()
            or replay['gas'] < first['gas'] or receipt['gasUsed'] >= replay['gas']):
        raise ValueError('not an exact, non-out-of-gas, rejected replay')
    task = contract.functions.tasks(expected.task_id).call(block_identifier=receipt['blockNumber'])
    _terms(task, expected)
    if task[7] != 2:
        raise ValueError('replay changed settled state')
    # Also reproduce the revert at the canonical prior state. This establishes
    # rejection at the already-settled state, rather than a generic RPC failure.
    from web3.exceptions import ContractLogicError, Web3RPCError
    try:
        w3.eth.call({'from': replay['from'], 'to': replay['to'], 'data': replay['input'],
                     'gas': replay['gas']}, block_identifier=receipt['blockNumber'] - 1)
    except (ContractLogicError, Web3RPCError) as error:
        if 'not funded' not in str(error):
            raise ValueError('replay failed for an unexpected reason') from error
    else:
        raise ValueError('replay unexpectedly succeeds against canonical prior state')
    return _result(receipt, expected, 'replay_rejection', finalized)


def _receipt(w3, abi, transaction_hash, expected, finalized):
    if expected.chain_id not in (84532, 31337) or w3.eth.chain_id != expected.chain_id:
        raise ValueError('unexpected/non-test chain')
    if expected.chain_id == 84532 and not finalized:
        raise ValueError('Base Sepolia requires finalized coverage')
    receipt = w3.eth.get_transaction_receipt(transaction_hash)
    if not receipt['to'] or receipt['to'].lower() != expected.escrow.lower():
        raise ValueError('wrong transaction target')
    block = w3.eth.get_block(receipt['blockNumber'])
    if block['hash'] != receipt['blockHash']:
        raise ValueError('noncanonical receipt')
    if finalized and w3.eth.get_block('finalized')['number'] < receipt['blockNumber']:
        raise ValueError('transaction not finalized')
    contract = w3.eth.contract(address=expected.escrow, abi=abi)
    if contract.functions.token().call(block_identifier=receipt['blockNumber']).lower() != expected.token.lower():
        raise ValueError('wrong token')
    return receipt, contract


def _terms(task, expected):
    if (tuple(a.lower() for a in task[:3]) != tuple(a.lower() for a in
            (expected.payer, expected.payee, expected.validator))
            or task[3] != expected.amount or task[4] != expected.expires
            or hex_value(task[5]).lower() != expected.mandate_hash.lower()
            or hex_value(task[6]).lower() != expected.validator_hash.lower()
            or task[8] != expected.settlement_nonce):
        raise ValueError('immutable task terms mismatch')


def _result(receipt, expected, scenario, finalized):
    return {'scenario': scenario, 'chain_id': expected.chain_id,
            'transaction_hash': hex_value(receipt['transactionHash']), 'gas_used': receipt['gasUsed'],
            'block_number': receipt['blockNumber'], 'block_hash': hex_value(receipt['blockHash']),
            'escrow': expected.escrow, 'token': expected.token, 'task_id': expected.task_id,
            'finalized': finalized, 'verified': True}


def verify_funding(w3, abi, transaction_hash, expected, *, finalized=True):
    receipt, contract = _receipt(w3, abi, transaction_hash, expected, finalized)
    if receipt['status'] != 1:
        raise ValueError('funding transaction failed')
    task = contract.functions.tasks(expected.task_id).call(block_identifier=receipt['blockNumber'])
    _terms(task, expected)
    events = [event for event in contract.events.Funded().process_receipt(receipt)
              if event['address'].lower() == expected.escrow.lower()
              and hex_value(event['args']['taskId']).lower() == expected.task_id.lower()]
    if len(events) != 1:
        raise ValueError('one exact funding event required')
    event = events[0]['args']
    if (event['payer'].lower() != expected.payer.lower() or event['payee'].lower() != expected.payee.lower()
            or event['validator'].lower() != expected.validator.lower() or event['amount'] != expected.amount
            or event['expires'] != expected.expires or hex_value(event['mandateHash']).lower() != expected.mandate_hash.lower()
            or hex_value(event['validatorHash']).lower() != expected.validator_hash.lower()):
        raise ValueError('funding event terms mismatch')
    return _result(receipt, expected, 'funding', finalized)
