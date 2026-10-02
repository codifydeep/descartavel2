"""Test-first acceptance tests for SEARCHAPI-1 title search on ``GET /feedback``.

Phase 1 is tests only. The approved contract adds an optional ``q`` parameter to
``GET /feedback`` that narrows the listing to items whose *title* contains ``q``
as a substring, compared with Unicode ``str.casefold`` on both sides:

* ``q`` is trimmed of surrounding whitespace first, and the trimmed value is the
  needle; matching is case-insensitive and Unicode-aware (``casefold``), so e.g.
  a title containing ``Straße`` matches ``q=STRASSE``.
* An absent ``q``, or one that is whitespace-only after trimming, must be
  *exactly* compatible with the pre-existing unsearched response -- byte for
  byte, and identical to a request with no ``q`` at all. Whitespace-only is
  therefore treated as absent, not as an empty needle matching everything.
* Only the title is searched; the description (and any other field) never
  contributes a match.
* ``q`` composes with the existing ``status`` filter (both narrow, intersection),
  and the existing invalid-status 400 errors are preserved unchanged whenever
  ``q`` is present.
* Item order, the ``{"items": [...]}`` envelope, create/complete responses and
  ``GET /feedback/summary`` whole-board counts are all preserved. Summary ignores
  ``q`` entirely.
* ``q`` data is never interpolated into SQL; it is a bound parameter, so SQL
  metacharacters and Unicode round-trip literally without touching the schema.

The frozen base ``app/server.py`` ignores any ``q`` parameter (it reads only
``status``), so every search assertion below is Red before Phase 2, while the
default-compatibility and preservation guards are green in both phases. As
elsewhere in the suite the real stdlib ``http.server`` handler is driven over
loopback against a temporary SQLite file and exact response bytes are inspected,
mirroring the pinned discovery command
(``PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q``).
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


class FeedbackSearchApiTests(unittest.TestCase):
    """``GET /feedback?q=`` must title-substring search, casefolded and trimmed."""

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

    def titles(self, path):
        """Fetch ``path`` and return the ordered titles of a 200 listing."""
        status, _, _, body = self.call('GET', path)
        self.assertEqual(status, 200, 'GET %s must answer 200, got %r' % (path, status))
        return [item['title'] for item in body['items']]

    def search(self, needle):
        """Percent-encode ``needle`` into a ``q=`` query value."""
        from urllib.parse import quote
        return self.titles('/feedback?q=' + quote(needle, safe=''))

    def seed_board(self):
        """A small mixed board with case, spacing, Unicode and overlaps."""
        self.create('Fix login bug')
        self.create('LOGIN redirect')
        self.create('Update docs')
        self.create('Straße signage')
        return None

    # absent / default compatibility -- unchanged unsearched behaviour
    def test_absent_q_is_byte_for_byte_the_unsearched_body(self):
        self.seed_board()
        status, content_type, raw, body = self.call('GET', '/feedback')
        self.assertEqual(status, 200)
        self.assertEqual(
            raw,
            json.dumps({'items': [
                {'id': 1, 'title': 'Fix login bug', 'completed': False},
                {'id': 2, 'title': 'LOGIN redirect', 'completed': False},
                {'id': 3, 'title': 'Update docs', 'completed': False},
                {'id': 4, 'title': 'Straße signage', 'completed': False},
            ]}).encode('utf-8'),
            'GET /feedback without q must keep the legacy body byte for byte')
        self.assertTrue(content_type.lower().startswith('application/json'))

    def test_empty_q_is_exactly_compatible_with_no_search(self):
        self.seed_board()
        base = self.call('GET', '/feedback')[2]
        for path in ('/feedback?q=', '/feedback?q=%20', '/feedback?q=++',
                     '/feedback?q=%09%0a'):
            status, _, raw, _ = self.call('GET', path)
            self.assertEqual(status, 200, '%s must answer 200' % path)
            self.assertEqual(raw, base,
                             'whitespace-only/empty q (%r) must be exactly the '
                             'unsearched response' % path)

    def test_empty_board_search_and_unsearched_are_the_same_empty_body(self):
        status, _, raw, _ = self.call('GET', '/feedback?q=anything')
        self.assertEqual(status, 200)
        self.assertEqual(raw, b'{"items": []}')

    # basic substring match and nonmatch
    def test_substring_match_returns_only_matching_items_in_order(self):
        self.seed_board()
        self.assertEqual(self.search('login'), ['Fix login bug', 'LOGIN redirect'])

    def test_nonmatching_q_returns_an_empty_envelope(self):
        self.seed_board()
        status, _, raw, body = self.call('GET', '/feedback?q=zzz-not-present')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'items': []})
        self.assertEqual(raw, b'{"items": []}')

    def test_match_is_on_title_substring_not_whole_title(self):
        self.create('prefix-middle-suffix')
        self.assertEqual(self.search('middle'), ['prefix-middle-suffix'])
        self.assertEqual(self.search('fix'), ['prefix-middle-suffix'])

    # casefolding
    def test_matching_is_case_insensitive_both_directions(self):
        self.seed_board()
        self.assertEqual(self.search('LOGIN'), ['Fix login bug', 'LOGIN redirect'])
        self.assertEqual(self.search('fIx'), ['Fix login bug'])
        self.assertEqual(self.search('docs'), ['Update docs'])

    def test_whitespace_around_q_is_trimmed_before_matching(self):
        self.seed_board()
        self.assertEqual(self.search('  login  '), ['Fix login bug', 'LOGIN redirect'])
        self.assertEqual(self.search('\tdocs\n'), ['Update docs'])

    # description-only text must never match
    def test_description_text_is_never_matched(self):
        self.create('Alpha item')
        status, _, _, body = self.call(
            'POST', '/feedback', {'title': 'Beta item',
                                  'description': 'uniquedescriptionneedle'})
        self.assertEqual(status, 201)
        self.assertEqual(self.search('uniquedescriptionneedle'), [])
        self.assertEqual(self.search('needle'), [])

    # Unicode: casefold, not a naive lower()
    def test_unicode_casefold_matches_across_case_and_script(self):
        self.create('Straße signage')
        self.create('Σίσυφος task')
        # casefold maps 'ß' to 'ss'; the casefolded title is 'σίσυφοσ task',
        # so both an ASCII 'ss' needle and the accented Greek needle match.
        self.assertEqual(self.search('STRASSE'), ['Straße signage'])
        self.assertEqual(self.search('strasse'), ['Straße signage'])
        # 'ΣΊΣΥΦΟΣ' casefolds to 'σίσυφοσ', the exact casefolded title.
        self.assertEqual(self.search('ΣΊΣΥΦΟΣ'), ['Σίσυφος task'])

    def test_unicode_nonmatch_is_empty(self):
        self.create('Straße signage')
        self.assertEqual(self.search('STRASSEE'), [])
        self.assertEqual(self.search('café'), [])

    def test_accents_and_ligatures_follow_plain_casefold(self):
        self.create('Café résumé')
        self.create('ﬁle upload')
        self.assertEqual(self.search('CAFÉ'), ['Café résumé'])
        self.assertEqual(self.search('RÉSUMÉ'), ['Café résumé'])
        # 'ﬁ' casefolds to 'fi', so plain 'fi' is a substring of the folded title.
        self.assertEqual(self.search('file'), ['ﬁle upload'])
        # casefold preserves accents: the Greek title is 'Σίσυφος task' and its
        # casefolded form 'σίσυφοσ task' begins with an accented 'ί', so an
        # unaccented needle - which must not be accent-folded away - cannot
        # match it.
        self.assertEqual(self.search('σισυφος'), [])

    # composition with the existing status filter
    def test_q_composes_with_status_open_and_completed(self):
        done = self.create('login done')
        self.complete(done['id'])
        self.create('login open')
        self.create('other open')
        self.assertEqual(self.titles('/feedback?status=open&q=login'), ['login open'])
        self.assertEqual(self.titles('/feedback?status=completed&q=login'),
                         ['login done'])
        self.assertEqual(self.titles('/feedback?q=login'),
                         ['login done', 'login open'])

    def test_q_with_status_open_yields_the_intersection(self):
        first = self.create('todo alpha')
        self.create('todo beta')
        self.complete(first['id'])
        self.assertEqual(self.titles('/feedback?q=todo&status=open'), ['todo beta'])
        self.assertEqual(self.titles('/feedback?q=todo&status=completed'),
                         ['todo alpha'])

    def test_q_present_preserves_invalid_status_errors(self):
        self.seed_board()
        for query in ('q=login&status=', 'q=login&status=all', 'q=login&status=bogus',
                      'q=login&status=open&status=completed'):
            status, content_type, raw, body = self.call('GET', '/feedback?' + query)
            self.assertEqual(status, 400,
                             'invalid status must stay 400 even with q (%r)' % query)
            self.assertTrue(content_type.lower().startswith('application/json'))
            self.assertIn('error', body)
            self.assertNotIn(b'items', raw)

    def test_invalid_status_with_q_never_leaks_the_board(self):
        self.seed_board()
        status, _, raw, _ = self.call('GET', '/feedback?q=login&status=all')
        self.assertEqual(status, 400)
        self.assertNotIn(b'Fix login bug', raw)
        self.assertNotIn(b'LOGIN redirect', raw)

    # invalid status without q is exactly the pre-existing error (no regression)
    def test_invalid_status_without_q_is_unchanged(self):
        self.seed_board()
        status, _, _, body = self.call('GET', '/feedback?status=all')
        self.assertEqual(status, 400)
        self.assertIn('error', body)

    # order and envelope are preserved
    def test_filtered_listing_keeps_envelope_and_item_shape(self):
        self.seed_board()
        status, content_type, raw, body = self.call('GET', '/feedback?q=docs')
        self.assertEqual(status, 200)
        self.assertTrue(content_type.lower().startswith('application/json'))
        self.assertEqual(set(body.keys()), {'items'})
        self.assertEqual(len(body['items']), 1)
        item = body['items'][0]
        self.assertEqual(set(item.keys()), {'id', 'title', 'completed'})
        self.assertIsInstance(item['id'], int)
        self.assertNotIsInstance(item['id'], bool)
        self.assertIsInstance(item['title'], str)
        self.assertIs(item['completed'], False)

    def test_preserves_insertion_order_not_sorted(self):
        self.create('zeta match')
        self.create('alpha match')
        self.create('mu match')
        self.assertEqual(self.search('match'), ['zeta match', 'alpha match', 'mu match'])

    # q data is bound, never interpolated into SQL
    def test_q_sql_metacharacters_are_treated_as_literal_text(self):
        self.create("it's a test")
        self.create('quote "title"')
        from urllib.parse import quote
        status, _, _, _ = self.call(
            'GET', '/feedback?q=' + quote("' OR 1=1 --", safe=''))
        self.assertEqual(status, 200)
        self.assertEqual(self.search("' OR 1=1 --"), [])
        self.assertEqual(self.search("quote"), ['quote "title"'])
        # 'title' table/column names appear in titles but must be literal needles
        self.assertEqual(self.search('quote "title"'), ['quote "title"'])

    def test_q_never_drops_the_table_or_board(self):
        self.create('Keep one')
        self.create('Keep two')
        self.call('GET', '/feedback?q=%27%3B%20DROP%20TABLE%20feedback%3B%20--')
        self.assertEqual(self.search('keep'), ['Keep one', 'Keep two'])

    # create/complete responses and summary are untouched by q
    def test_create_and_complete_responses_are_unchanged(self):
        created = self.create('Searchable item')
        self.assertEqual(set(created.keys()), {'id', 'title', 'completed'})
        self.assertIs(created['completed'], False)
        status, _, _, completed = self.call(
            'POST', '/feedback/%d/complete' % created['id'])
        self.assertEqual(status, 200)
        self.assertEqual(completed, {'id': created['id'],
                                     'title': 'Searchable item', 'completed': True})

    def test_summary_ignores_q_and_counts_the_whole_board(self):
        done = self.create('login done')
        self.complete(done['id'])
        self.create('login open')
        self.create('unrelated')
        base_status, base_type, base_raw, base = self.call('GET', '/feedback/summary')
        self.assertEqual(base_status, 200)
        self.assertEqual(base, {'total': 3, 'completed': 1, 'open': 2})
        for query in ('q=login', 'q=unrelated', 'q=zzz', 'q=', 'q=login&status=open'):
            status, content_type, raw, body = self.call(
                'GET', '/feedback/summary?' + query)
            self.assertEqual(status, base_status,
                             'summary must ignore %r' % query)
            self.assertEqual(raw, base_raw,
                             'summary must return identical bytes for %r' % query)
            self.assertEqual(body, base)

    # every matching item actually contains the needle under casefold
    def test_every_returned_item_matches_under_casefold(self):
        self.seed_board()
        needle = 'login'
        status, _, _, body = self.call('GET', '/feedback?q=' + needle)
        self.assertEqual(status, 200)
        self.assertTrue(body['items'], 'expected at least one match for %r' % needle)
        for item in body['items']:
            self.assertIn(needle.casefold(), item['title'].casefold())


class SearchDoesNotTouchSchemaOrExistingRowsTests(unittest.TestCase):
    """The search reads through the existing store; it must not mutate it."""

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

    def test_search_leaves_persisted_rows_and_schema_intact(self):
        from urllib.parse import quote
        self.call('POST', '/feedback', {'title': 'Persisted searchable'})
        self.call('GET', '/feedback?q=searchable')
        self.call('GET', '/feedback?q=' + quote("'; DROP TABLE feedback; --", safe=''))
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                'SELECT title, completed FROM feedback ORDER BY id').fetchall()
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        self.assertEqual(rows, [('Persisted searchable', 0)])
        self.assertIn('feedback', tables)


if __name__ == '__main__':
    unittest.main()
