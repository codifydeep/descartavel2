"""Test-first acceptance tests for FILTER-1 backend on ``GET /feedback`` (C1).

Phase 1 is tests only. The binding CTO contract for the status filter is
``{"parameter": "status", "absent": "all", "empty": "400", "explicit_all":
"400", "unknown": "400"}``: absent ``status`` keeps the legacy body byte for
byte; ``status=open`` and ``status=completed`` return only items in that state;
an empty, explicit ``all`` or unknown value (including repeated values and any
empty token) is a 400 JSON error and never a silent fallback. The UI's All tab
omits the parameter entirely. ``POST /feedback``, the completion route and
``GET /feedback/summary`` are untouched.

The frozen base lists every item for every ``GET /feedback`` request, so the
filter and 400 assertions below are Red before Phase 2 while the preservation
guards are green in both phases. As elsewhere in the suite the real stdlib
``http.server`` handler is driven over loopback against a temporary SQLite file
and the exact response bytes are inspected, mirroring the pinned discovery
command (``PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q``).
"""
import json
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

ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = ROOT / 'app' / 'static' / 'app.js'

from app.server import Handler  # noqa: E402


class _QuietHandler(Handler):
    """The real handler with request logging silenced for clean test output."""

    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class StatusFilterApiTests(unittest.TestCase):
    """``GET /feedback`` must honour the status filter exactly as contracted."""

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
        self.db_path = os.path.join(self._tmp.name, 'feedback.db')
        self._saved = os.environ.get('FEEDBACK_DB_PATH')
        os.environ['FEEDBACK_DB_PATH'] = self.db_path

    def tearDown(self):
        if self._saved is None:
            os.environ.pop('FEEDBACK_DB_PATH', None)
        else:
            os.environ['FEEDBACK_DB_PATH'] = self._saved
        self._tmp.cleanup()

    def call(self, method, path, payload=None):
        """Return ``(status, content_type, raw_bytes, parsed_body)``."""
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = Request('http://127.0.0.1:%d%s' % (self.port, path),
                          data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                status = response.status
                content_type = response.headers.get('Content-Type', '')
                raw = response.read()
        except HTTPError as error:
            status = error.code
            content_type = error.headers.get('Content-Type', '') if error.headers else ''
            raw = error.read()
        try:
            body = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            body = None
        return status, content_type, raw, body

    def create(self, title):
        status, _, _, body = self.call('POST', '/feedback', {'title': title})
        self.assertEqual(status, 201, 'fixture create must succeed')
        return body

    def complete(self, item_id):
        status, _, _, body = self.call('POST', '/feedback/%d/complete' % item_id)
        self.assertEqual(status, 200, 'fixture complete must succeed')
        return body

    def seed_mixed_board(self):
        """One completed item followed by two open items, in insertion order."""
        done = self.create('Done first')
        self.complete(done['id'])
        self.create('Open second')
        self.create('Open third')
        return done

    # absent parameter -- All -- byte-compatible with the legacy body
    def test_absent_status_returns_every_item_byte_for_byte(self):
        self.seed_mixed_board()
        status, content_type, raw, body = self.call('GET', '/feedback')
        self.assertEqual(status, 200)
        self.assertEqual(
            raw,
            json.dumps({'items': [
                {'id': 1, 'title': 'Done first', 'completed': True},
                {'id': 2, 'title': 'Open second', 'completed': False},
                {'id': 3, 'title': 'Open third', 'completed': False},
            ]}).encode('utf-8'),
            'GET /feedback without status must keep the legacy body byte for byte')
        self.assertEqual([item['title'] for item in body['items']],
                         ['Done first', 'Open second', 'Open third'])

    def test_absent_status_on_an_empty_board_is_the_legacy_empty_body(self):
        status, _, raw, body = self.call('GET', '/feedback')
        self.assertEqual(status, 200)
        self.assertEqual(raw, b'{"items": []}')
        self.assertEqual(body, {'items': []})

    def test_empty_board_filtered_by_open_or_completed_is_empty(self):
        for value in ('open', 'completed'):
            status, _, _, body = self.call('GET', '/feedback?status=%s' % value)
            self.assertEqual(status, 200,
                             'status=%s on an empty board must still answer 200' % value)
            self.assertEqual(body, {'items': []})

    # known values -- only items in that state, in insertion order
    def test_status_open_returns_only_open_items(self):
        self.seed_mixed_board()
        status, _, _, body = self.call('GET', '/feedback?status=open')
        self.assertEqual(status, 200)
        self.assertEqual([item['title'] for item in body['items']],
                         ['Open second', 'Open third'])
        self.assertTrue(all(item['completed'] is False for item in body['items']))

    def test_status_completed_returns_only_completed_items(self):
        self.seed_mixed_board()
        status, _, _, body = self.call('GET', '/feedback?status=completed')
        self.assertEqual(status, 200)
        self.assertEqual([item['title'] for item in body['items']], ['Done first'])
        self.assertTrue(all(item['completed'] is True for item in body['items']))

    def test_status_filters_reflect_completion_changes(self):
        item = self.create('Mutate me')
        self.create('Stay open')
        _, _, _, opened = self.call('GET', '/feedback?status=open')
        self.assertEqual([entry['title'] for entry in opened['items']],
                         ['Mutate me', 'Stay open'])
        self.complete(item['id'])
        _, _, _, completed = self.call('GET', '/feedback?status=completed')
        self.assertEqual([entry['title'] for entry in completed['items']], ['Mutate me'])
        _, _, _, still_open = self.call('GET', '/feedback?status=open')
        self.assertEqual([entry['title'] for entry in still_open['items']], ['Stay open'])

    def test_filtered_items_carry_the_full_item_shape(self):
        self.seed_mixed_board()
        _, _, _, body = self.call('GET', '/feedback?status=open')
        for item in body['items']:
            self.assertEqual(set(item.keys()), {'id', 'title', 'completed'})
            self.assertIsInstance(item['id'], int)
            self.assertNotIsInstance(item['id'], bool)
            self.assertIsInstance(item['title'], str)
            self.assertIsInstance(item['completed'], bool)

    # the parameter is the single key ``status``; other keys are inert
    def test_unrelated_query_parameters_are_ignored(self):
        self.seed_mixed_board()
        _, _, _, body = self.call('GET', '/feedback?page=2&sort=title')
        self.assertEqual([item['title'] for item in body['items']],
                         ['Done first', 'Open second', 'Open third'])
        _, _, _, filtered = self.call('GET', '/feedback?page=2&status=open')
        self.assertEqual([item['title'] for item in filtered['items']],
                         ['Open second', 'Open third'])

    # empty, explicit all, unknown and malformed values -- always 400 JSON
    def test_empty_status_value_is_400_json_error(self):
        self.seed_mixed_board()
        status, content_type, raw, body = self.call('GET', '/feedback?status=')
        self.assertEqual(status, 400, 'an empty status must never fall back silently')
        self.assertTrue(content_type.lower().startswith('application/json'),
                        'a 400 must be JSON, got %r' % content_type)
        self.assertIsInstance(body, dict)
        self.assertIn('error', body)
        self.assertIsInstance(body['error'], str)
        self.assertTrue(body['error'].strip())
        self.assertNotIn(b'items', raw)

    def test_explicit_all_status_value_is_400_json_error(self):
        self.seed_mixed_board()
        status, content_type, _, body = self.call('GET', '/feedback?status=all')
        self.assertEqual(status, 400,
                         "the UI's All tab omits status; an explicit all must be rejected")
        self.assertTrue(content_type.lower().startswith('application/json'))
        self.assertIn('error', body)

    def test_unknown_status_value_is_400_json_error(self):
        self.seed_mixed_board()
        for value in ('bogus', 'OPEN', 'Open', 'done', '1', 'null', 'true',
                      'open%20'):
            status, content_type, raw, body = self.call('GET', '/feedback?status=%s' % value)
            self.assertEqual(status, 400,
                             'status=%r must be rejected, never silently ignored' % value)
            self.assertTrue(content_type.lower().startswith('application/json'),
                            'status=%r must answer a JSON error' % value)
            self.assertIn('error', body)
            self.assertNotIn(b'items', raw)

    def test_repeated_or_empty_token_status_is_400(self):
        self.seed_mixed_board()
        for query in ('status=open&status=completed', 'status=open&status=',
                      'status=&status=open', 'status=open&status=all'):
            status, _, _, body = self.call('GET', '/feedback?%s' % query)
            self.assertEqual(status, 400,
                             'ambiguous/repeated status (%r) must be rejected' % query)
            self.assertIn('error', body)

    def test_rejected_status_never_leaks_the_board(self):
        self.seed_mixed_board()
        for query in ('status=', 'status=all', 'status=bogus', 'status=open&status=completed'):
            status, _, raw, _ = self.call('GET', '/feedback?%s' % query)
            self.assertEqual(status, 400)
            self.assertNotIn(b'Done first', raw)
            self.assertNotIn(b'Open second', raw)
            self.assertNotIn(b'Open third', raw)

    # existing routes are untouched by the filter
    def test_create_and_completion_keep_their_status_and_full_item(self):
        created = self.create('Keep me')
        self.assertEqual(set(created.keys()), {'id', 'title', 'completed'})
        self.assertIs(created['completed'], False)
        self.assertIsInstance(created['id'], int)
        unchanged = self.create('Second')
        status, _, _, completed_body = self.call(
            'POST', '/feedback/%d/complete' % created['id'])
        self.assertEqual(status, 200)
        self.assertEqual(completed_body, {'id': created['id'],
                                          'title': 'Keep me', 'completed': True})
        status, _, _, duplicate = self.call('POST', '/feedback', {'title': 'Second'})
        self.assertEqual(status, 409)
        self.assertIn('duplicate', duplicate['error'].lower())
        self.assertIsInstance(unchanged['id'], int)

    def test_summary_is_untouched_and_ignores_any_status_param(self):
        self.seed_mixed_board()
        base_status, base_type, base_raw, base = self.call('GET', '/feedback/summary')
        self.assertEqual(base_status, 200)
        self.assertEqual(base, {'total': 3, 'completed': 1, 'open': 2})
        for query in ('status=open', 'status=completed', 'status=all',
                      'status=bogus', 'status='):
            status, content_type, raw, body = self.call('GET', '/feedback/summary?%s' % query)
            self.assertEqual(status, base_status,
                             'summary must ignore %r' % query)
            self.assertEqual(raw, base_raw,
                             'summary must return identical bytes for %r' % query)
            self.assertEqual(body, base)
        status, _, _, _ = self.call('GET', '/feedback/summary')
        self.assertEqual(status, 200)
        self.assertEqual(base_type.lower().startswith('application/json'), True)


class ClientKeepsDraftAcrossFilterChangeTests(unittest.TestCase):
    """A filter change must be a board reload, never a form reset.

    A stdlib-only suite cannot execute JavaScript, so -- exactly as
    ``tests/test_feedback_summary_ui.py`` and ``tests/test_board_ui.py`` do --
    the served client is inspected over the real handler. The guard pins that
    the filter refresh path reloads the list without clearing, resetting or
    re-rendering the form, so a typed draft survives the switch. It is green in
    both phases: no filtering client exists yet.
    """

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

    def get_js(self):
        request = Request('http://127.0.0.1:%d/static/app.js' % self.port)
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return response.read().decode('utf-8', 'replace')

    def test_status_filter_marker_is_present_or_absent_without_a_reset(self):
        js = self.get_js()
        # The board is (re)loaded through the list loader, whose body must not
        # clear or reset the form -- an in-flight draft survives a filter switch.
        match = re.search(r'function\s+loadFeedback\s*\([^)]*\)\s*\{', js)
        self.assertIsNotNone(match, 'app.js must keep its loadFeedback() loader')
        start = match.end() - 1
        depth = 0
        body = js[start:]
        for index in range(start, len(js)):
            character = js[index]
            if character == '{':
                depth += 1
            elif character == '}':
                depth -= 1
                if depth == 0:
                    body = js[start:index + 1]
                    break
        self.assertNotIn('.reset(', body,
                         'loading the board must not reset the form')
        self.assertNotIn('form.reset', body,
                         'loading the board must not clear a typed draft')


if __name__ == '__main__':
    unittest.main()
