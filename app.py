"""Greeting page (AC1, AC2) plus health and identity endpoints. Python stdlib only."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sys

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>Greeting</title>
<style>
[hidden] { display: none !important; }
body { font-family: sans-serif; margin: 2rem; max-width: 32rem; }
label { display: block; margin-bottom: 0.5rem; }
input { font: inherit; padding: 0.4rem; width: 100%; box-sizing: border-box; }
button { font: inherit; margin-top: 0.5rem; padding: 0.4rem 1rem; }
.validation { color: #b00020; margin: 0.25rem 0 0; }
.greeting { font-size: 1.25rem; margin-top: 1rem; }
</style>
</head>
<body>
<h1>Greeting</h1>
<form id="greeting-form" novalidate>
  <label for="display-name">Display name</label>
  <input id="display-name" name="display-name" type="text" autocomplete="off">
  <p id="validation" class="validation" role="alert" hidden>Please enter a display name.</p>
  <button id="greet" type="submit">Greet me</button>
</form>
<p id="greeting" class="greeting" aria-live="polite" hidden></p>
<script>
(function () {
  var form = document.getElementById('greeting-form');
  var input = document.getElementById('display-name');
  var validation = document.getElementById('validation');
  var greeting = document.getElementById('greeting');
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var name = input.value.trim();
    if (name === '') {
      greeting.textContent = '';
      greeting.hidden = true;
      validation.hidden = false;
      return;
    }
    validation.hidden = true;
    greeting.textContent = 'Hello, ' + name + '!';
    greeting.hidden = false;
  });
}());
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            body = PAGE.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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
