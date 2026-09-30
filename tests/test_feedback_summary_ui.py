"""Test-first acceptance tests for the SUMB-2 summary region (stdlib only).

Phase 1 is tests only. The approved SUMB-2 contract adds an accessible feedback
summary region to the existing board: the served page must expose a live region
that labels the total, open and completed counts, and the served client must
fetch those counts from ``GET /feedback/summary`` and refresh the region after
the initial load, after a submission, after a completion and on every poll tick.

The frozen base merges SUMA-2 (``GET /feedback/summary`` already answers) but
``app/static/index.html`` has no summary region and ``app/static/app.js`` never
requests ``/feedback/summary``, so every assertion about the new markup and the
new client wiring below is Red before Phase 2. They turn Green once the two
static assets gain the summary region and refresh paths, without disturbing the
existing form, list, empty state, error handling, polling or their tests. The
preservation guards and the endpoint-integration guard in this file are green in
both phases; they exist to prove the addition leaves the merged board intact.

A stdlib-only suite cannot execute JavaScript, so -- exactly as
``tests/test_board_ui.py`` does -- the served assets are inspected through the
real ``http.server`` handler over loopback and the agreed ids, labels and
endpoint are pinned by text, mirroring the pinned discovery command
(``python3 -m unittest discover -s . -q``).
"""
import os
import re
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.server import Handler  # noqa: E402


# --- pinned SUMB-2 contract -------------------------------------------------

# The accessible region that wraps the counts.
SUMMARY_ID = 'feedback-summary'
# The three labelled count elements the region must expose.
TOTAL_ID = 'summary-total'
OPEN_ID = 'summary-open'
COMPLETED_ID = 'summary-completed'
SUMMARY_COUNT_IDS = (TOTAL_ID, OPEN_ID, COMPLETED_ID)
# The human-readable labels for those counts.
SUMMARY_LABELS = ('Total', 'Open', 'Completed')
# The endpoint the client must read the counts from.
SUMMARY_ENDPOINT = '/feedback/summary'
# The named refresh routine the four refresh paths must call.
REFRESH_FUNCTION = 'loadSummary'


def _function_body(source, name):
    """Return the body of ``function name(...) { ... }``, or ``None``.

    Brace matching keeps the check inside one function so a call in a sibling
    handler cannot satisfy it. ``None`` means the function is absent (Red).
    """
    match = re.search(r'function\s+%s\s*\([^)]*\)\s*\{' % re.escape(name), source)
    if not match:
        return None
    start = match.end() - 1  # index of the opening brace
    depth = 0
    for index in range(start, len(source)):
        character = source[index]
        if character == '{':
            depth += 1
        elif character == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    return source[start:]


def _callback_body(source, call):
    """Return the body of the first ``call(...) { ... }`` callback, or ``None``."""
    index = source.find(call)
    if index < 0:
        return None
    brace = source.find('{', index)
    if brace < 0:
        return None
    depth = 0
    for position in range(brace, len(source)):
        character = source[position]
        if character == '{':
            depth += 1
        elif character == '}':
            depth -= 1
            if depth == 0:
                return source[brace:position + 1]
    return source[brace:]


class _QuietHandler(Handler):
    """The real handler with request logging silenced for clean test output."""

    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class _SummaryServerCase(unittest.TestCase):
    """Shared loopback server plus helpers for the served HTML and script."""

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

    def index_html(self):
        """Return the served board markup from ``GET /``, asserting a 200."""
        status, _, body = self.get('/')
        self.assertEqual(status, 200, 'GET / must serve the board')
        return body

    def app_js(self):
        """Return the served client from ``GET /static/app.js``, asserting a 200."""
        status, _, body = self.get('/static/app.js')
        self.assertEqual(status, 200, 'app.js must be served for behaviour checks')
        return body

    def assert_has_id(self, body, element_id):
        """The served markup must expose an element with this id attribute."""
        self.assertRegex(body, r'id=["\']%s["\']' % re.escape(element_id))

    def element_tag(self, body, element_id):
        """Return the whitespace-normalized opening tag carrying ``element_id``."""
        match = re.search(
            r'<[a-zA-Z][^>]*\bid=["\']%s["\'][^>]*>' % re.escape(element_id), body)
        return match.group(0) if match else None


class SummaryMarkupTests(_SummaryServerCase):
    """``GET /`` must serve an accessible region for the feedback counts."""

    def test_root_page_exposes_the_summary_region(self):
        body = self.index_html()
        self.assert_has_id(body, SUMMARY_ID)

    def test_static_index_html_exposes_the_summary_region(self):
        status, content_type, body = self.get('/static/index.html')
        self.assertEqual(status, 200)
        self.assertTrue(content_type.lower().startswith('text/html'),
                        'index.html must be served as text/html, got %r' % content_type)
        self.assert_has_id(body, SUMMARY_ID)

    def test_summary_region_exposes_total_open_and_completed_counts(self):
        body = self.index_html()
        for element_id in SUMMARY_COUNT_IDS:
            self.assert_has_id(body, element_id)

    def test_summary_region_is_a_labelled_live_region(self):
        body = self.index_html()
        tag = self.element_tag(body, SUMMARY_ID)
        self.assertIsNotNone(tag, 'summary region element must be present')
        self.assertRegex(tag, r'role=["\']status["\']',
                         'the summary region must be an ARIA live region')
        self.assertRegex(tag, r'aria-labelledby=["\'][^"\']+["\']|aria-label=["\'][^"\']+["\']',
                         'the summary region must have an accessible name')

    def test_summary_region_labels_its_counts(self):
        body = self.index_html()
        for label in SUMMARY_LABELS:
            self.assertRegex(body, r'>\s*%s\s*<' % re.escape(label),
                             'the summary region must label the %r count' % label)


class SummaryClientWiringTests(_SummaryServerCase):
    """The served client must read the counts from ``/feedback/summary``."""

    def test_app_js_requests_the_summary_endpoint(self):
        self.assertIn(SUMMARY_ENDPOINT, self.app_js(),
                      'app.js must request %s' % SUMMARY_ENDPOINT)

    def test_app_js_fetches_the_summary_endpoint(self):
        js = self.app_js()
        self.assertRegex(
            js, r'fetch\s*\(\s*["\']%s["\']' % re.escape(SUMMARY_ENDPOINT),
            'app.js must fetch %s for the summary counts' % SUMMARY_ENDPOINT)

    def test_app_js_defines_the_summary_refresh_routine(self):
        js = self.app_js()
        self.assertRegex(js, r'function\s+%s\s*\(' % re.escape(REFRESH_FUNCTION),
                         'app.js must define %s()' % REFRESH_FUNCTION)

    def test_refresh_routine_updates_every_count_element(self):
        js = self.app_js()
        body = _function_body(js, REFRESH_FUNCTION)
        self.assertIsNotNone(body, '%s() must be defined' % REFRESH_FUNCTION)
        self.assertIn(SUMMARY_ENDPOINT, body,
                      '%s() must read %s' % (REFRESH_FUNCTION, SUMMARY_ENDPOINT))
        for element_id in SUMMARY_COUNT_IDS:
            self.assertIn(element_id, body,
                          '%s() must write the %s count' % (REFRESH_FUNCTION, element_id))
        self.assertRegex(body, r'textContent|innerText|innerHTML|nodeValue',
                         '%s() must render the fetched counts' % REFRESH_FUNCTION)


class SummaryRefreshPathTests(_SummaryServerCase):
    """The region must refresh after load, submit, completion and polling."""

    def test_summary_is_refreshed_on_the_initial_load(self):
        js = self.app_js()
        self.assertRegex(
            js, r'^%s\s*\(' % re.escape(REFRESH_FUNCTION),
            'app.js must call %s() at top level for the initial load' % REFRESH_FUNCTION)

    def test_summary_is_refreshed_after_a_submission(self):
        js = self.app_js()
        body = _function_body(js, 'submitFeedback')
        self.assertIsNotNone(body, 'submitFeedback() must remain in app.js')
        self.assertIn(REFRESH_FUNCTION, body,
                      'submitFeedback() must refresh the summary after submitting')

    def test_summary_is_refreshed_after_a_completion(self):
        js = self.app_js()
        body = _function_body(js, 'completeItem')
        self.assertIsNotNone(body, 'completeItem() must remain in app.js')
        self.assertIn(REFRESH_FUNCTION, body,
                      'completeItem() must refresh the summary after completing')

    def test_summary_is_refreshed_on_every_poll_tick(self):
        js = self.app_js()
        self.assertIn('setInterval', js, 'app.js must keep polling')
        body = _callback_body(js, 'setInterval')
        self.assertIsNotNone(body, 'the poll timer callback must be inspectable')
        self.assertIn(REFRESH_FUNCTION, body,
                      'the poll callback must refresh the summary each tick')


class PreservedBoardContractTests(_SummaryServerCase):
    """The existing board behaviour must survive the summary addition."""

    def test_existing_form_list_empty_state_and_status_are_preserved(self):
        body = self.index_html()
        for element_id in ('feedback-form', 'feedback-list', 'empty-state',
                           'form-status'):
            self.assert_has_id(body, element_id)

    def test_existing_named_assets_are_still_wired(self):
        body = self.index_html()
        self.assertIn('/static/app.js', body)
        self.assertIn('/static/style.css', body)

    def test_existing_client_endpoints_and_status_are_preserved(self):
        js = self.app_js()
        for fragment in ('/feedback', '/complete', 'form-status', 'setInterval'):
            self.assertIn(fragment, js,
                          'app.js must keep the existing %r wiring' % fragment)


class SummaryEndpointIntegrationTests(_SummaryServerCase):
    """The endpoint the client wiring reads must really be served by the board."""

    def test_summary_endpoint_backs_the_client_wiring(self):
        status, content_type, body = self.get(SUMMARY_ENDPOINT)
        self.assertEqual(status, 200,
                         'GET %s must be served for the summary region'
                         % SUMMARY_ENDPOINT)
        self.assertTrue(content_type.lower().startswith('application/json'),
                        'GET %s must be JSON, got %r' % (SUMMARY_ENDPOINT, content_type))
        for key in ('total', 'open', 'completed'):
            self.assertIn('"%s"' % key, body,
                          'GET %s must expose %r' % (SUMMARY_ENDPOINT, key))


if __name__ == '__main__':
    unittest.main()
