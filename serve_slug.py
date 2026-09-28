"""Local-only fixture service. The controller validates the exact source SHA."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from urllib.parse import parse_qs, urlsplit

import slugapp


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path)
        query = parse_qs(path.query)
        if path.path == '/health':
            body = {'status': 'ok'}
        elif path.path == '/slug':
            body = {'result': slugapp.slugify(query.get('text', [''])[0])}
        elif path.path == '/truncate' and hasattr(slugapp, 'truncate_slug'):
            try:
                body = {'result': slugapp.truncate_slug(query.get('text', [''])[0],
                                                        int(query.get('limit', ['0'])[0]))}
            except (ValueError, TypeError):
                self.send_error(400)
                return
        else:
            self.send_error(404)
            return
        encoded = json.dumps({**body, 'source_sha': os.environ['SOURCE_SHA']}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
