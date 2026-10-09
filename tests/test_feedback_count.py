"""API tests for GET /feedback/count (BRIEFCOUNT-2 / C1).

Phase 1 tests only. They drive the real stdlib handler over loopback against the
sqlite3 file store, mirroring tests/test_feedback_api.py. They express the
count contract: exact {"count": N} body, filter parity with GET /feedback,
strict status validation, trimmed Unicode case-insensitive q matching, and
read-only behaviour.
"""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.server import Handler  # noqa: E402

INVALID_COUNT = {'error': 'Invalid count filter'}


class _QuietHandler(Handler):
    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class FeedbackCountApiTests(unittest.TestCase):
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
                ctype = response.headers.get('Content-Type')
        except HTTPError as error:
            status, raw = error.code, error.read()
            ctype = error.headers.get('Content-Type')
        try:
            body = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            body = None
        return status, ctype, body, raw

    def count(self, query=''):
        return self.call('GET', '/feedback/count' + query)

    def seed(self, titles, completed=()):
        for title in titles:
            self.call('POST', '/feedback', {'title': title})
        for index, title in enumerate(titles):
            if title in completed:
                _, _, listing, _ = self.call('GET', '/feedback')
                item_id = listing['items'][index]['id']
                self.call('POST', '/feedback/%d/complete' % item_id)

    # shape and content type
    def test_count_returns_200_json_with_exact_body(self):
        self.seed(['Alpha'])
        status, ctype, body, raw = self.count()
        self.assertEqual(status, 200)
        self.assertEqual(ctype, 'application/json')
        self.assertEqual(body, {'count': 1})
        self.assertEqual(raw, b'{"count": 1}')

    def test_empty_store_counts_zero(self):
        status, _, body, _ = self.count()
        self.assertEqual(status, 200)
        self.assertEqual(body, {'count': 0})

    def test_count_is_nonnegative_integer_not_bool(self):
        status, _, body, _ = self.count()
        self.assertEqual(status, 200)
        self.assertIsInstance(body['count'], int)
        self.assertNotIsInstance(body['count'], bool)
        self.assertGreaterEqual(body['count'], 0)

    # filter parity with GET /feedback
    def test_missing_status_counts_all(self):
        self.seed(['One', 'Two', 'Three'], completed={'Two'})
        _, _, body, _ = self.count()
        self.assertEqual(body, {'count': 3})

    def test_status_open_counts_only_open(self):
        self.seed(['One', 'Two', 'Three'], completed={'Two'})
        _, _, body, _ = self.count('?status=open')
        self.assertEqual(body, {'count': 2})

    def test_status_completed_counts_only_completed(self):
        self.seed(['One', 'Two', 'Three'], completed={'Two'})
        _, _, body, _ = self.count('?status=completed')
        self.assertEqual(body, {'count': 1})

    def test_count_equals_list_length_for_same_filters(self):
        self.seed(['Dark mode', 'dark Theme', 'Export', 'Import'], completed={'Export'})
        for query in ('', '?status=open', '?status=completed',
                      '?q=dark', '?status=open&q=DARK', '?status=completed&q=zzz'):
            _, _, count_body, _ = self.count(query)
            _, _, listing, _ = self.call('GET', '/feedback' + query)
            self.assertEqual(count_body['count'], len(listing['items']), query)

    # strict status validation
    def test_explicit_empty_status_is_400(self):
        status, _, body, _ = self.count('?status=')
        self.assertEqual(status, 400)
        self.assertEqual(body, INVALID_COUNT)

    def test_explicit_all_status_is_400(self):
        status, _, body, _ = self.count('?status=all')
        self.assertEqual(status, 400)
        self.assertEqual(body, INVALID_COUNT)

    def test_unknown_status_is_400(self):
        status, _, body, _ = self.count('?status=bogus')
        self.assertEqual(status, 400)
        self.assertEqual(body, INVALID_COUNT)

    def test_repeated_status_is_400(self):
        status, _, body, _ = self.count('?status=open&status=completed')
        self.assertEqual(status, 400)
        self.assertEqual(body, INVALID_COUNT)

    def test_repeated_valid_status_is_400(self):
        status, _, body, _ = self.count('?status=open&status=open')
        self.assertEqual(status, 400)
        self.assertEqual(body, INVALID_COUNT)

    # q matching
    def test_q_matches_trimmed_title_case_insensitively(self):
        self.seed(['Dark Mode', 'light mode', 'Export'])
        _, _, body, _ = self.count('?q=%20%20DARK%20%20')
        self.assertEqual(body, {'count': 1})

    def test_q_matches_unicode_case_insensitively(self):
        self.seed(['Ärger mit Export', 'Other'])
        _, _, body, _ = self.count('?q=' + quote('ÄRGER'))
        self.assertEqual(body, {'count': 1})

    def test_blank_q_matches_all(self):
        self.seed(['One', 'Two'])
        _, _, body, _ = self.count('?q=%20%20%20')
        self.assertEqual(body, {'count': 2})

    def test_missing_q_matches_all(self):
        self.seed(['One', 'Two'])
        _, _, body, _ = self.count()
        self.assertEqual(body, {'count': 2})

    def test_other_parameters_are_ignored(self):
        self.seed(['One', 'Two'])
        _, _, body, _ = self.count('?sort=desc&page=9&foo=bar')
        self.assertEqual(body, {'count': 2})

    def test_q_and_status_combine(self):
        self.seed(['Dark A', 'Dark B', 'Light'], completed={'Dark A'})
        _, _, body, _ = self.count('?status=open&q=dark')
        self.assertEqual(body, {'count': 1})

    # read-only and unchanged surfaces
    def test_count_does_not_modify_items_or_summary(self):
        self.seed(['One', 'Two'], completed={'Two'})
        _, _, before_list, _ = self.call('GET', '/feedback')
        _, _, before_summary, _ = self.call('GET', '/feedback/summary')
        self.count('?status=open&q=one')
        self.count()
        _, _, after_list, _ = self.call('GET', '/feedback')
        _, _, after_summary, _ = self.call('GET', '/feedback/summary')
        self.assertEqual(before_list, after_list)
        self.assertEqual(before_summary, after_summary)

    def test_existing_feedback_list_shape_unchanged(self):
        self.seed(['One'])
        status, _, body, _ = self.call('GET', '/feedback')
        self.assertEqual(status, 200)
        self.assertEqual(list(body.keys()), ['items'])

    def test_unknown_feedback_id_still_404(self):
        status, _, body, _ = self.call('GET', '/feedback/999')
        self.assertEqual(status, 404)
        self.assertEqual(body, {'error': 'Feedback not found'})


if __name__ == '__main__':
    unittest.main()
