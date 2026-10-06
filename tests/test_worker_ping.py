"""Red/Green coverage for WORKERREC-1: ``GET /ping`` liveness alias.

These tests exercise the real :class:`app.server.Handler` over a local
ephemeral ``HTTPServer``. Nothing here touches the network, credentials or
external services; the server binds ``127.0.0.1`` on an OS-assigned port.
"""
import http.client
import json
import threading
import unittest
from http.server import HTTPServer

from app import server


class _ServerHarness(unittest.TestCase):
    """Boot the real handler once per test case on an ephemeral port."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def get(self, target):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            conn.request('GET', target)
            response = conn.getresponse()
            body = response.read()
            return response.status, response.getheader('Content-Type'), body
        finally:
            conn.close()


class PingAliasTests(_ServerHarness):
    def test_ping_is_liveness_alias(self):
        status, content_type, body = self.get('/ping')
        self.assertEqual(status, 200)
        self.assertEqual(content_type, 'application/json')
        self.assertEqual(json.loads(body.decode('utf-8')), {'status': 'ok'})

    def test_ping_query_string_does_not_change_route(self):
        status, content_type, body = self.get('/ping?probe=1')
        self.assertEqual(status, 200)
        self.assertEqual(content_type, 'application/json')
        self.assertEqual(json.loads(body.decode('utf-8')), {'status': 'ok'})

    def test_health_unchanged(self):
        status, content_type, body = self.get('/health')
        self.assertEqual(status, 200)
        self.assertEqual(content_type, 'application/json')
        payload = json.loads(body.decode('utf-8'))
        self.assertEqual(payload['status'], 'ok')

    def test_healthz_unchanged(self):
        status, content_type, body = self.get('/healthz')
        self.assertEqual(status, 200)
        self.assertEqual(content_type, 'application/json')
        payload = json.loads(body.decode('utf-8'))
        self.assertEqual(payload['status'], 'ready')


if __name__ == '__main__':
    unittest.main()
