"""Protect the infrastructure seed, not future product acceptance criteria."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.request import urlopen


class Infrastructure(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen(
            [sys.executable, '-B', str(Path(__file__).parents[1] / 'app.py'), '0'],
            env={**os.environ, 'FABRIQUINHA_SOURCE_SHA': 'a' * 40},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop)
        self.port = int(self.process.stdout.readline())

    def stop(self):
        self.process.terminate()
        self.process.communicate(timeout=3)

    def test_health(self):
        with urlopen(f'http://127.0.0.1:{self.port}/health', timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), {'status': 'ok'})

    def test_identity_uses_runtime_sha(self):
        with urlopen(f'http://127.0.0.1:{self.port}/identity', timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), {'source_sha': 'a' * 40})
