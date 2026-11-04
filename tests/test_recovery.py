import subprocess
import sys
import unittest
from tests_support import Fixture
from contractguard import Denied


class RecoveryTests(Fixture):
    def test_real_process_exit_after_reservation(self):
        program = '''
import os, sys
from contractguard import Guard, Tool

def crash(args):
    os._exit(23)

g = Guard(sys.argv[1], [Tool('run', 'v1', 3, crash)], lambda: 100)
g.execute('root', 'parent', 'run', {}, 'crash-key')
'''
        result = subprocess.run([sys.executable, '-c', program, self.guard.path], timeout=15)
        self.assertEqual(result.returncode, 23)
        with self.assertRaises(Denied):
            self.guard.execute('root', 'parent', 'run', {}, 'crash-key')
        with self.guard.tx() as db:
            row = db.execute("SELECT spent FROM mandates WHERE id='root'").fetchone()
            self.assertEqual(row['spent'], 3)
        self.assertTrue(self.guard.verify_receipts())

    def test_multiple_os_processes_share_ceiling(self):
        program = '''
import sys
from contractguard import Guard, Tool, Denied

g = Guard(sys.argv[1], [Tool('run', 'v1', 3, lambda args: {})], lambda: 100)
try:
    g.execute('root', 'parent', 'run', {}, sys.argv[2])
except Denied:
    sys.exit(7)
'''
        workers = [subprocess.Popen([sys.executable, '-c', program, self.guard.path, str(i)])
                   for i in range(8)]
        codes = [worker.wait(timeout=15) for worker in workers]
        self.assertEqual(codes.count(0), 3)
        self.assertEqual(codes.count(7), 5)
