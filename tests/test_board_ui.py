"""Test-first acceptance tests for the C2 feedback board UI (stdlib only).

Phase 1 is tests only. These tests are authored against the C2 contract before
``GET /`` and the ``/static/*`` routes exist, so they fail Red against the
frozen C1 implementation. They drive the real stdlib ``http.server`` handler
over loopback and inspect the served assets, mirroring the pinned discovery
command (``python3 -m unittest discover -s . -q``). Once Phase 2 adds the board
page and its three assets, every assertion here turns Green without touching the
preserved C1 API tests.
"""
import http.client
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.server import Handler  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / 'app' / 'static'


class _QuietHandler(Handler):
    """The real handler with request logging silenced for clean test output."""

    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class _BoardServerCase(unittest.TestCase):
    """Shared loopback server plus helpers for HTTP and raw-path requests."""

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

    def raw_get(self, path):
        """Send a verbatim request target so encoded traversal is not rewritten."""
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            conn.request('GET', path)
            response = conn.getresponse()
            return (response.status, response.getheader('Content-Type', ''),
                    response.read())
        finally:
            conn.close()

    def assert_has_id(self, body, element_id):
        """The served markup must expose an element with this id attribute."""
        self.assertRegex(body, r'id=["\']%s["\']' % re.escape(element_id))


class BoardPageTests(_BoardServerCase):
    """``GET /`` must serve the shell the browser board is built from."""

    def test_root_serves_the_html_board(self):
        status, content_type, body = self.get('/')
        self.assertEqual(status, 200)
        self.assertTrue(content_type.lower().startswith('text/html'),
                        'GET / must be served as text/html, got %r' % content_type)
        self.assertIn('<html', body.lower())

    def test_root_page_declares_title_and_description_fields(self):
        status, _, body = self.get('/')
        self.assertEqual(status, 200)
        self.assertRegex(body, r'name=["\']title["\']')
        self.assertRegex(body, r'name=["\']description["\']')

    def test_root_page_exposes_the_form_list_and_status_regions(self):
        status, _, body = self.get('/')
        self.assertEqual(status, 200)
        self.assert_has_id(body, 'feedback-form')
        self.assert_has_id(body, 'feedback-list')
        self.assert_has_id(body, 'empty-state')

    def test_root_page_wires_up_the_named_assets(self):
        status, _, body = self.get('/')
        self.assertEqual(status, 200)
        self.assertIn('/static/app.js', body)
        self.assertIn('/static/style.css', body)


class StaticAssetTests(_BoardServerCase):
    """The three named assets must exist on disk and be served with types."""

    def test_named_assets_exist_on_disk(self):
        for name in ('index.html', 'app.js', 'style.css'):
            self.assertTrue((STATIC_DIR / name).is_file(),
                            'missing named static asset: app/static/%s' % name)

    def test_index_html_is_served_as_html(self):
        status, content_type, body = self.get('/static/index.html')
        self.assertEqual(status, 200)
        self.assertTrue(content_type.lower().startswith('text/html'),
                        'index.html must be text/html, got %r' % content_type)
        self.assertIn('<html', body.lower())

    def test_app_js_is_served_as_javascript(self):
        status, content_type, body = self.get('/static/app.js')
        self.assertEqual(status, 200)
        lowered = content_type.lower()
        self.assertTrue('javascript' in lowered or 'ecmascript' in lowered,
                        'app.js must be served as javascript, got %r' % content_type)
        self.assertTrue(body.strip())

    def test_style_css_is_served_as_css(self):
        status, content_type, body = self.get('/static/style.css')
        self.assertEqual(status, 200)
        self.assertTrue(content_type.lower().startswith('text/css'),
                        'style.css must be text/css, got %r' % content_type)
        self.assertTrue(body.strip())

    def test_unknown_static_asset_is_a_clean_404(self):
        status, _, _ = self.get('/static/does-not-exist.js')
        self.assertEqual(status, 404)


class StaticTraversalTests(_BoardServerCase):
    """Static routing must never escape ``app/static`` via traversal."""

    def test_legitimate_asset_is_served_so_routing_exists(self):
        status, _, _ = self.get('/static/app.js')
        self.assertEqual(status, 200)

    def test_relative_traversal_is_rejected(self):
        for attack in ('/static/../server.py',
                       '/static/../store.py',
                       '/static/../../AGENTS.md'):
            status, _, body = self.raw_get(attack)
            self.assertNotEqual(status, 200, 'traversal was served: %s' % attack)
            self.assertNotIn(b'class Handler', body)
            self.assertNotIn(b'def create_item', body)

    def test_encoded_traversal_is_rejected(self):
        for attack in ('/static/..%2fserver.py',
                       '/static/%2e%2e/server.py',
                       '/static/..%5cserver.py'):
            status, _, body = self.raw_get(attack)
            self.assertNotEqual(status, 200, 'traversal was served: %s' % attack)
            self.assertNotIn(b'class Handler', body)


class BoardClientBehaviourTests(_BoardServerCase):
    """The served script must implement the board's interactive contract.

    A stdlib-only suite cannot execute JavaScript, so the polling, toggle, empty
    state and human-readable error handling are asserted against the served
    ``app.js`` using the agreed markup ids and endpoints.
    """

    def app_js(self):
        status, _, body = self.get('/static/app.js')
        self.assertEqual(status, 200, 'app.js must be served for behaviour checks')
        return body

    def test_polls_the_board_about_every_two_seconds(self):
        js = self.app_js()
        self.assertIn('setInterval', js)
        delays = [int(n) for n in re.findall(r'\b(\d{3,5})\b', js)]
        self.assertTrue(any(1500 <= delay <= 2500 for delay in delays),
                        'expected a ~2000ms poll interval in app.js')

    def test_lists_feedback_from_the_api(self):
        js = self.app_js()
        self.assertIn('/feedback', js)

    def test_renders_items_into_the_list_container(self):
        js = self.app_js()
        self.assertIn('feedback-list', js)
        self.assertRegex(js, r'createElement|innerHTML|appendChild|textContent')

    def test_shows_an_empty_state_when_there_is_no_feedback(self):
        js = self.app_js()
        self.assertIn('empty-state', js)

    def test_toggles_completion_via_the_complete_endpoint(self):
        js = self.app_js()
        self.assertIn('/complete', js)
        self.assertRegex(js, r"method\s*:\s*['\"]POST['\"]")

    def test_surfaces_human_readable_errors(self):
        js = self.app_js()
        self.assertIn('form-status', js)
        self.assertIn('error', js.lower())

    def test_clears_the_form_after_a_successful_submission(self):
        js = self.app_js()
        cleared = (re.search(r'\.reset\s*\(', js)
                   or re.search(r"\.value\s*=\s*['\"]{2}", js))
        self.assertIsNotNone(cleared,
                             'app.js must clear the form after a successful submit')


if __name__ == '__main__':
    unittest.main()
