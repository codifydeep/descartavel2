"""SQLite3 persistence for the disposable feedback board (C1).

This is the contract-declared persistence layer. Every statement is
parameterized; titles are stored verbatim once trimmed, and a UNIQUE constraint
on the stored title backs the duplicate-submission guard.
"""
import os
import sqlite3


DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'feedback.db')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    completed INTEGER NOT NULL DEFAULT 0
)
"""


class ValidationError(ValueError):
    """A submission was rejected before anything was stored."""


class DuplicateError(ValidationError):
    """An identical title already exists."""


def db_path():
    """Resolve the database file, honoring the FEEDBACK_DB_PATH override."""
    return os.environ.get('FEEDBACK_DB_PATH') or DEFAULT_DB_PATH


def connect(path=None):
    """Open (and initialize) a connection to the feedback database."""
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _as_item(row):
    if row is None:
        return None
    return {'id': row['id'], 'title': row['title'], 'completed': bool(row['completed'])}


def _select(conn, item_id):
    return conn.execute(
        'SELECT id, title, completed FROM feedback WHERE id = ?', (item_id,)).fetchone()


def get_item(conn, item_id):
    """Return one feedback item by id, or None when it does not exist."""
    return _as_item(_select(conn, item_id))


def create_item(conn, title):
    """Create a feedback item, rejecting blank or duplicate titles outright."""
    if not isinstance(title, str):
        raise ValidationError('title is required and must not be blank')
    cleaned = title.strip()
    if not cleaned:
        raise ValidationError('title is required and must not be blank')
    duplicate = conn.execute(
        'SELECT id FROM feedback WHERE title = ?', (cleaned,)).fetchone()
    if duplicate is not None:
        raise DuplicateError('duplicate submission: a feedback item with this title already exists')
    cursor = conn.execute(
        'INSERT INTO feedback (title, completed) VALUES (?, 0)', (cleaned,))
    conn.commit()
    return _as_item(_select(conn, cursor.lastrowid))


def list_items(conn, query=None):
    """Return every feedback item in insertion order.

    ``query`` is an optional already-trimmed title needle. When it is truthy the
    listing is narrowed to items whose title contains the needle as a
    case-insensitive, Unicode-aware substring (``str.casefold`` on both sides).
    The needle is applied in Python to the parameterized ``SELECT`` result, so it
    is never interpolated into SQL and cannot alter the query shape.
    """
    rows = conn.execute('SELECT id, title, completed FROM feedback ORDER BY id').fetchall()
    items = [_as_item(row) for row in rows]
    if query:
        folded = query.casefold()
        items = [item for item in items if folded in item['title'].casefold()]
    return items


def complete_item(conn, item_id):
    """Mark an item completed; idempotent and None when the item is unknown."""
    if _select(conn, item_id) is None:
        return None
    conn.execute('UPDATE feedback SET completed = 1 WHERE id = ?', (item_id,))
    conn.commit()
    return _as_item(_select(conn, item_id))
