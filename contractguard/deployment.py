"""Read-only Base Sepolia preflight. Never opens a keystore or unlocks a wallet."""
import os
from pathlib import Path
import re
import shutil
import stat
import urllib.parse


def preflight(*, account='contractguard-base-sepolia-test', environ=None, keystore_root=None,
              locate=shutil.which, chain_id=None):
    environ = os.environ if environ is None else environ
    root = Path.home() / '.foundry' / 'keystores' if keystore_root is None else Path(keystore_root)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', account):
        raise ValueError('invalid keystore alias')
    path = root / account
    # Inspect only filesystem metadata. No ciphertext, password or key is read.
    exists = path.is_file() and not path.is_symlink()
    private_mode = exists and stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    url = environ.get('BASE_SEPOLIA_RPC_URL', '')
    valid_url = bool(url and urllib.parse.urlparse(url).scheme == 'https' and urllib.parse.urlparse(url).netloc)
    rpc_verified = False
    error = None
    if valid_url and chain_id is not None:
        try:
            rpc_verified = chain_id(url) == 84532
        except Exception:
            error = 'RPC lookup failed; endpoint and credentials redacted'
    checks = {'forge_available': bool(locate('forge')), 'cast_available': bool(locate('cast')),
              'keystore_exists': exists, 'keystore_permissions_private': bool(private_mode),
              'rpc_configured_https': valid_url, 'rpc_chain_84532_verified': rpc_verified}
    return {'account': account, 'rpc_environment_variable': 'BASE_SEPOLIA_RPC_URL', 'checks': checks,
            'configuration_checks_passed': all(checks.values()),
            'signer_unlock_verified': False, 'deployment_authorized_by_this_report': False,
            'note': 'Keystore decryption/address and signer funds require a trusted interactive operator; this report cannot authorize broadcast.',
            'error': error}
