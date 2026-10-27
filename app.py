"""Greeting page: one same-origin HTML page plus /health and /identity."""
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
</head>
<body>
<h1>Greeting</h1>
<form id="greeting-form" novalidate>
<label for="display-name">Display name</label>
<input id="display-name" name="display-name" type="text" autocomplete="off">
<button id="greet" type="submit">Greet</button>
<button id="reset" type="button">Reset</button>
<p id="validation" role="alert"></p>
</form>
<p id="greeting"></p>
<script>
(function () {
  var form = document.getElementById('greeting-form');
  var input = document.getElementById('display-name');
  var validation = document.getElementById('validation');
  var greeting = document.getElementById('greeting');
  var reset = document.getElementById('reset');
  reset.addEventListener('click', function () {
    input.value = '';
    greeting.textContent = '';
    validation.textContent = '';
  });
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var name = input.value.trim();
    if (name === '') {
      greeting.textContent = '';
      validation.textContent = 'Please enter a display name.';
      return;
    }
    validation.textContent = '';
    greeting.textContent = 'Hello, ' + name + '!';
  });
}());
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            return self.send_body(200, 'text/html; charset=utf-8', PAGE.encode())
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
