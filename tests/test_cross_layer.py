"""Actual Python → Anvil → Solidity integration, never a simulated EVM success.

CI REQUIRE_CROSS_LAYER=1 makes missing tools/dependencies fatal instead of a skip.
Only an ephemeral local chain and its public disposable wallets are supported.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from dataclasses import asdict

from contractguard import Guard, Mandate, Tool, Denied
from contractguard.core import digest
from contractguard.economics import EconomicLedger, MoneyBudget, EscrowBinding


class CrossLayerTests(unittest.TestCase):
    def test_mandate_to_verified_local_settlement(self):
        missing = [name for name in ('forge', 'anvil') if not shutil.which(name)]
        if importlib.util.find_spec('web3') is None:
            missing.append('web3')
        if missing:
            if os.environ.get('REQUIRE_CROSS_LAYER') == '1':
                self.fail('required integration dependencies missing: ' + ', '.join(missing))
            self.skipTest('integration dependencies missing: ' + ', '.join(missing))
        from web3 import Web3
        from eth_account import Account
        from eth_account.messages import encode_typed_data
        root = Path(__file__).resolve().parents[1]
        subprocess.run(['forge', 'build'], cwd=root / 'contracts', check=True, capture_output=True, timeout=180)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        node = subprocess.Popen(['anvil', '--host', '127.0.0.1', '--port', str(port), '--silent'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: self.stop(node))
        w3 = Web3(Web3.HTTPProvider(f'http://127.0.0.1:{port}', request_kwargs={'timeout': 5}))
        for _ in range(100):
            if w3.is_connected(): break
            if node.poll() is not None: self.fail('Anvil exited during startup')
            time.sleep(0.1)
        self.assertTrue(w3.is_connected(), 'Anvil startup timed out')
        self.assertEqual(w3.eth.chain_id, 31337, 'local chain only')
        payer, payee = w3.eth.accounts[:2]
        # Public fixture key used only for local signatures, never a funded wallet.
        validator = Account.from_key((1).to_bytes(32, 'big'))
        receipts = []
        def mined(tx):
            receipt = w3.eth.wait_for_transaction_receipt(tx, timeout=20)
            self.assertEqual(receipt.status, 1)
            self.assertEqual(w3.eth.get_block(receipt.blockNumber).hash, receipt.blockHash)
            receipts.append({'transaction_hash': receipt.transactionHash.hex(), 'gas_used': receipt.gasUsed,
                             'block_number': receipt.blockNumber, 'block_hash': receipt.blockHash.hex()})
            return receipt
        def deploy(name, *args):
            artifact = json.loads((root / 'contracts' / 'out' / f'{name}.sol' / f'{name}.json').read_text())
            factory = w3.eth.contract(abi=artifact['abi'], bytecode=artifact['bytecode']['object'])
            receipt = mined(factory.constructor(*args).transact({'from': payer}))
            return w3.eth.contract(address=receipt.contractAddress, abi=artifact['abi'])
        token = deploy('TestUSD'); escrow = deploy('TaskEscrow', token.address)
        now = lambda: w3.eth.get_block('latest').timestamp
        with tempfile.TemporaryDirectory() as directory:
            # Integration job can exercise a disposable PostgreSQL database too.
            database = os.environ.get('CONTRACTGUARD_CROSS_LAYER_DATABASE', str(Path(directory) / 'guard.db'))
            guard = Guard(database, [Tool('simulate', 'v1', 2, lambda args: {'episodes': 10, 'successful': 9})], now)
            mandate = Mandate('cross-layer', 'tenant', 'worker', ('simulate',), 10, now() + 7200)
            guard.issue(mandate)
            guard.create_ticket('ticket', mandate.id, 'episode/v1')
            guard.assign('assignment', 'ticket', 'worker', mandate.expires)
            ledger = EconomicLedger(guard)
            asset = f'eip155:31337/erc20:{token.address}'
            ledger.allocate(MoneyBudget(mandate.id, 'evm-escrow', asset, 200, (payee,)))
            expires = now() + 3600
            ledger.reserve('order', mandate.id, 'worker', 'assignment', 'ticket', 'evm-escrow', asset, 100, payee, expires)
            guard.create_ticket('refund-ticket', mandate.id, 'episode/v1')
            guard.assign('refund-assignment', 'refund-ticket', 'worker', mandate.expires)
            refund_expires = now() + 600
            ledger.reserve('refund-order', mandate.id, 'worker', 'refund-assignment', 'refund-ticket',
                           'evm-escrow', asset, 100, payee, refund_expires)
            result = guard.execute(mandate.id, 'worker', 'simulate', {}, 'call', assignment='assignment')
            mined(token.functions.mint(payer, 200).transact({'from': payer}))
            mined(token.functions.approve(escrow.address, 200).transact({'from': payer}))
            mh, vh = '0x' + digest(asdict(mandate)), '0x' + digest('episode/v1')
            funded = mined(escrow.functions.fund(payee, validator.address, 100, expires, mh, vh).transact({'from': payer}))
            event = escrow.events.Funded().process_receipt(funded)[0]['args']
            task_id = event['taskId']
            # Independently read immutable funded terms, not just transaction submission.
            task = escrow.functions.tasks(task_id).call()
            self.assertEqual(tuple(task[:5]), (payer, payee, validator.address, 100, expires))
            self.assertEqual(task[5].hex(), mh[2:]); self.assertEqual(task[6].hex(), vh[2:])
            from contractguard.validators import REGISTRY
            self.assertEqual(guard.submit('assignment', 'worker', result, REGISTRY), 'ACCEPTED')
            binding = EscrowBinding(31337, escrow.address, '0x' + task_id.hex(), asset, payee, 100, expires,
                                    mh, vh, expires - 1, validator.address, task[8])
            typed = ledger.acceptance('order', binding)
            message = encode_typed_data(full_message=typed)
            signed = Account.sign_message(message, validator.key)
            artifact_hash = typed['message']['artifactHash']
            self.assertEqual(signed.message_hash, escrow.functions.acceptanceDigest(task_id, artifact_hash, binding.deadline).call())
            before = token.functions.balanceOf(payee).call()
            released = mined(escrow.functions.release(task_id, artifact_hash, binding.deadline, signed.signature).transact({'from': payer}))
            release = escrow.events.Released().process_receipt(released)[0]['args']
            self.assertEqual(release['taskId'], task_id); self.assertEqual(release['payee'], payee)
            self.assertEqual(release['amount'], 100)
            self.assertEqual(token.functions.balanceOf(payee).call() - before, 100)
            self.assertEqual(escrow.functions.tasks(task_id).call()[7], 2)
            from contractguard.chain_verification import ExpectedSettlement, verify_settlement
            expected = ExpectedSettlement(31337, escrow.address, token.address, '0x' + task_id.hex(), payer,
                payee, validator.address, 100, expires, mh, vh, artifact_hash, task[8])
            independent = verify_settlement(w3, escrow.abi, released.transactionHash, expected, finalized=False)
            self.assertTrue(independent['verified'])
            from dataclasses import replace
            for changed in (replace(expected, amount=101), replace(expected, settlement_nonce=999),
                            replace(expected, artifact_hash='0x' + 'ff' * 32)):
                with self.assertRaises(ValueError):
                    verify_settlement(w3, escrow.abi, released.transactionHash, changed, finalized=False)
            # Mine the exact replay with enough gas, then independently establish
            # that it reverted because the task was already settled.
            original = w3.eth.get_transaction(released.transactionHash)
            replay_hash = escrow.functions.release(task_id, artifact_hash, binding.deadline, signed.signature).transact(
                {'from': payer, 'gas': original['gas']})
            replay = w3.eth.wait_for_transaction_receipt(replay_hash)
            self.assertEqual(replay.status, 0)
            from contractguard.chain_verification import verify_replay_rejection, verify_refund
            rejected = verify_replay_rejection(w3, escrow.abi, released.transactionHash, replay_hash, expected, finalized=False)
            self.assertTrue(rejected['verified'])
            # Simulate the operator-facing no-key funding script on the actual
            # local RPC. It must compile and run without accessing a wallet key.
            script_env = dict(os.environ, ESCROW_ADDRESS=escrow.address, PAYER_ADDRESS=payer,
                              PAYEE_ADDRESS=payee, VALIDATOR_ADDRESS=validator.address, TASK_AMOUNT='100',
                              TASK_EXPIRES=str(refund_expires), MANDATE_HASH=mh, VALIDATOR_HASH=vh)
            subprocess.run(['forge', 'script', 'script/Scenarios.s.sol:FundScenario', '--rpc-url',
                            f'http://127.0.0.1:{port}', '--sender', payer],
                           cwd=root / 'contracts', env=script_env, capture_output=True, check=True, timeout=120)
            refunded_funding = mined(escrow.functions.fund(payee, validator.address, 100, refund_expires, mh, vh).transact({'from': payer}))
            refund_task = escrow.events.Funded().process_receipt(refunded_funding)[0]['args']['taskId']
            refund_state = escrow.functions.tasks(refund_task).call()
            refund_expected = replace(expected, task_id='0x' + refund_task.hex(), expires=refund_expires,
                                      settlement_nonce=refund_state[8])
            w3.provider.make_request('evm_increaseTime', [max(0, refund_expires - now())])
            w3.provider.make_request('evm_mine', [])
            refund_receipt = mined(escrow.functions.refund(refund_task).transact({'from': payer}))
            refund_checked = verify_refund(w3, escrow.abi, refund_receipt.transactionHash, refund_expected, finalized=False)
            self.assertTrue(refund_checked['verified'])
            self.assertEqual(token.functions.balanceOf(payer).call(), 100)
            self.assertEqual(token.functions.balanceOf(payee).call(), 100)
            self.assertEqual(token.functions.balanceOf(escrow.address).call(), 0)
            self.assertTrue(guard.verify_receipts())
            if os.environ.get('CROSS_LAYER_REPORT'):
                Path(os.environ['CROSS_LAYER_REPORT']).write_text(json.dumps({
                    'network': 'ephemeral-local-anvil', 'chain_id': 31337, 'is_testnet_deployment': False,
                    'escrow': escrow.address, 'token': token.address, 'task_id': task_id.hex(),
                    'artifact_hash': artifact_hash, 'receipts': receipts, 'independent_verification': independent, 'replay_rejection': rejected, 'expiry_refund': refund_checked, 'verified': True}, indent=2))

    @staticmethod
    def stop(node):
        if node.poll() is None:
            node.terminate()
            try: node.wait(timeout=5)
            except subprocess.TimeoutExpired:
                node.kill(); node.wait(timeout=5)
