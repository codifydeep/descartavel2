"""Generic stdlib HTTP bootstrap; product routes belong to agent-authored cards."""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

try:  # imported as ``app.server`` (tests) or executed as a script (container)
    from . import db
except ImportError:  # pragma: no cover - direct script execution path
    import db


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

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            body = json.dumps({'status': 'ok',
                               'source_sha': os.environ.get('SOURCE_SHA', 'local')}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == '/feedback':
            conn = db.connect()
            try:
                items = db.list_items(conn)
            finally:
                conn.close()
            self._send_json(200, {'items': items})
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
