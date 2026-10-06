"""C1: GET /service-mode returns exactly the demo payload.

Real ``app.server.Handler`` is served over a local ephemeral HTTPServer; the
production module is exercised unchanged, with no sleeps, skips or stubbing.
"""
import json
import threading
import unittest
from http.server import HTTPServer
from urllib.request import urlopen

from app.server import Handler

EXPECTED_STATUS = 200
EXPECTED_CTYPE = 'application/json; charset=utf-8'
EXPECTED_BODY = b'{"mode":"demo"}'


def accepts_demo(raw):
    """Strict allow-list decode: only own-key set {mode} == 'demo' passes."""
    try:
        value = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return False
    return isinstance(value, dict) and set(value) == {'mode'} and value['mode'] == 'demo'


class _ServerCase(unittest.TestCase):
    """Spin up a real Handler on an ephemeral port; no production edits."""

    def setUp(self):
        self._server = HTTPServer(('127.0.0.1', 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        self.addCleanup(self._stop)
        self.base = 'http://127.0.0.1:%d' % self._server.server_address[1]

    def _stop(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _get(self, path):
        response = urlopen(self.base + path, timeout=5)
        return response.status, response.headers['Content-Type'], response.read()


class ServiceModeEndpointTests(_ServerCase):

    def test_exact_object_success(self):
        status, ctype, body = self._get('/service-mode')
        self.assertEqual(status, EXPECTED_STATUS)
        self.assertEqual(ctype, EXPECTED_CTYPE)
        self.assertEqual(body, EXPECTED_BODY)
        decoded = json.loads(body.decode('utf-8'))
        self.assertEqual(set(decoded), {'mode'})
        self.assertEqual(decoded['mode'], 'demo')

    def test_probe_variant_byte_identical(self):
        base = self._get('/service-mode')
        probe = self._get('/service-mode?probe=1')
        self.assertEqual(probe, base)

    def test_negative_decoding_cases(self):
        # The literal body passes the strict allow-list.
        self.assertTrue(accepts_demo(EXPECTED_BODY))
        # Malformed JSON, empty body, extra-field payloads and another valid
        # mode must all fail; only exactly {"mode":"demo"} is demo.
        self.assertFalse(accepts_demo(b'{"mode":'))
        self.assertFalse(accepts_demo(b''))
        self.assertFalse(accepts_demo(b'{"mode":"demo","extra":1}'))
        self.assertFalse(accepts_demo(b'{"mode":"staging"}'))
        # The served body must equal the accepted literal.
        _, _, body = self._get('/service-mode')
        self.assertTrue(accepts_demo(body))
        self.assertEqual(body, EXPECTED_BODY)


if __name__ == '__main__':
    unittest.main()
