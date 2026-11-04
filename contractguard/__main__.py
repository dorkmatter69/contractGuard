"""Offline demo: no LLM, cloud account, wallet, or external network needed."""
import json
import tempfile
import time
from pathlib import Path
from . import Guard, Mandate, Tool
from .adapters import DeepAgentsAdapter, DeepSeekHarnessAdapter
from .validators import REGISTRY


def main():
    with tempfile.TemporaryDirectory() as directory:
        tool = Tool('simulation.run', 'v1', 3, lambda args: {'episodes': 10, 'successful': 9})
        guard = Guard(Path(directory) / 'guard.db', [tool])
        mandate = Mandate('m1', 'operator', 'worker', ('simulation.run',), 10, int(time.time()) + 60)
        DeepSeekHarnessAdapter(guard).admit(mandate, 't1', 'a1', 'episode/v1')
        result = DeepAgentsAdapter(guard, 'm1', 'worker').call('simulation.run', {}, 'call1')
        state = guard.submit('a1', 'worker', result, REGISTRY)
        print(json.dumps({'state': state, 'receipt_chain_valid': guard.verify_receipts(),
                          'artifact': result, 'simulation': True}, indent=2))


if __name__ == '__main__':
    main()
