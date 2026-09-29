"""Protected baseline test; future cards may add tests but not weaken this one."""
import json
from io import BytesIO
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.server import Handler  # noqa: E402


class BootstrapHealthTests(unittest.TestCase):
    def test_health_reports_the_exact_source_sha(self):
        handler = Handler.__new__(Handler)
        handler.path = '/health'
        handler.wfile = BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        with patch.dict(os.environ, {'SOURCE_SHA': 'a' * 40}):
            handler.do_GET()
        handler.send_response.assert_called_once_with(200)
        self.assertEqual(json.loads(handler.wfile.getvalue()),
                         {'status': 'ok', 'source_sha': 'a' * 40})


if __name__ == '__main__':
    unittest.main()
