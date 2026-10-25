"""Infrastructure seed only: product behavior must be authored by the team."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sys


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            status, value = 200, {'status': 'ok'}
        elif self.path == '/identity':
            status, value = 200, {'source_sha': os.environ.get('FABRIQUINHA_SOURCE_SHA', '')}
        else:
            status, value = 404, {'error': 'not found'}
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', int(sys.argv[1])), Handler)
    print(server.server_port, flush=True)
    server.serve_forever()
