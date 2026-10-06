"""Acceptance tests for LINESRC-2: `/pulse` liveness alias of ``/health``.

These tests exercise the real ``app.server.Handler`` over a local ephemeral
``HTTPServer`` so the HTTP status, headers and body are observed exactly as a
client would see them.

Covered criteria:
* ``GET /pulse`` -> 200, ``application/json``, exact ``{"status": "ok"}``.
* ``GET /pulse?probe=1`` -> same route, query string does not change it.
* Pre-existing ``/health`` and ``/healthz`` behaviour is unchanged.
"""
import http.client
import threading
import unittest
from http.server import HTTPServer

from app.server import Handler


class _Server:
    """Ephemeral local HTTP server bound to ``127.0.0.1:0``."""

    def __init__(self):
        self.httpd = HTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever)
        self.thread.daemon = True

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    @property
    def port(self):
        return self.httpd.server_address[1]

    def get(self, path):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            conn.request('GET', path)
            response = conn.getresponse()
            return response.status, response.getheader('Content-Type'), response.read()
        finally:
            conn.close()


class PulseAliasTest(unittest.TestCase):
    def test_pulse_returns_ok_json(self):
        with _Server() as server:
            status, content_type, body = server.get('/pulse')
        self.assertEqual(200, status)
        self.assertEqual('application/json', content_type)
        self.assertEqual(b'{"status": "ok"}', body)

    def test_pulse_query_string_is_ignored(self):
        with _Server() as server:
            status, content_type, body = server.get('/pulse?probe=1')
        self.assertEqual(200, status)
        self.assertEqual('application/json', content_type)
        self.assertEqual(b'{"status": "ok"}', body)

    def test_health_still_returns_source_sha(self):
        with _Server() as server:
            status, content_type, body = server.get('/health')
        self.assertEqual(200, status)
        self.assertEqual('application/json', content_type)
        self.assertIn(b'"status": "ok"', body)
        self.assertIn(b'"source_sha"', body)

    def test_healthz_still_returns_ready(self):
        with _Server() as server:
            status, content_type, body = server.get('/healthz')
        self.assertEqual(200, status)
        self.assertEqual('application/json', content_type)
        self.assertIn(b'"status": "ready"', body)


if __name__ == '__main__':
    unittest.main()
