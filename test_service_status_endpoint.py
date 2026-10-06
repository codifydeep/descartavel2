import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer

from app.server import Handler


def _get(path):
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.daemon = True
    thread.start()
    try:
        conn = HTTPConnection(server.server_address[0], server.server_address[1])
        conn.request('GET', path)
        response = conn.getresponse()
        body = response.read()
        headers = dict(response.getheaders())
        return response.status, headers, body
    finally:
        conn.close()
        thread.join(5)
        server.server_close()


class ServiceStatusEndpointTest(unittest.TestCase):
    def test_returns_200_with_exact_json_body(self):
        status, headers, body = _get('/service-status')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"status":"available"}')
        self.assertEqual(len(body), 22)
        self.assertEqual(headers.get('Content-Type'), 'application/json; charset=utf-8')


if __name__ == '__main__':
    unittest.main()
