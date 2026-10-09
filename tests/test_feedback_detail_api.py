"""Red-first HTTP contract tests for ``GET /feedback/<id>`` (BRIEFDETAIL-1 / C1).

Drives the real stdlib ``Handler`` over loopback against a temporary SQLite DB
seeded through ``db``. Assertions cover the accepted shape, query-string
invariance, fixed 404/400 bodies, and canonical id parsing. Red against the
pinned base, since the route does not exist yet.
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
from urllib.request import urlopen


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.server import Handler  # noqa: E402


class _QuietHandler(Handler):
    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class FeedbackDetailApiTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._saved_db = os.environ.get('FEEDBACK_DB_PATH')
        os.environ['FEEDBACK_DB_PATH'] = os.path.join(cls._tmp.name, 'feedback.db')
        conn = db.connect()
        try:
            cls.item = db.create_item(conn, 'Detail target')
        finally:
            conn.close()
        cls.server = HTTPServer(('127.0.0.1', 0), _QuietHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        if cls._saved_db is None:
            os.environ.pop('FEEDBACK_DB_PATH', None)
        else:
            os.environ['FEEDBACK_DB_PATH'] = cls._saved_db
        cls._tmp.cleanup()

    def _get(self, path):
        url = 'http://127.0.0.1:%d%s' % (self.port, path)
        try:
            with urlopen(url) as resp:
                return resp.status, resp.headers.get('Content-Type'), resp.read()
        except HTTPError as exc:
            return exc.code, exc.headers.get('Content-Type'), exc.read()

    def test_existing_id_returns_fixed_item_shape(self):
        status, ctype, body = self._get('/feedback/%d' % self.item['id'])
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith('application/json'))
        self.assertEqual(json.loads(body), {'item': {
            'id': self.item['id'],
            'title': 'Detail target',
            'completed': False,
        }})

    def test_query_string_does_not_change_detail_result(self):
        plain = self._get('/feedback/%d' % self.item['id'])
        queried = self._get('/feedback/%d?status=open&q=x' % self.item['id'])
        self.assertEqual(queried, plain)

    def test_unknown_positive_id_returns_fixed_404(self):
        status, _, body = self._get('/feedback/999999')
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {'error': 'Feedback not found'})

    def test_noncanonical_ids_return_fixed_400(self):
        for raw in ('0', '-1', '01', '1a', 'abc'):
            with self.subTest(raw=raw):
                status, _, body = self._get('/feedback/%s' % raw)
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(body), {'error': 'Invalid feedback id'})

    def test_feedback_list_and_summary_still_served(self):
        status, _, body = self._get('/feedback')
        self.assertEqual(status, 200)
        self.assertIn('items', json.loads(body))
        status, _, body = self._get('/feedback/summary')
        self.assertEqual(status, 200)
        self.assertEqual(set(json.loads(body)), {'total', 'completed', 'open'})


if __name__ == '__main__':
    unittest.main()
