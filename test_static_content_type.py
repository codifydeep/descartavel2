"""Test-first regression for the failed *deployed* HTTP QA (QA198A2E86-1).

Phase 1 is tests only. The unchanged operator-owned HTTP QA contract requires
every served static asset to carry its registered media type; in particular
``GET /static/style.css`` must answer with a ``Content-Type`` beginning
``text/css``. ``tests/test_board_ui.py`` already pins that contract for a local
server, but the deployed feedback image stamps ``SOURCE_SHA`` into the
environment (``ARG``/``ENV`` in ``Dockerfile.feedback-bootstrap``) and
``app/server.py`` then silently downgrades the served stylesheet to
``text/plain`` for every deployment except one hard-coded revision. The contract
therefore holds locally but regresses in deployment -- exactly the failure the
deployed QA reported.

The Tech Lead diagnosis attached to this issue blamed the JavaScript media type.
That note is evidence, not truth: the frozen base already serves
``/static/app.js`` as ``application/javascript`` in both environments, so the
only observable deployed content-type fault is the stylesheet, and this file
pins that contract rather than the mis-diagnosed one.

Every assertion below is Red against the pinned base and turns Green once
``app/server.py`` serves the contractual type in deployment without disturbing
any other route. As elsewhere in the suite the tests drive the real stdlib
``http.server`` handler over loopback, mirroring the pinned discovery command
(``python3 -m unittest discover -s . -q``).
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


sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.server import Handler  # noqa: E402


# The media type the approved operator contract requires for served CSS.
CONTRACTUAL_CSS_MIME = 'text/css'
# The downgraded media type the deployed base actually sends for CSS.
WRONG_CSS_MIME = 'text/plain'
# The pinned revision the deployed QA ran against; the image stamps it as
# SOURCE_SHA, which is what triggers the downgrade in app/server.py.
PINNED_DEPLOYED_SHA = '1ffbd01ef03f7d859903e0a0ed0dc18926939c3e'
# An unrelated, valid revision: the contract must not depend on one blessed SHA.
OTHER_DEPLOYED_SHA = '0123456789abcdef0123456789abcdef01234567'


class _QuietHandler(Handler):
    """The real handler with request logging silenced for clean test output."""

    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class DeployedStaticContentTypeTests(unittest.TestCase):
    """Deployed ``GET /static/style.css`` must keep the contractual CSS type."""

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
        os.environ['SOURCE_SHA'] = PINNED_DEPLOYED_SHA

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

    def get_under_sha(self, path, sha):
        """Fetch ``path`` with ``SOURCE_SHA`` set to ``sha`` (``None`` unsets it)."""
        saved = os.environ.get('SOURCE_SHA')
        if sha is None:
            os.environ.pop('SOURCE_SHA', None)
        else:
            os.environ['SOURCE_SHA'] = sha
        try:
            return self.get(path)
        finally:
            if saved is None:
                os.environ.pop('SOURCE_SHA', None)
            else:
                os.environ['SOURCE_SHA'] = saved

    # the failed contract: deployment must not downgrade the served CSS media type
    def test_deployed_style_css_is_served_with_the_contractual_media_type(self):
        status, content_type, body = self.get('/static/style.css')
        self.assertEqual(status, 200)
        self.assertTrue(
            content_type.lower().startswith(CONTRACTUAL_CSS_MIME),
            'deployed GET /static/style.css must send Content-Type beginning %r, '
            'got %r' % (CONTRACTUAL_CSS_MIME, content_type))
        self.assertTrue(body.strip(), 'style.css must be served with a body')

    def test_deployed_style_css_is_not_downgraded_to_plain_text(self):
        _, content_type, _ = self.get('/static/style.css')
        media_type = content_type.split(';', 1)[0].strip().lower()
        self.assertNotEqual(
            media_type, WRONG_CSS_MIME,
            'deployed style.css must not be downgraded to %r' % WRONG_CSS_MIME)

    def test_deployed_css_media_type_does_not_depend_on_one_blessed_source_sha(self):
        for sha in (PINNED_DEPLOYED_SHA, OTHER_DEPLOYED_SHA):
            _, content_type, _ = self.get_under_sha('/static/style.css', sha)
            self.assertTrue(
                content_type.lower().startswith(CONTRACTUAL_CSS_MIME),
                'deployed GET /static/style.css under SOURCE_SHA=%s must stay %r, '
                'got %r' % (sha, CONTRACTUAL_CSS_MIME, content_type))

    # preserved behaviour: other routes are unaffected by the deployment stamp
    def test_deployed_other_assets_keep_their_media_types(self):
        html_status, html_type, _ = self.get('/static/index.html')
        self.assertEqual(html_status, 200)
        self.assertTrue(html_type.lower().startswith('text/html'),
                        'index.html must stay text/html, got %r' % html_type)
        js_status, js_type, js_body = self.get('/static/app.js')
        self.assertEqual(js_status, 200)
        self.assertTrue(js_type.lower().startswith('application/javascript'),
                        'app.js must stay application/javascript, got %r' % js_type)
        self.assertTrue(js_body.strip(), 'app.js must be served with a body')

    def test_deployed_health_still_reports_the_exact_source_sha(self):
        status, _, body = self.get('/health')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body),
                         {'status': 'ok', 'source_sha': PINNED_DEPLOYED_SHA})

    def test_undeployed_style_css_still_serves_the_contractual_media_type(self):
        _, content_type, _ = self.get_under_sha('/static/style.css', None)
        self.assertTrue(
            content_type.lower().startswith(CONTRACTUAL_CSS_MIME),
            'GET /static/style.css without SOURCE_SHA must stay %r, got %r'
            % (CONTRACTUAL_CSS_MIME, content_type))


if __name__ == '__main__':
    unittest.main()
