"""Test-first acceptance tests for the contractual static JavaScript MIME type.

Phase 1 is tests only. The approved HTTP contract requires ``GET /static/app.js``
to send a ``Content-Type`` beginning ``application/javascript``; the frozen base
answer is ``text/javascript``, so every assertion here is Red before Phase 2 and
turns Green once ``app/server.py`` is corrected. As in the rest of the suite a
stdlib-only test cannot execute JavaScript, so the real ``http.server`` handler
is driven over loopback and the response headers are inspected, mirroring the
pinned discovery command (``python3 -m unittest discover -s . -q``).
"""
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.server import Handler  # noqa: E402


# The exact media type the approved contract requires for served JavaScript.
CONTRACTUAL_JS_MIME = 'application/javascript'
LEGACY_JS_MIME = 'text/javascript'


class _QuietHandler(Handler):
    """The real handler with request logging silenced for clean test output."""

    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class StaticJavaScriptMimeTests(unittest.TestCase):
    """``GET /static/app.js`` must be served as ``application/javascript``."""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), _QuietHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = os.environ.get('FEEDBACK_DB_PATH')
        os.environ['FEEDBACK_DB_PATH'] = os.path.join(self._tmp.name, 'feedback.db')

    def tearDown(self):
        if self._saved is None:
            os.environ.pop('FEEDBACK_DB_PATH', None)
        else:
            os.environ['FEEDBACK_DB_PATH'] = self._saved
        self._tmp.cleanup()

    def get(self, path):
        """Fetch a path, returning ``(status, content_type, decoded_body)``."""
        request = Request('http://127.0.0.1:%d%s' % (self.port, path))
        try:
            with urlopen(request, timeout=5) as response:
                status = response.status
                content_type = response.headers.get('Content-Type', '')
                raw = response.read()
        except HTTPError as error:
            status = error.code
            content_type = error.headers.get('Content-Type', '') if error.headers else ''
            raw = error.read()
        return status, content_type, raw.decode('utf-8', 'replace')

    def test_static_app_js_content_type_starts_with_application_javascript(self):
        status, content_type, body = self.get('/static/app.js')
        self.assertEqual(status, 200)
        self.assertTrue(
            content_type.lower().startswith(CONTRACTUAL_JS_MIME),
            'GET /static/app.js must send Content-Type beginning %r, got %r'
            % (CONTRACTUAL_JS_MIME, content_type))
        self.assertTrue(body.strip(), 'app.js must be served with a body')

    def test_static_app_js_media_type_is_not_the_legacy_text_javascript(self):
        _, content_type, _ = self.get('/static/app.js')
        media_type = content_type.split(';', 1)[0].strip().lower()
        self.assertNotEqual(
            media_type, LEGACY_JS_MIME,
            'app.js must not use the legacy %r media type' % LEGACY_JS_MIME)


if __name__ == '__main__':
    unittest.main()
