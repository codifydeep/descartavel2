"""SUPREC-1: GET /livez liveness alias.

Real ``app.server.Handler`` served over a local ephemeral HTTPServer; the
production module is exercised unchanged (no mocks, no fixed port, no
external service). The liveness contract is asserted through the wire:
HTTP 200, ``application/json`` and the exact JSON body ``{"status": "ok"}``.
Query strings must not change the route, and the pre-existing ``/health``
and ``/healthz`` routes must stay byte-compatible.
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


class LivezAliasTests(_ServerCase):

    def test_livez_is_http_200_json_ok(self):
        os.environ[ENV_VAR] = 'abc123'
        response, body = self._get('/livez')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/json')
        self.assertEqual(json.loads(body.decode('utf-8')), {'status': 'ok'})

    def test_livez_body_is_exactly_status_ok(self):
        os.environ[ENV_VAR] = 'abc123'
        response, body = self._get('/livez')
        self.assertEqual(response.status, 200)
        # Exact shape: no source_sha (or any other key) may leak in.
        self.assertEqual(json.loads(body.decode('utf-8')), {'status': 'ok'})

    def test_livez_query_string_does_not_change_route(self):
        os.environ[ENV_VAR] = 'abc123'
        response, body = self._get('/livez?probe=1')
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Content-Type'], 'application/json')
        self.assertEqual(json.loads(body.decode('utf-8')), {'status': 'ok'})

    def test_health_behavior_is_preserved(self):
        os.environ[ENV_VAR] = 'abc123'
        response, body = self._get('/health')
        self.assertEqual(response.status, 200)
        self.assertIn('application/json', response.headers['Content-Type'])
        self.assertEqual(json.loads(body.decode('utf-8')),
                         {'status': 'ok', 'source_sha': 'abc123'})

    def test_healthz_behavior_is_preserved(self):
        os.environ[ENV_VAR] = 'abc123'
        response, body = self._get('/healthz')
        self.assertEqual(response.status, 200)
        self.assertIn('application/json', response.headers['Content-Type'])
        self.assertEqual(json.loads(body.decode('utf-8')),
                         {'status': 'ready', 'source_sha': 'abc123'})

    def test_healthz_query_string_behavior_is_preserved(self):
        os.environ[ENV_VAR] = 'abc123'
        response, body = self._get('/healthz?probe=1')
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(body.decode('utf-8')),
                         {'status': 'ready', 'source_sha': 'abc123'})


if __name__ == '__main__':
    unittest.main()
