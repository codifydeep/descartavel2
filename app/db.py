"""Compatibility facade exposing the canonical persistence layer in app.store.

The contract-declared persistence module is ``app/store.py``; this module keeps
the ``app.db`` name importable so the HTTP handler reads through it.
"""
try:  # imported as ``app.db`` (tests) or executed as a top-level module
    from .store import (DEFAULT_DB_PATH, DuplicateError, ValidationError,
                        complete_item, connect, create_item, db_path, list_items)
except ImportError:  # pragma: no cover - direct script execution path
    from store import (DEFAULT_DB_PATH, DuplicateError, ValidationError,
                       complete_item, connect, create_item, db_path, list_items)

__all__ = ['DEFAULT_DB_PATH', 'DuplicateError', 'ValidationError', 'complete_item',
           'connect', 'create_item', 'db_path', 'list_items']
