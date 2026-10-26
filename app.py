"""Greeting page app (stdlib only): GET /, GET /health, GET /identity."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sys


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>Greeting</title>
<style>
body { font-family: sans-serif; margin: 2rem; }
form { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
#field-message { flex-basis: 100%; }
.validation { color: #b00020; margin: 0.25rem 0 0; }
.greeting { font-size: 1.25rem; margin-top: 1rem; }
</style>
</head>
<body>
<h1>Greeting</h1>
<form id="greet-form" data-testid="greet-form" novalidate>
  <label for="name-input">Display name</label>
  <input id="name-input" data-testid="name-input" type="text" autocomplete="off">
  <button type="submit" data-testid="submit">Greet</button>
  <div id="field-message"></div>
</form>
<div id="output"></div>
<script>
(function () {
  var form = document.getElementById('greet-form');
  var input = document.getElementById('name-input');
  var fieldMessage = document.getElementById('field-message');
  var output = document.getElementById('output');

  function clearValidation() {
    fieldMessage.textContent = '';
  }

  function showValidation(text) {
    clearValidation();
    var p = document.createElement('p');
    p.className = 'validation';
    p.setAttribute('data-testid', 'validation');
    p.setAttribute('role', 'alert');
    p.textContent = text;
    fieldMessage.appendChild(p);
  }

  function clearGreeting() {
    output.textContent = '';
  }

  function showGreeting(name) {
    clearGreeting();
    var p = document.createElement('p');
    p.className = 'greeting';
    p.setAttribute('data-testid', 'greeting');
    p.textContent = 'Hello, ' + name + '!';
    output.appendChild(p);
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var name = input.value.trim();
    if (name === '') {
      clearGreeting();
      showValidation('Please enter a display name.');
      return;
    }
    clearValidation();
    showGreeting(name);
  });
})();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self._send(200, 'text/html; charset=utf-8', PAGE.encode('utf-8'))
            return
        if self.path == '/health':
            status, value = 200, {'status': 'ok'}
        elif self.path == '/identity':
            status, value = 200, {'source_sha': os.environ.get('FABRIQUINHA_SOURCE_SHA', '')}
        else:
            status, value = 404, {'error': 'not found'}
        self._send(status, 'application/json', json.dumps(value).encode())

    def _send(self, status, content_type, body):
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
