"""Test-first acceptance tests for ``GET /ready`` on the stdlib bootstrap server.

Phase 1 is tests only. The approved contract requires ``GET /ready`` to answer
HTTP 200 with the JSON body ``{"status": "ready", "source_sha": <SOURCE_SHA>}``
where ``source_sha`` mirrors ``/health``: the ``SOURCE_SHA`` environment value
when present, otherwise the literal ``"local"``. The frozen base does not route
``/ready`` (it falls through to the 404 branch of ``do_GET``), so every
assertion here is Red before Phase 2 and turns Green once ``app/server.py``
gains the route, without touching ``/health`` or any other handler.

As in the rest of the suite the real ``http.server`` handler is driven over
loopback and the response status and body are inspected, mirroring the pinned
discovery command (``python3 -m unittest discover -s . -q``).
"""
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen


sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.server import Handler  # noqa: E402


class _QuietHandler(Handler):
    """The real handler with request logging silenced for clean test output."""

    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class ReadyEndpointTests(unittest.TestCase):
    """``GET /ready`` must report readiness and the exact source revision."""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _QuietHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def get(self, path):
        """Fetch a path, returning ``(status, decoded_body)``."""
        request = Request("http://127.0.0.1:%d%s" % (self.port, path))
        try:
            with urlopen(request, timeout=5) as response:
                status = response.status
                raw = response.read()
        except HTTPError as error:
            status = error.code
            raw = error.read()
        return status, raw.decode("utf-8", "replace")

    def test_ready_returns_200_ready_status_and_exact_source_sha(self):
        with patch.dict(os.environ, {"SOURCE_SHA": "b" * 40}):
            status, body = self.get("/ready")
        self.assertEqual(status, 200,
                         "GET /ready must answer HTTP 200, got %r" % status)
        self.assertEqual(json.loads(body), {"status": "ready", "source_sha": "b" * 40},
                         "GET /ready must report readiness and the exact SOURCE_SHA")

    def test_ready_falls_back_to_local_when_source_sha_is_absent(self):
        os.environ.pop("SOURCE_SHA", None)
        status, body = self.get("/ready")
        self.assertEqual(status, 200,
                         "GET /ready must answer HTTP 200, got %r" % status)
        self.assertEqual(json.loads(body), {"status": "ready", "source_sha": "local"},
                         "GET /ready must default source_sha to local")

    def test_ready_body_is_valid_json_with_ready_status_and_source_sha(self):
        status, body = self.get("/ready")
        self.assertEqual(status, 200)
        parsed = json.loads(body)
        self.assertEqual(parsed.get("status"), "ready")
        self.assertIn("source_sha", parsed)


if __name__ == "__main__":
    unittest.main()
