"""Test-first acceptance tests for ``GET /feedback/summary`` (SUMA-2).

Phase 1 is tests only. The approved contract requires ``GET /feedback/summary``
to answer HTTP 200 with the exact JSON object ``{"total": <int>,
"completed": <int>, "open": <int>}``: ``total`` counts every feedback item
already held by the existing SQLite store, ``completed`` counts the completed
ones, and ``open`` is the remaining work, always ``total - completed``. The
counts must track the store as items are created and completed.

The frozen base routes only ``/feedback`` exactly, so ``/feedback/summary``
falls through to the 404 branch of ``do_GET`` and every assertion below is Red
before Phase 2. They turn Green once ``app/server.py`` gains the summary route
over the existing ``app.store`` persistence, without disturbing any other route.

As elsewhere in the suite the real stdlib ``http.server`` handler is driven over
loopback against a temporary SQLite file and the status and JSON body are
inspected, mirroring the pinned discovery command
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


class _QuietHandler(Handler):
    """The real handler with request logging silenced for clean test output."""

    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class FeedbackSummaryApiTests(unittest.TestCase):
    """``GET /feedback/summary`` must report exact total/completed/open counts."""

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

    def create(self, title):
        """Create a feedback item through the API and return the stored item."""
        status, body = self.call('POST', '/feedback', {'title': title})
        self.assertEqual(status, 201, 'fixture create must succeed')
        return body

    def complete(self, item_id):
        status, body = self.call('POST', '/feedback/%d/complete' % item_id)
        self.assertEqual(status, 200, 'fixture complete must succeed')
        return body

    def summary(self):
        """Fetch the summary, asserting the contractual 200 before returning it."""
        status, body = self.call('GET', '/feedback/summary')
        self.assertEqual(status, 200,
                         'GET /feedback/summary must answer HTTP 200, got %r' % status)
        return body

    # empty state
    def test_summary_of_empty_store_is_all_zero(self):
        self.assertEqual(self.summary(), {'total': 0, 'completed': 0, 'open': 0})

    # created state
    def test_summary_counts_each_created_item_as_open(self):
        self.create('First')
        self.create('Second')
        self.assertEqual(self.summary(), {'total': 2, 'completed': 0, 'open': 2})

    # completed state
    def test_summary_counts_completed_items_separately_from_open(self):
        first = self.create('First')
        self.create('Second')
        self.create('Third')
        self.complete(first['id'])
        self.assertEqual(self.summary(), {'total': 3, 'completed': 1, 'open': 2})

    # the contract invariant, across every state
    def test_summary_open_is_always_total_minus_completed(self):
        empty = self.summary()
        self.assertEqual(empty['open'], empty['total'] - empty['completed'])
        first = self.create('First')
        self.create('Second')
        created = self.summary()
        self.assertEqual(created['open'], created['total'] - created['completed'])
        self.complete(first['id'])
        after = self.summary()
        self.assertEqual(after['open'], after['total'] - after['completed'])

    # exact JSON: only the three integer counts, no extras, no booleans/strings
    def test_summary_body_has_exactly_the_three_integer_counts(self):
        self.create('First')
        body = self.summary()
        self.assertEqual(set(body.keys()), {'total', 'completed', 'open'},
                         'summary must carry exactly total, completed and open')
        for key in ('total', 'completed', 'open'):
            value = body[key]
            self.assertIsInstance(value, int,
                                  '%s must be an integer, got %r' % (key, value))
            self.assertNotIsInstance(value, bool,
                                     '%s must be a count, not a boolean' % key)

    # existing SQLite persistence: rows already on disk are counted
    def test_summary_counts_items_already_persisted_in_sqlite(self):
        from app import store
        conn = store.connect(self.db_path)
        try:
            store.create_item(conn, 'Seeded open')
            seeded_done = store.create_item(conn, 'Seeded done')
            store.complete_item(conn, seeded_done['id'])
        finally:
            conn.close()
        self.assertEqual(self.summary(), {'total': 2, 'completed': 1, 'open': 1})

    # completion changes the counts, and re-completing does not double-count
    def test_summary_reflects_store_changes_over_time(self):
        self.assertEqual(self.summary(), {'total': 0, 'completed': 0, 'open': 0})
        item = self.create('Track me')
        self.assertEqual(self.summary(), {'total': 1, 'completed': 0, 'open': 1})
        self.complete(item['id'])
        self.assertEqual(self.summary(), {'total': 1, 'completed': 1, 'open': 0})
        self.complete(item['id'])
        self.assertEqual(self.summary(), {'total': 1, 'completed': 1, 'open': 0})

    # regression guard: the summary route leaves the existing routes intact
    def test_summary_preserves_existing_feedback_and_health_routes(self):
        self.create('Keep me')
        listing_status, listing = self.call('GET', '/feedback')
        self.assertEqual(listing_status, 200)
        self.assertEqual([item['title'] for item in listing['items']], ['Keep me'])
        health_status, health = self.call('GET', '/health')
        self.assertEqual(health_status, 200)
        self.assertEqual(health['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
