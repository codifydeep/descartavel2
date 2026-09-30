"""API tests for the disposable feedback board (C1).

Authored against the contract before app/db.py and the feedback routes existed,
so this file is the failing-Red baseline that drives the implementation. The
tests exercise the real stdlib http.server handler over loopback plus the
sqlite3 file store, mirroring the pinned unittest discovery command.
"""
import json
import os
from pathlib import Path
import sqlite3
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


class FeedbackApiTests(unittest.TestCase):
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

    # create
    def test_create_returns_json_item(self):
        status, body = self.call('POST', '/feedback', {'title': 'Add dark mode'})
        self.assertEqual(status, 201)
        self.assertEqual(body['title'], 'Add dark mode')
        self.assertIs(body['completed'], False)
        self.assertIsInstance(body['id'], int)

    def test_list_returns_created_items_in_order(self):
        self.call('POST', '/feedback', {'title': 'First'})
        self.call('POST', '/feedback', {'title': 'Second'})
        status, body = self.call('GET', '/feedback')
        self.assertEqual(status, 200)
        self.assertEqual([item['title'] for item in body['items']], ['First', 'Second'])

    def test_list_is_empty_before_any_submission(self):
        status, body = self.call('GET', '/feedback')
        self.assertEqual(status, 200)
        self.assertEqual(body['items'], [])

    # complete
    def test_complete_marks_item_completed(self):
        _, created = self.call('POST', '/feedback', {'title': 'Ship it'})
        status, body = self.call('POST', '/feedback/%d/complete' % created['id'])
        self.assertEqual(status, 200)
        self.assertEqual(body['id'], created['id'])
        self.assertIs(body['completed'], True)

    def test_complete_twice_is_idempotent(self):
        _, created = self.call('POST', '/feedback', {'title': 'Ship it'})
        first_status, first = self.call('POST', '/feedback/%d/complete' % created['id'])
        second_status, second = self.call('POST', '/feedback/%d/complete' % created['id'])
        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual(first, second)
        self.assertIs(second['completed'], True)

    def test_complete_unknown_item_is_404(self):
        status, _ = self.call('POST', '/feedback/999/complete')
        self.assertEqual(status, 404)

    # rejection
    def test_whitespace_title_rejected_and_stored_nowhere(self):
        status, body = self.call('POST', '/feedback', {'title': '   \t\n '})
        self.assertEqual(status, 400)
        self.assertIn('title', body['error'].lower())
        _, listing = self.call('GET', '/feedback')
        self.assertEqual(listing['items'], [])

    def test_missing_title_rejected_and_stored_nowhere(self):
        status, body = self.call('POST', '/feedback', {})
        self.assertEqual(status, 400)
        self.assertIn('title', body['error'].lower())
        _, listing = self.call('GET', '/feedback')
        self.assertEqual(listing['items'], [])

    def test_duplicate_submission_rejected_and_stored_nowhere(self):
        self.call('POST', '/feedback', {'title': 'Add dark mode'})
        status, body = self.call('POST', '/feedback', {'title': 'Add dark mode'})
        self.assertEqual(status, 409)
        self.assertIn('duplicate', body['error'].lower())
        _, listing = self.call('GET', '/feedback')
        self.assertEqual([item['title'] for item in listing['items']], ['Add dark mode'])

    def test_duplicate_detected_across_surrounding_whitespace(self):
        self.call('POST', '/feedback', {'title': 'Add dark mode'})
        status, body = self.call('POST', '/feedback', {'title': '  Add dark mode  '})
        self.assertEqual(status, 409)
        self.assertIn('duplicate', body['error'].lower())

    # sqlite3 file persistence
    def test_feedback_persists_to_sqlite3_file(self):
        self.call('POST', '/feedback', {'title': 'Persist me'})
        self.assertTrue(os.path.exists(self.db_path))
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute('SELECT title, completed FROM feedback').fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [('Persist me', 0)])

    def test_persisted_items_survive_process_reopen(self):
        self.call('POST', '/feedback', {'title': 'Persist me'})
        from app import db as db_module
        conn = db_module.connect(self.db_path)
        try:
            self.assertEqual([item['title'] for item in db_module.list_items(conn)],
                             ['Persist me'])
        finally:
            conn.close()

    # parameterized queries hold up against SQL metacharacters
    def test_sql_metacharacters_are_stored_literally(self):
        title = "'); DROP TABLE feedback; --"
        status, _ = self.call('POST', '/feedback', {'title': title})
        self.assertEqual(status, 201)
        _, listing = self.call('GET', '/feedback')
        self.assertEqual([item['title'] for item in listing['items']], [title])

    # regression guard: the bootstrap /health route still answers
    def test_health_endpoint_still_responds(self):
        status, body = self.call('GET', '/health')
        self.assertEqual(status, 200)
        self.assertEqual(body['status'], 'ok')


class FeedbackStoreModuleTests(unittest.TestCase):
    """The contract declares the persistence layer at app/store.py."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, 'store.db')

    def tearDown(self):
        self._tmp.cleanup()

    def test_declared_store_module_exposes_persistence_api(self):
        from app import store
        for name in ('connect', 'create_item', 'list_items', 'complete_item',
                     'ValidationError', 'DuplicateError', 'db_path'):
            self.assertTrue(hasattr(store, name), 'app.store.%s missing' % name)

    def test_store_create_list_complete_roundtrip(self):
        from app import store
        conn = store.connect(self.db_path)
        try:
            item = store.create_item(conn, 'Store roundtrip')
            self.assertEqual(item['title'], 'Store roundtrip')
            self.assertIs(item['completed'], False)
            self.assertEqual([entry['title'] for entry in store.list_items(conn)],
                             ['Store roundtrip'])
            self.assertIs(store.complete_item(conn, item['id'])['completed'], True)
            self.assertIs(store.complete_item(conn, item['id'])['completed'], True)
        finally:
            conn.close()

    def test_store_rejects_blank_and_duplicate_without_persisting(self):
        from app import store
        conn = store.connect(self.db_path)
        try:
            store.create_item(conn, 'Only once')
            with self.assertRaises(store.ValidationError):
                store.create_item(conn, '   \t ')
            with self.assertRaises(store.DuplicateError):
                store.create_item(conn, 'Only once')
            self.assertEqual([entry['title'] for entry in store.list_items(conn)],
                             ['Only once'])
        finally:
            conn.close()

    def test_store_writes_a_sqlite3_file(self):
        from app import store
        conn = store.connect(self.db_path)
        try:
            store.create_item(conn, 'On disk')
        finally:
            conn.close()
        self.assertTrue(os.path.exists(self.db_path))
        reopened = store.connect(self.db_path)
        try:
            self.assertEqual([entry['title'] for entry in store.list_items(reopened)],
                             ['On disk'])
        finally:
            reopened.close()


if __name__ == '__main__':
    unittest.main()
