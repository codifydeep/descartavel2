"""API tests for GET /feedback/latest (BRIEFLATEST-1 / C1).

Phase 1 tests only. They drive the real stdlib handler over loopback against the
sqlite3 file store, mirroring tests/test_feedback_count.py. They express the
latest contract: exact {"latest_id": N} body (highest positive matching ID or
null), filter parity with /feedback/count, strict status validation returning
the fixed 400 body, trimmed Unicode case-insensitive q matching, and read-only
behaviour.
"""
import json
import os
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

INVALID_LATEST = {'error': 'Invalid latest filter'}


class _QuietHandler(Handler):
    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class FeedbackLatestApiTests(unittest.TestCase):
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

    def latest(self, query=''):
        return self.call('GET', '/feedback/latest' + query)

    def seed(self, titles, completed=()):
        for title in titles:
            self.call('POST', '/feedback', {'title': title})
        for index, title in enumerate(titles):
            if title in completed:
                _, _, listing, _ = self.call('GET', '/feedback')
                item_id = listing['items'][index]['id']
                self.call('POST', '/feedback/%d/complete' % item_id)

    def listing_ids(self, query=''):
        _, _, listing, _ = self.call('GET', '/feedback' + query)
        return [item['id'] for item in listing['items']]

    # shape and content type
    def test_latest_returns_200_json_with_exact_body(self):
        self.seed(['Alpha'])
        status, ctype, body, raw = self.latest()
        self.assertEqual(status, 200)
        self.assertEqual(ctype, 'application/json')
        self.assertEqual(body, {'latest_id': self.listing_ids()[0]})
        self.assertEqual(raw, ('{"latest_id": %d}' % self.listing_ids()[0]).encode())

    def test_empty_store_returns_null(self):
        status, _, body, raw = self.latest()
        self.assertEqual(status, 200)
        self.assertEqual(body, {'latest_id': None})
        self.assertEqual(raw, b'{"latest_id": null}')

    def test_latest_is_highest_matching_id_not_first_listed(self):
        self.seed(['One', 'Two', 'Three'])
        highest = max(self.listing_ids())
        _, _, body, _ = self.latest()
        self.assertEqual(body, {'latest_id': highest})
        self.assertIsInstance(body['latest_id'], int)
        self.assertNotIsInstance(body['latest_id'], bool)

    # filter parity with /feedback/count and GET /feedback
    def test_missing_status_selects_all_items(self):
        self.seed(['One', 'Two', 'Three'], completed={'Three'})
        _, _, body, _ = self.latest()
        self.assertEqual(body, {'latest_id': max(self.listing_ids())})

    def test_status_open_selects_only_open_items(self):
        self.seed(['One', 'Two', 'Three'], completed={'Three'})
        open_ids = self.listing_ids('?status=open')
        _, _, body, _ = self.latest('?status=open')
        self.assertEqual(body, {'latest_id': max(open_ids)})

    def test_status_completed_selects_only_completed_items(self):
        self.seed(['One', 'Two', 'Three'], completed={'One'})
        completed_ids = self.listing_ids('?status=completed')
        _, _, body, _ = self.latest('?status=completed')
        self.assertEqual(body, {'latest_id': max(completed_ids)})

    def test_no_match_returns_null(self):
        self.seed(['Only open'])
        _, _, body, _ = self.latest('?status=completed')
        self.assertEqual(body, {'latest_id': None})

    def test_search_uses_trimmed_unicode_case_insensitive_title_match(self):
        self.seed(['Dark mode', 'dark Theme', 'Export'])
        expected = max(self.listing_ids('?q=DARK'))
        for query in ('?q=DARK', '?q=%20%20dark%20%20', '?q=dArK'):
            _, _, body, _ = self.latest(query)
            self.assertEqual(body, {'latest_id': expected}, query)

    def test_blank_q_matches_all(self):
        self.seed(['One', 'Two'])
        expected = max(self.listing_ids())
        for query in ('?q=', '?q=%20%20%20'):
            _, _, body, _ = self.latest(query)
            self.assertEqual(body, {'latest_id': expected}, query)

    def test_unrelated_parameters_are_ignored(self):
        self.seed(['One', 'Two'])
        expected = max(self.listing_ids())
        _, _, body, _ = self.latest('?foo=bar&sort=title')
        self.assertEqual(body, {'latest_id': expected})

    # strict status validation
    def test_explicit_empty_status_is_400(self):
        status, _, body, _ = self.latest('?status=')
        self.assertEqual(status, 400)
        self.assertEqual(body, INVALID_LATEST)

    def test_explicit_all_status_is_400(self):
        status, _, body, _ = self.latest('?status=all')
        self.assertEqual(status, 400)
        self.assertEqual(body, INVALID_LATEST)

    def test_unknown_status_is_400(self):
        status, _, body, raw = self.latest('?status=archived')
        self.assertEqual(status, 400)
        self.assertEqual(body, INVALID_LATEST)
        self.assertEqual(raw, b'{"error": "Invalid latest filter"}')

    def test_repeated_status_is_400(self):
        status, _, body, _ = self.latest('?status=open&status=open')
        self.assertEqual(status, 400)
        self.assertEqual(body, INVALID_LATEST)

    # read-only behaviour
    def test_latest_never_changes_items_counts_or_summary(self):
        self.seed(['One', 'Two'], completed={'Two'})
        _, _, before_list, _ = self.call('GET', '/feedback')
        _, _, before_count, _ = self.call('GET', '/feedback/count')
        _, _, before_summary, _ = self.call('GET', '/feedback/summary')
        self.latest()
        self.latest('?status=open')
        self.latest('?q=One')
        self.assertEqual(self.call('GET', '/feedback')[2], before_list)
        self.assertEqual(self.call('GET', '/feedback/count')[2], before_count)
        self.assertEqual(self.call('GET', '/feedback/summary')[2], before_summary)


if __name__ == '__main__':
    unittest.main()
