"""Greeting page: stdlib-only HTTP app serving one same-origin page, /health and /identity."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sys

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Greeting</title>
<link rel="icon" href="data:,">
<style>
body { font-family: sans-serif; margin: 2rem; }
.field-error { color: #b00020; margin-top: 0.5rem; }
#greeting { font-size: 1.25rem; margin-top: 1rem; }
</style>
</head>
<body>
<h1>Greeting</h1>
<form id="greeting-form" novalidate>
  <label for="display-name">Display name</label>
  <input id="display-name" name="display-name" type="text" autocomplete="off">
  <button id="greet-button" type="submit">Greet me</button>
  <p id="name-error" class="field-error" hidden>Please enter a name before greeting.</p>
</form>
<p id="greeting" hidden></p>
<script>
(function () {
  var form = document.getElementById('greeting-form');
  var input = document.getElementById('display-name');
  var message = document.getElementById('name-error');
  var greeting = document.getElementById('greeting');
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var name = input.value.trim();
    if (name === '') {
      greeting.textContent = '';
      greeting.hidden = true;
      message.hidden = false;
      return;
    }
    message.hidden = true;
    greeting.textContent = 'Hello, ' + name + '! Welcome.';
    greeting.hidden = false;
  });
})();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_body(200, 'text/html; charset=utf-8', PAGE.encode('utf-8'))
            return
        if self.path == '/health':
            status, value = 200, {'status': 'ok'}
        elif self.path == '/identity':
            status, value = 200, {'source_sha': os.environ.get('FABRIQUINHA_SOURCE_SHA', '')}
        else:
            status, value = 404, {'error': 'not found'}
        self.send_body(status, 'application/json', json.dumps(value).encode())

    def send_body(self, status, content_type, body):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', int(sys.argv[1])), Handler)
    print(server.server_port, flush=True)
    server.serve_forever()
