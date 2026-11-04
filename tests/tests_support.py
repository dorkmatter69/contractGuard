import tempfile
import unittest
from pathlib import Path
from contractguard import Guard, Mandate, Tool


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 100
        self.calls = []
        self.tool = Tool('run', 'v1', 3, self.run_tool)
        self.guard = Guard(Path(self.tmp.name) / 'db', [self.tool], lambda: self.now)
        self.root = Mandate('root', 'tenant', 'parent', ('run',), 9, 200)
        self.guard.issue(self.root)

    def run_tool(self, args):
        self.calls.append(args)
        return {'episodes': 10, 'successful': 9}

