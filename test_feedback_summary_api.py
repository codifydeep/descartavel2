"""API tests for the feedback summary counts endpoint (SUMA-1).

Authored against the contract before ``GET /feedback/summary`` existed, so this
file is the failing-Red baseline that drives the implementation. The tests
exercise the real stdlib ``http.server`` handler over loopback against the
existing sqlite3 file store, mirroring the pinned unittest discovery command.

Contract: ``GET /feedback/summary`` returns exactly the JSON keys ``total``,
``completed`` and ``open``, each an integer, with ``open == total - completed``.
Counts reflect the existing persisted feedback items and change as items are
completed.
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


class _QuietHandler(Handler):
    """The real handler with request logging silenced for clean test output."""

    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class FeedbackSummaryApiTests(unittest.TestCase):
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
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = Request('http://127.0.0.1:%d%s' % (self.port, path),
                          data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
        try:
            body = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            body = None
        return status, body

    def summary(self):
        """Fetch ``/feedback/summary`` and return its decoded body."""
        status, body = self.call('GET', '/feedback/summary')
        self.assertEqual(status, 200)
        return body

    def assert_summary(self, body, total, completed, open_count):
        """Assert the exact summary shape and integer count values."""
        self.assertEqual(set(body.keys()), {'total', 'completed', 'open'})
        for key in ('total', 'completed', 'open'):
            self.assertIsInstance(body[key], int)
            self.assertNotIsInstance(body[key], bool)
        self.assertEqual(body, {'total': total, 'completed': completed, 'open': open_count})
        self.assertEqual(body['open'], body['total'] - body['completed'])

    # empty state
    def test_summary_is_all_zero_before_any_submission(self):
        self.assert_summary(self.summary(), 0, 0, 0)

    # created state
    def test_summary_counts_created_items_as_open(self):
        self.call('POST', '/feedback', {'title': 'First'})
        self.call('POST', '/feedback', {'title': 'Second'})
        self.assert_summary(self.summary(), 2, 0, 2)

    # completed state
    def test_summary_reflects_completion(self):
        _, first = self.call('POST', '/feedback', {'title': 'First'})
        self.call('POST', '/feedback', {'title': 'Second'})
        self.call('POST', '/feedback/%d/complete' % first['id'])
        self.assert_summary(self.summary(), 2, 1, 1)

    # counts track existing items and changes after completion
    def test_summary_tracks_counts_across_create_and_complete(self):
        _, a = self.call('POST', '/feedback', {'title': 'A'})
        _, b = self.call('POST', '/feedback', {'title': 'B'})
        _, c = self.call('POST', '/feedback', {'title': 'C'})
        self.assert_summary(self.summary(), 3, 0, 3)
        self.call('POST', '/feedback/%d/complete' % a['id'])
        self.assert_summary(self.summary(), 3, 1, 2)
        self.call('POST', '/feedback/%d/complete' % b['id'])
        self.call('POST', '/feedback/%d/complete' % c['id'])
        self.assert_summary(self.summary(), 3, 3, 0)

    # idempotent completion must not double count
    def test_summary_does_not_double_count_idempotent_completion(self):
        _, item = self.call('POST', '/feedback', {'title': 'Only once'})
        self.call('POST', '/feedback/%d/complete' % item['id'])
        self.call('POST', '/feedback/%d/complete' % item['id'])
        self.assert_summary(self.summary(), 1, 1, 0)

    # rejected submissions must not affect the counts
    def test_rejected_submissions_do_not_change_summary(self):
        self.call('POST', '/feedback', {'title': 'Kept'})
        self.call('POST', '/feedback', {'title': 'Kept'})            # duplicate
        self.call('POST', '/feedback', {'title': '   \t '})          # blank
        self.call('POST', '/feedback', {})                           # missing
        self.assert_summary(self.summary(), 1, 0, 1)

    # regression guard: the pre-existing feedback listing route still answers
    def test_feedback_listing_still_responds(self):
        self.call('POST', '/feedback', {'title': 'Kept'})
        status, body = self.call('GET', '/feedback')
        self.assertEqual(status, 200)
        self.assertEqual([item['title'] for item in body['items']], ['Kept'])


if __name__ == '__main__':
    unittest.main()
