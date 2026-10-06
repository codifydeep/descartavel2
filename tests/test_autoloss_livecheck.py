"""Acceptance tests for GET /livecheck, a liveness alias of /health."""
import json
import threading
import unittest
from http.server import HTTPServer
from urllib.request import urlopen

from app.server import Handler


class _ServerFixture(unittest.TestCase):
    """Run the real Handler on a local ephemeral HTTPServer per test."""

    def setUp(self):
        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base = 'http://%s:%s' % (host, port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def _get(self, path):
        response = urlopen(self.base + path)
        try:
            body = response.read()
            return response.status, response.headers.get('Content-Type'), body
        finally:
            response.close()


class LivecheckRouteTest(_ServerFixture):

    def test_livecheck_is_ok_json(self):
        status, content_type, body = self._get('/livecheck')
        self.assertEqual(200, status)
        self.assertEqual('application/json', content_type)
        self.assertEqual({'status': 'ok'}, json.loads(body.decode('utf-8')))

    def test_livecheck_ignores_query_string(self):
        status, content_type, body = self._get('/livecheck?probe=1')
        self.assertEqual(200, status)
        self.assertEqual('application/json', content_type)
        self.assertEqual({'status': 'ok'}, json.loads(body.decode('utf-8')))

    def test_health_still_reports_source_sha(self):
        status, content_type, body = self._get('/health')
        self.assertEqual(200, status)
        self.assertEqual('application/json', content_type)
        self.assertEqual('ok', json.loads(body.decode('utf-8'))['status'])

    def test_healthz_still_ready(self):
        status, content_type, body = self._get('/healthz')
        self.assertEqual(200, status)
        self.assertEqual('application/json', content_type)
        self.assertEqual('ready', json.loads(body.decode('utf-8'))['status'])


if __name__ == '__main__':
    unittest.main()
