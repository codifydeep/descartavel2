"""Generic stdlib HTTP bootstrap; product routes belong to agent-authored cards."""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

try:  # imported as ``app.server`` (tests) or executed as a script (container)
    from . import db
except ImportError:  # pragma: no cover - direct script execution path
    import db


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

# Explicit map keeps served content types stable across hosts and images.
_CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except (TypeError, ValueError):
            return None
        raw = self.rfile.read(length) if length > 0 else b''
        if not raw:
            return {}
        try:
            return json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return None

    def _send_static(self, name):
        """Serve a file from ``STATIC_DIR``, refusing anything outside it."""
        root = os.path.realpath(STATIC_DIR)
        target = os.path.realpath(os.path.join(root, name))
        if target != root and not target.startswith(root + os.sep):
            self.send_error(404)
            return
        if not os.path.isfile(target):
            self.send_error(404)
            return
        extension = os.path.splitext(target)[1].lower()
        content_type = _CONTENT_TYPES.get(extension, 'application/octet-stream')
        with open(target, 'rb') as handle:
            body = handle.read()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/livez':
            # Liveness alias of ``/health``: HTTP 200, ``application/json`` and
            # the exact body ``{"status": "ok"}`` with no ``source_sha`` (or any
            # other key) leaked in. ``urlsplit`` above drops the query string so
            # probes such as ``/livez?probe=1`` resolve to this route unchanged.
            self._send_json(200, {'status': 'ok'})
            return
        if path == '/health':
            body = json.dumps({'status': 'ok',
                               'source_sha': os.environ.get('SOURCE_SHA', 'local')}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ('/ready', '/healthz'):
            # ``/healthz`` is a readiness alias for ``/ready``: same status,
            # same content type and the same body. The query string is parsed
            # off ``self.path`` (see ``urlsplit`` above) so probes such as
            # ``/healthz?probe=1`` resolve to this route unchanged.
            self._send_json(200, {'status': 'ready',
                                  'source_sha': os.environ.get('SOURCE_SHA', 'local')})
            return
        if path == '/':
            self._send_static('index.html')
            return
        if path.startswith('/static/'):
            self._send_static(unquote(path[len('/static/'):]))
            return
        if path == '/feedback':
            # The status filter is the single ``status`` query parameter. It is
            # absent for the UI's All tab, which must stay byte-compatible with
            # the legacy body; ``open`` and ``completed`` narrow the list. Any
            # other shape -- an empty value, an explicit ``all``, an unknown
            # value, repeated keys or an empty token alongside a valid one --
            # is rejected outright rather than silently treated as All.
            occurrences = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            values = occurrences.get('status')
            if values is None:
                wanted = None
            elif len(values) == 1 and values[0] in ('open', 'completed'):
                wanted = values[0] == 'completed'
            else:
                self._send_json(400, {'error': (
                    "invalid status filter: expected 'open' or 'completed'; "
                    "omit the parameter to list every entry")})
                return
            # The optional ``q`` narrows the listing to titles containing the
            # trimmed needle, compared with ``str.casefold``. An absent or
            # whitespace-only value is exactly the unsearched listing. The
            # needle is data: it lives in a Python variable and is never
            # interpolated into SQL.
            raw_q = occurrences.get('q')
            needle = raw_q[0].strip() if raw_q else ''
            conn = db.connect()
            try:
                items = db.list_items(conn, needle)
            finally:
                conn.close()
            if wanted is not None:
                items = [item for item in items if item['completed'] is wanted]
            self._send_json(200, {'items': items})
            return
        if path == '/feedback/summary':
            conn = db.connect()
            try:
                items = db.list_items(conn)
            finally:
                conn.close()
            total = len(items)
            completed = sum(1 for item in items if item['completed'])
            self._send_json(200, {'total': total,
                                  'completed': completed,
                                  'open': total - completed})
            return
        self.send_error(404)

    def do_POST(self):
        parts = urlsplit(self.path).path.strip('/').split('/')
        payload = self._read_json()
        if payload is None:
            self._send_json(400, {'error': 'request body must be valid JSON'})
            return
        if parts == ['feedback']:
            self._create_feedback(payload)
            return
        if len(parts) == 3 and parts[0] == 'feedback' and parts[2] == 'complete':
            self._complete_feedback(parts[1])
            return
        self.send_error(404)

    def _create_feedback(self, payload):
        conn = db.connect()
        try:
            try:
                item = db.create_item(conn, payload.get('title'))
            except db.DuplicateError as exc:
                self._send_json(409, {'error': str(exc)})
                return
            except db.ValidationError as exc:
                self._send_json(400, {'error': str(exc)})
                return
        finally:
            conn.close()
        self._send_json(201, item)

    def _complete_feedback(self, raw_id):
        try:
            item_id = int(raw_id)
        except (TypeError, ValueError):
            self._send_json(400, {'error': 'feedback id must be an integer'})
            return
        conn = db.connect()
        try:
            item = db.complete_item(conn, item_id)
        finally:
            conn.close()
        if item is None:
            self._send_json(404, {'error': 'feedback item %s not found' % raw_id})
            return
        self._send_json(200, item)


def run():
    HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()


if __name__ == '__main__':
    run()
