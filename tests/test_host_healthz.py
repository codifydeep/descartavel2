"""HOSTREC-1: GET /healthz readiness alias.

Real ``app.server.Handler`` served over a local ephemeral HTTPServer; the
production module is exercised unchanged. Pre-existing /ready behavior is
re-checked here so the alias cannot regress it.
"""
import json
import os
import threading
import unittest
from http.server import HTTPServer

from app.server import Handler

ENV_VAR = 'SOURCE_SHA'


class _ServerCase(unittest.TestCase):
    """Spin up a real Handler on an ephemeral port; no production edits."""

    def setUp(self):
        self._saved = os.environ.get(ENV_VAR)
        self._server = HTTPServer(('127.0.0.1', 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        self.addCleanup(self._stop)
        self.host, self.port = self._server.server_address
        self.base = 'http://127.0.0.1:%d' % self.port

    def _stop(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        if self._saved is None:
            os.environ.pop(ENV_VAR, None)
        else:
            os.environ[ENV_VAR] = self._saved

    def _get(self, path):
        import urllib.request
        response = urllib.request.urlopen(self.base + path, timeout=5)
        return response, response.read()


class HealthzAliasTests(_ServerCase):

    def test_healthz_default_status_and_fallback(self):
        os.environ.pop(ENV_VAR, None)
        response, body = self._get('/healthz')
        self.assertEqual(response.status, 200)
        self.assertIn('application/json', response.headers['Content-Type'])
        self.assertEqual(json.loads(body.decode('utf-8')),
                         {'status': 'ready', 'source_sha': 'local'})

    def test_healthz_reports_configured_source_sha(self):
        os.environ[ENV_VAR] = 'abc123'
        response, body = self._get('/healthz')
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(body.decode('utf-8')),
                         {'status': 'ready', 'source_sha': 'abc123'})

    def test_healthz_query_string_does_not_change_route(self):
        os.environ[ENV_VAR] = 'abc123'
        response, body = self._get('/healthz?probe=1&x=ready')
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(body.decode('utf-8')),
                         {'status': 'ready', 'source_sha': 'abc123'})

    def test_ready_behavior_is_preserved(self):
        os.environ[ENV_VAR] = 'abc123'
        response, body = self._get('/ready')
        self.assertEqual(response.status, 200)
        self.assertIn('application/json', response.headers['Content-Type'])
        self.assertEqual(json.loads(body.decode('utf-8')),
                         {'status': 'ready', 'source_sha': 'abc123'})


if __name__ == '__main__':
    unittest.main()
