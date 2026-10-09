"""Test-first acceptance tests for the BRIEFCOUNT-2 matching-count UI (C2).

Phase 1 is tests only. The approved contract adds a status element
``#feedback-match-count`` (role=status, aria-live=polite) to the board, and a
client that refreshes it from ``GET /feedback/count`` with the active status
and search (never sort), riding the existing poll. Superseded responses are
ignored and text is rendered via textContent only. None of this exists in the
frozen base, so the markup/wiring assertions are Red before Phase 2.

Like ``tests/test_feedback_summary_ui.py``, a stdlib-only suite cannot execute
JavaScript; the served assets are fetched through the real ``http.server``
handler over loopback and the contract is pinned by text.
"""
import re
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.request import urlopen


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.server import Handler  # noqa: E402


COUNT_ID = 'feedback-match-count'
COUNT_ENDPOINT = '/feedback/count'
COUNT_PREFIX = 'Matching: '
COUNT_UNAVAILABLE = 'Matching unavailable'
POLL_MS = 2000


def _function_body(source, name):
    """Return the body of ``function name(...) { ... }``, or ``None``."""
    match = re.search(r'function\s+%s\s*\([^)]*\)\s*\{' % re.escape(name), source)
    if not match:
        return None
    start = match.end() - 1
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


class _QuietHandler(Handler):
    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class FeedbackCountUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), _QuietHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.markup = cls._fetch('/')
        cls.script = cls._fetch('/static/app.js')

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    @classmethod
    def _fetch(cls, path):
        with urlopen('http://127.0.0.1:%d%s' % (cls.port, path), timeout=5) as response:
            return response.read().decode('utf-8')

    def test_count_status_element_is_declared_in_markup(self):
        element = re.search(r'<[^>]*id="%s"[^>]*>' % COUNT_ID, self.markup)
        self.assertIsNotNone(element)
        self.assertIn('role="status"', element.group(0))
        self.assertIn('aria-live="polite"', element.group(0))

    def test_count_element_ships_initial_matching_text(self):
        self.assertRegex(self.markup, r'id="%s"[^>]*>\s*Matching: ' % COUNT_ID)

    def test_client_requests_count_endpoint(self):
        self.assertIn(COUNT_ENDPOINT, self.script)

    def test_client_refresh_is_wired_to_existing_poll_without_new_timer(self):
        poll = re.search(r'setInterval\(function\s*\(\)\s*\{(.*?)\},\s*POLL_MS\)',
                         self.script, re.S)
        self.assertIsNotNone(poll)
        self.assertIn('loadMatchCount', poll.group(1))
        self.assertEqual(len(re.findall(r'setInterval\s*\(', self.script)), 1)
        self.assertEqual(len(re.findall(r'setTimeout\s*\(', self.script)), 1)

    def test_count_refresh_is_called_from_status_and_search_paths(self):
        self.assertIn('loadMatchCount', self.script)
        applied = _function_body(self.script, 'applyFilter')
        self.assertIsNotNone(applied)
        self.assertIn('loadMatchCount', applied)
        search = self.script[self.script.find('SEARCH_DEBOUNCE_MS);'):]
        self.assertIn('loadMatchCount', search)

    def test_sort_path_does_not_refresh_count(self):
        applied = _function_body(self.script, 'applySort')
        self.assertIsNotNone(applied)
        self.assertNotIn('loadMatchCount', applied)

    def test_count_text_is_rendered_with_textcontent_only(self):
        body = _function_body(self.script, 'loadMatchCount')
        self.assertIsNotNone(body)
        self.assertIn('textContent', body)
        self.assertNotIn('innerHTML', body)

    def test_count_refresh_never_writes_or_disables_the_form(self):
        body = _function_body(self.script, 'loadMatchCount')
        self.assertIsNotNone(body)
        self.assertNotIn("method: 'POST'", body)
        self.assertNotIn('disabled', body)
        self.assertNotIn('setSubmitting', body)

    def test_count_response_is_sequenced_so_superseded_responses_are_ignored(self):
        body = _function_body(self.script, 'loadMatchCount')
        self.assertIsNotNone(body)
        self.assertIn('Generation', body)


if __name__ == '__main__':
    unittest.main()
