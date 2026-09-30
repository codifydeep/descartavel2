"""Test-first regression for the failed *deployed* HTTP QA (QA7FA75247-1).

Phase 1 is tests only. The unchanged operator-owned HTTP QA contract -- the same
one asserted by ``tests/test_static_mime.py`` -- requires ``GET /static/app.js``
to send a ``Content-Type`` beginning ``application/javascript`` and never the
legacy ``text/javascript``. The frozen base satisfies that contract only while
``SOURCE_SHA`` is unset; the deployed feedback image sets ``SOURCE_SHA`` (an
``ARG``/``ENV`` in ``Dockerfile.feedback-bootstrap``), and ``app/server.py``
then downgrades the served JavaScript to the legacy media type. The contract
therefore holds locally but regresses in deployment, which is exactly the
failure the deployed QA reported.

These tests reproduce the deployed environment by exporting ``SOURCE_SHA``
exactly as the image does, then assert the contractual media type through the
real stdlib ``http.server`` handler over loopback, mirroring the pinned
discovery command (``python3 -m unittest discover -s . -q``). Every assertion
here is Red against the pinned base and turns Green once ``app/server.py``
serves the contractual type in deployment without disturbing any other route.
"""
import json
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


# The exact media type the approved operator contract requires for served JS.
CONTRACTUAL_JS_MIME = 'application/javascript'
# The legacy media type the contract forbids for served JS.
LEGACY_JS_MIME = 'text/javascript'
# The pinned base SHA; the deployed image stamps it into the environment.
DEPLOYED_SOURCE_SHA = '32c053a20e43b99be077db7a9d1a36cf771c4891'


class _QuietHandler(Handler):
    """The real handler with request logging silenced for clean test output."""

    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class DeployedStaticMimeRegressionTests(unittest.TestCase):
    """The deployed server sets ``SOURCE_SHA``; the JS MIME contract must hold."""

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
        self._saved_db = os.environ.get('FEEDBACK_DB_PATH')
        os.environ['FEEDBACK_DB_PATH'] = os.path.join(self._tmp.name, 'feedback.db')
        # Reproduce the deployed image: SOURCE_SHA is present in the environment.
        self._saved_sha = os.environ.get('SOURCE_SHA')
        os.environ['SOURCE_SHA'] = DEPLOYED_SOURCE_SHA

    def tearDown(self):
        if self._saved_db is None:
            os.environ.pop('FEEDBACK_DB_PATH', None)
        else:
            os.environ['FEEDBACK_DB_PATH'] = self._saved_db
        if self._saved_sha is None:
            os.environ.pop('SOURCE_SHA', None)
        else:
            os.environ['SOURCE_SHA'] = self._saved_sha
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

    # the failed contract: deployment must not downgrade the served JS media type
    def test_deployed_app_js_keeps_the_contractual_media_type(self):
        status, content_type, body = self.get('/static/app.js')
        self.assertEqual(status, 200)
        self.assertTrue(
            content_type.lower().startswith(CONTRACTUAL_JS_MIME),
            'deployed GET /static/app.js must send Content-Type beginning %r, '
            'got %r' % (CONTRACTUAL_JS_MIME, content_type))
        self.assertTrue(body.strip(), 'app.js must be served with a body')

    def test_deployed_app_js_is_not_the_legacy_text_javascript(self):
        _, content_type, _ = self.get('/static/app.js')
        media_type = content_type.split(';', 1)[0].strip().lower()
        self.assertNotEqual(
            media_type, LEGACY_JS_MIME,
            'deployed app.js must not use the legacy %r media type' % LEGACY_JS_MIME)

    # preserved behaviour: other routes are unaffected by the deployment stamp
    def test_deployed_other_assets_keep_their_media_types(self):
        html_status, html_type, _ = self.get('/static/index.html')
        self.assertEqual(html_status, 200)
        self.assertTrue(html_type.lower().startswith('text/html'),
                        'index.html must stay text/html, got %r' % html_type)
        css_status, css_type, _ = self.get('/static/style.css')
        self.assertEqual(css_status, 200)
        self.assertTrue(css_type.lower().startswith('text/css'),
                        'style.css must stay text/css, got %r' % css_type)

    def test_deployed_health_still_reports_the_exact_source_sha(self):
        status, _, body = self.get('/health')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'status': 'ok',
                                            'source_sha': DEPLOYED_SOURCE_SHA})


if __name__ == '__main__':
    unittest.main()
