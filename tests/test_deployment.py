import tempfile
from pathlib import Path
import unittest
from contractguard.deployment import preflight


class DeploymentTests(unittest.TestCase):
    def test_missing_config_never_authorizes_broadcast(self):
        with tempfile.TemporaryDirectory() as directory:
            report = preflight(environ={}, keystore_root=directory, locate=lambda _: None)
        self.assertFalse(report['configuration_checks_passed'])
        self.assertFalse(report['deployment_authorized_by_this_report'])

    def test_chain_and_private_mode_required_without_reading_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'contractguard-base-sepolia-test'
            path.write_text('not a wallet; preflight must never treat metadata as signing proof')
            path.chmod(0o600)
            args = dict(environ={'BASE_SEPOLIA_RPC_URL': 'https://example.test/secret'},
                        keystore_root=directory, locate=lambda _: '/fixture/bin')
            report = preflight(**args, chain_id=lambda _: 84532)
            self.assertTrue(report['configuration_checks_passed'])
            self.assertFalse(report['signer_unlock_verified'])
            self.assertNotIn('secret', str(report))
            self.assertFalse(preflight(**args, chain_id=lambda _: 8453)['configuration_checks_passed'])
            path.chmod(0o644)
            self.assertFalse(preflight(**args, chain_id=lambda _: 84532)['configuration_checks_passed'])

    def test_account_path_traversal_rejected(self):
        with self.assertRaises(ValueError): preflight(account='../wallet')
