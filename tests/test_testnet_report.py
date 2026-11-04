from dataclasses import asdict
from copy import deepcopy
from contractguard.chain_verification import ExpectedSettlement
from contractguard.core import digest
from contractguard.testnet_report import expected_runtime, verify_offchain_context
from tests_support import Fixture


class TestnetReportTests(Fixture):
    def test_runtime_immutable_linking_is_exact(self):
        artifact = {'deployedBytecode': {'object': '0x00' * 0 + '00' * 40,
                    'immutableReferences': {'token': [{'start': 4, 'length': 32}]}}}
        address = '0x' + '12' * 20
        result = expected_runtime(artifact, token=address)
        self.assertEqual(result[4:36], int(address, 16).to_bytes(32, 'big'))
        self.assertEqual(result[:4], b'\x00' * 4)
        with self.assertRaises(ValueError): expected_runtime(artifact)
        bad = deepcopy(artifact); bad['deployedBytecode']['immutableReferences']['unexpected'] = []
        with self.assertRaises(ValueError): expected_runtime(bad, token=address)

    def test_report_reproduces_approved_validation(self):
        import json
        self.guard.create_ticket('t', 'root', 'episode/v1')
        self.guard.assign('a', 't', 'parent', 190)
        artifact = self.guard.execute('root', 'parent', 'run', {}, 'call', assignment='a')
        from contractguard.validators import REGISTRY
        self.guard.submit('a', 'parent', artifact, REGISTRY)
        mandate = json.loads(json.dumps(asdict(self.root)))
        manifest = {'mandate': mandate, 'artifact': artifact, 'validator_version': 'episode/v1',
                    'tool_call_key': 'call', 'ticket': 't', 'evidence_snapshot': self.guard.snapshot()}
        expected = ExpectedSettlement(84532, 'escrow', 'token', 'task', 'payer','payee','validator',100,180,
                    '0x'+digest(mandate), '0x'+digest('episode/v1'), '0x'+digest(artifact), 0)
        self.assertTrue(verify_offchain_context(manifest, expected)['deterministic_validation_reproduced'])
        changed = deepcopy(manifest); changed['artifact']['successful'] = 0
        with self.assertRaises(ValueError): verify_offchain_context(changed, expected)
        changed = deepcopy(manifest); changed['tool_call_key'] = 'unknown'
        with self.assertRaises(ValueError): verify_offchain_context(changed, expected)
        changed = deepcopy(manifest); changed['evidence_snapshot']['head'] = '0'*64
        with self.assertRaises(ValueError): verify_offchain_context(changed, expected)
