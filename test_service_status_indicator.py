"""Test-first acceptance for BRIEFSTATUS-1 C2: the accessible service-status
indicator on page load.

Phase 1 is tests only. This file is the declared NEW acceptance test. It drives
the *real* assets -- ``app/static/index.html`` served over the real stdlib
``http.server`` handler and the *real* ``app/static/app.js`` executed inside a
Node ``vm`` context whose global is a faithful ``Window`` -- never a source
regex or reimplemented client. It follows the pinned in-repo harness pattern of
``tests/test_browser_feedback_flow.py`` / ``tests/test_feedback_search_client.py``.

The real page must ship an element ``id="service-status" role="status"`` whose
initial text is exactly ``Checking service\u2026`` (U+2026). On each page load the
client issues exactly one same-origin relative GET ``/service-status`` (no
polling, interval or repeat) and sets the indicator to exactly ``Service
available`` when the parsed JSON is exactly ``{"status":"available"}``, else
exactly ``Service unavailable`` for a network failure, a non-200, unparseable
JSON, or any other body. The update must never lock the form, clear a draft or
disturb filter/search/sort state, and two browser contexts must stay
independent. Every assertion below is Red against the pinned base (which ships
no such element and no such request) and turns Green once the frontend card
lands.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.server import Handler  # noqa: E402


INDEX_HTML_PATH = ROOT / 'app' / 'static' / 'index.html'
APP_JS_PATH = ROOT / 'app' / 'static' / 'app.js'

STATUS_ID = 'service-status'
CHECKING_TEXT = 'Checking service\u2026'
AVAILABLE_TEXT = 'Service available'
UNAVAILABLE_TEXT = 'Service unavailable'

# Bounded execution: a hung script must fail loudly, never stall the suite.
NODE_TIMEOUT_SECONDS = 60

# Every scenario below resolves the pending /service-status request after the
# operator has typed a draft and changed filter/search/sort, so the client's own
# update path is exercised against live page state.
SCENARIOS = ('success', 'network', 'http500', 'badjson', 'wrongbody', 'extrafield')
EXPECTED_TEXT = {
    'success': AVAILABLE_TEXT,
    'network': UNAVAILABLE_TEXT,
    'http500': UNAVAILABLE_TEXT,
    'badjson': UNAVAILABLE_TEXT,
    'wrongbody': UNAVAILABLE_TEXT,
    'extrafield': UNAVAILABLE_TEXT,
}


NODE_HARNESS_TEMPLATE = r"""'use strict';
const vm = require('vm');
const fs = require('fs');
const SOURCE_PATH = __SOURCE_PATH__;
const HTML_PATH = __HTML_PATH__;
const SCENARIOS = __SCENARIOS__;
const SOURCE = fs.readFileSync(SOURCE_PATH, 'utf8');
const HTML = fs.readFileSync(HTML_PATH, 'utf8');

// Never let a rejected probe promise abort the process.
process.on('unhandledRejection', function () {});

function walk(node, visit) {
  visit(node);
  for (let i = 0; i < node.children.length; i += 1) { walk(node.children[i], visit); }
}

function makeWorld(mode) {
  const byId = {};

  function makeElement(id, tagName) {
    const el = {
      id: id, tagName: (tagName || 'div').toUpperCase(), children: [], _text: '',
      className: '', type: '', disabled: false, hidden: false, value: '',
      elements: {}, attributes: {}, listeners: {}, options: [],
      parentNode: null,
      classList: {
        _set: new Set(),
        add: function (c) { this._set.add(c); },
        remove: function (c) { this._set.delete(c); },
        toggle: function (c, on) {
          const force = (on === undefined) ? !this._set.has(c) : Boolean(on);
          if (force) { this._set.add(c); } else { this._set.delete(c); }
          return force;
        },
        contains: function (c) { return this._set.has(c); }
      },
      appendChild: function (child) { child.parentNode = this; this.children.push(child); return child; },
      addEventListener: function (type, handler) {
        (this.listeners[type] = this.listeners[type] || []).push(handler);
      },
      removeEventListener: function (type, handler) {
        const list = this.listeners[type] || [];
        this.listeners[type] = list.filter(function (h) { return h !== handler; });
      },
      dispatchEvent: function (event) {
        const list = this.listeners[(event && event.type) || ''] || [];
        for (let i = 0; i < list.length; i += 1) { list[i](event); }
        return true;
      },
      setAttribute: function (name, value) {
        this.attributes[name] = String(value);
        if (name === 'id') { byId[this.attributes[name]] = this; }
      },
      getAttribute: function (name) {
        return Object.prototype.hasOwnProperty.call(this.attributes, name)
          ? this.attributes[name] : null;
      },
      hasAttribute: function (name) {
        return Object.prototype.hasOwnProperty.call(this.attributes, name);
      },
      contains: function (node) {
        if (node === this) { return true; }
        for (let i = 0; i < this.children.length; i += 1) {
          if (this.children[i] === node || this.children[i].contains(node)) { return true; }
        }
        return false;
      },
      matches: function (selector) {
        const sel = String(selector).trim();
        const tag = /^[a-zA-Z][\w:-]*/.exec(sel);
        if (tag && this.tagName !== tag[0].toUpperCase()) { return false; }
        const rest = sel.slice(tag ? tag[0].length : 0);
        const re = /([.#]?[\w:-]+|\[[^\]]*\])/g;
        let part;
        while ((part = re.exec(rest)) !== null) {
          const token = part[0];
          if (token.charAt(0) === '.') {
            if (String(this.className).split(/\s+/).indexOf(token.slice(1)) === -1) { return false; }
          } else if (token.charAt(0) === '#') {
            if (this.id !== token.slice(1)) { return false; }
          } else if (token.charAt(0) === '[') {
            const body = token.slice(1, -1);
            const eq = body.indexOf('=');
            if (eq === -1) {
              if (!this.hasAttribute(body.trim())) { return false; }
            } else {
              const name = body.slice(0, eq).trim();
              let value = body.slice(eq + 1).trim();
              const quoted = /^"([\s\S]*)"$/.exec(value) || /^'([\s\S]*)'$/.exec(value);
              if (quoted) { value = quoted[1]; }
              if (this.getAttribute(name) !== value) { return false; }
            }
          }
        }
        return true;
      },
      querySelector: function (selector) {
        const found = this.querySelectorAll(selector);
        return found.length ? found[0] : null;
      },
      querySelectorAll: function (selector) {
        const out = [];
        walk(this, function (node) { if (node !== el && node.matches(selector)) { out.push(node); } });
        return out;
      },
      focus: function () {},
      reset: function () {
        Object.keys(this.elements).forEach(function (k) { this.elements[k].value = ''; }, this);
      }
    };
    Object.defineProperty(el, 'textContent', {
      get: function () { return this._text; },
      set: function (value) { this._text = String(value); }
    });
    Object.defineProperty(el, 'innerHTML', {
      get: function () { return this._text; },
      set: function (value) { this._text = String(value); this.children = []; }
    });
    return el;
  }

  // --- faithful HTML tokenizer: build the tree the client actually addresses --
  function parseHTML(source) {
    const root = DOCUMENT;
    const stack = [root];
    const VOID = { area: 1, base: 1, br: 1, col: 1, embed: 1, hr: 1, img: 1,
                   input: 1, link: 1, meta: 1, param: 1, source: 1, track: 1, wbr: 1 };
    const token = /<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<!DOCTYPE[^>]*>|<\/\s*([a-zA-Z][\w:-]*)\s*>|<([a-zA-Z][\w:-]*)((?:\s+[\w:-]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*)\s*(\/?)>|([^<]+)/g;
    const attrRe = /([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
    let m;
    while ((m = token.exec(source)) !== null) {
      const tag = m[2];
      if (tag) {
        const el = makeElement('#parse', tag);
        if (m[3]) {
          let a;
          attrRe.lastIndex = 0;
          while ((a = attrRe.exec(m[3])) !== null) {
            const name = a[1];
            const value = (a[2] !== undefined) ? a[2] : (a[3] !== undefined) ? a[3] : (a[4] !== undefined) ? a[4] : '';
            el.attributes[name] = value;
            if (name === 'id') { el.id = value; byId[value] = el; }
            if (name === 'class') { el.className = value; }
            if (name === 'type') { el.type = value; }
          }
        }
        stack[stack.length - 1].appendChild(el);
        if (!VOID[tag.toLowerCase()] && m[4] !== '/') { stack.push(el); }
      } else if (m[1]) {
        const name = m[1].toLowerCase();
        for (let i = stack.length - 1; i >= 1; i -= 1) {
          if (stack[i].tagName.toLowerCase() === name) { stack.length = i; break; }
        }
      } else if (m[5] && m[5].trim()) {
        const text = m[5].replace(/\s+/g, ' ').trim();
        if (text) { const node = makeElement('#text', 'text'); node._text = text; stack[stack.length - 1].appendChild(node); }
      }
    }
    return root;
  }

  const DOCUMENT = makeElement('#document', 'html');
  Object.defineProperty(DOCUMENT, 'documentElement', { value: DOCUMENT });
  const htmlMatch = HTML.match(/<html\b[^>]*>([\s\S]*?)<\/html>/i);
  parseHTML(htmlMatch ? htmlMatch[1] : HTML);

  const form = byId['feedback-form'];
  if (form) {
    form.elements.title = byId['title'];
    form.elements.description = byId['description'];
  }
  const submitButton = form ? form.querySelector('button[type="submit"]') : null;

  // --- board behind the fetch contract ---------------------------------------
  const items = [];
  let nextId = 1;
  function summaryCounts() {
    const completed = items.filter(function (it) { return it.completed; }).length;
    return { total: items.length, completed: completed, open: items.length - completed };
  }
  function jsonResponse(body, ok) {
    return {
      ok: (ok === undefined) ? true : ok,
      status: (ok === undefined || ok) ? 200 : 500,
      json: function () { return Promise.resolve(body); }
    };
  }

  const calls = [];
  let statusDeferred = null;
  function defaultFetch(url, options) {
    const method = (options && options.method) || 'GET';
    const target = String(url);
    calls.push({ url: target, method: String(method) });
    if (target === '/service-status') {
      statusDeferred = { resolve: null, reject: null };
      return new Promise(function (resolve, reject) { statusDeferred.resolve = resolve; statusDeferred.reject = reject; });
    }
    if (target === '/feedback' && method === 'GET') {
      return Promise.resolve(jsonResponse({ items: items.slice() }, true));
    }
    if (target === '/feedback' && method === 'POST') {
      let title = 'Untitled';
      try { const body = JSON.parse(options && options.body); title = (body && body.title) || title; } catch (error) { /* keep default */ }
      const item = { id: nextId, title: title, completed: false };
      nextId += 1; items.push(item);
      return Promise.resolve(jsonResponse(item, true));
    }
    if (target === '/feedback/summary') { return Promise.resolve(jsonResponse(summaryCounts(), true)); }
    const complete = /^\/feedback\/(\d+)\/complete$/.exec(target);
    if (complete) {
      const id = Number(complete[1]);
      items.forEach(function (it) { if (it.id === id) { it.completed = true; } });
      return Promise.resolve(jsonResponse({ id: id, completed: true }, true));
    }
    return Promise.resolve(jsonResponse({}, true));
  }

  // --- native Window global (status write coerces with String) ---------------
  let intervalCallback = null;
  let intervalDelay = null;
  const target = {
    Boolean: Boolean, Promise: Promise, JSON: JSON, Math: Math, String: String,
    Number: Number, Array: Array, Object: Object, Error: Error, Date: Date,
    RegExp: RegExp, Set: Set, Map: Map, Symbol: Symbol,
    document: {
      getElementById: function (id) { return byId[id] || null; },
      createElement: function (tag) { return makeElement('<' + tag + '>', tag); },
      querySelector: function (selector) { return DOCUMENT.querySelector(selector); },
      querySelectorAll: function (selector) { return DOCUMENT.querySelectorAll(selector); },
      addEventListener: function () {}
    },
    fetch: defaultFetch,
    setTimeout: function () { return 0; },
    clearTimeout: function () {},
    setInterval: function (fn, delay) { intervalCallback = fn; intervalDelay = delay; return 0; },
    clearInterval: function () {},
    console: { log: function () {}, error: function () {}, warn: function () {} }
  };
  const sandbox = new Proxy(target, {
    set: function (t, key, value) { t[key] = (key === 'status') ? String(value) : value; return true; },
    get: function (t, key) { return t[key]; },
    has: function (t, key) { return key in t; },
    defineProperty: function (t, key, descriptor) {
      t[key] = (key === 'status') ? String(descriptor.value) : descriptor.value; return true;
    },
    getOwnPropertyDescriptor: function (t, key) { return Object.getOwnPropertyDescriptor(t, key); },
    deleteProperty: function (t, key) { delete t[key]; return true; },
    ownKeys: function (t) { return Reflect.ownKeys(t); }
  });
  target.window = sandbox;
  target.self = sandbox;
  target.globalThis = sandbox;
  const context = vm.createContext(sandbox);

  function flush() {
    let chain = Promise.resolve();
    for (let i = 0; i < 12; i += 1) { chain = chain.then(function () { return undefined; }); }
    return chain;
  }
  function fire(control, type, extra) {
    const event = Object.assign({ type: type, target: control, currentTarget: control,
                                  preventDefault: function () {} }, extra || {});
    const handlers = control.listeners[type] || [];
    for (let i = 0; i < handlers.length; i += 1) { handlers[i](event); }
    return true;
  }
  function statusNode() { return byId['service-status'] || null; }
  function snapshot() {
    const node = statusNode();
    return {
      service_text: node ? node.textContent : null,
      service_role: node ? node.getAttribute('role') : null,
      draft_title: byId['title'] ? byId['title'].value : null,
      draft_description: byId['description'] ? byId['description'].value : null,
      search_value: byId['feedback-search'] ? byId['feedback-search'].value : null,
      sort_value: byId['sort-feedback'] ? byId['sort-feedback'].value : null,
      submit_disabled: submitButton ? submitButton.disabled === true : null,
      form_aria_busy: form ? form.getAttribute('aria-busy') : null,
      filter_open_pressed: byId['filter-open'] ? byId['filter-open'].getAttribute('aria-pressed') : null,
      filter_completed_pressed: byId['filter-completed'] ? byId['filter-completed'].getAttribute('aria-pressed') : null
    };
  }
  function settle(mode) {
    if (!statusDeferred) { return false; }
    if (mode === 'network') { statusDeferred.reject(new TypeError('Failed to fetch')); return true; }
    if (mode === 'http500') { statusDeferred.resolve(jsonResponse({}, false)); return true; }
    if (mode === 'badjson') {
      statusDeferred.resolve({ ok: true, status: 200, json: function () { return Promise.reject(new SyntaxError('bad json')); } });
      return true;
    }
    if (mode === 'wrongbody') { statusDeferred.resolve(jsonResponse({ status: 'down' }, true)); return true; }
    if (mode === 'extrafield') { statusDeferred.resolve(jsonResponse({ status: 'available', extra: true }, true)); return true; }
    statusDeferred.resolve(jsonResponse({ status: 'available' }, true));
    return true;
  }

  return (async function drive() {
    let executed = true, error = null;
    try {
      const script = new vm.Script(SOURCE, { filename: SOURCE_PATH });
      script.runInContext(context);
    } catch (thrown) { executed = false; error = String((thrown && thrown.message) || thrown); }
    if (!executed) { return { mode: mode, executed: false, error: error }; }

    await flush();
    const initial_service_calls = calls.filter(function (c) { return c.url === '/service-status'; }).length;
    const initial = snapshot();

    // The operator types a draft and changes filter, search and sort while the
    // availability request is still pending.
    if (byId['title']) { byId['title'].value = 'Draft title'; }
    if (byId['description']) { byId['description'].value = 'draft description'; }
    if (byId['feedback-search']) {
      byId['feedback-search'].value = 'needle';
      fire(byId['feedback-search'], 'keydown', { key: 'Enter', bubbles: true });
    }
    if (byId['filter-open']) { fire(byId['filter-open'], 'click'); }
    if (byId['sort-feedback']) { byId['sort-feedback'].value = 'oldest-first'; fire(byId['sort-feedback'], 'change'); }
    await flush();
    const before_settle = snapshot();
    const before_settle_board_urls = calls.filter(function (c) { return c.method === 'GET' && c.url.indexOf('/feedback') === 0; })
      .map(function (c) { return c.url; });

    settle(mode);
    await flush();
    const after_settle = snapshot();
    const service_calls = calls.filter(function (c) { return c.url === '/service-status'; });

    // A poll tick must not re-request availability.
    if (typeof intervalCallback === 'function') { intervalCallback(); }
    await flush();
    const polled_service_calls = calls.filter(function (c) { return c.url === '/service-status'; }).length;

    return {
      mode: mode, executed: true, error: null,
      initial_service_calls: initial_service_calls,
      service_methods: service_calls.map(function (c) { return c.method; }),
      service_urls: service_calls.map(function (c) { return c.url; }),
      polled_service_calls: polled_service_calls,
      interval_delay: intervalDelay,
      initial: initial,
      before_settle: before_settle,
      after_settle: after_settle,
      before_settle_board_urls: before_settle_board_urls
    };
  })();
}

Promise.all(SCENARIOS.map(makeWorld)).then(function (reports) {
  const byMode = {};
  reports.forEach(function (r) { byMode[r.mode] = r; });
  process.stdout.write(JSON.stringify({ filename: SOURCE_PATH, html: HTML_PATH, reports: byMode }));
}).catch(function (thrown) {
  process.stdout.write(JSON.stringify({ filename: SOURCE_PATH, error: String((thrown && thrown.message) || thrown) }));
});
"""


def _load_harness():
    program = (NODE_HARNESS_TEMPLATE
               .replace('__SOURCE_PATH__', json.dumps(str(APP_JS_PATH)))
               .replace('__HTML_PATH__', json.dumps(str(INDEX_HTML_PATH)))
               .replace('__SCENARIOS__', json.dumps(list(SCENARIOS))))
    node = shutil.which('node')
    if not node:
        raise unittest.SkipTest('node executable is unavailable')
    completed = subprocess.run(
        [node, '--input-type=commonjs', '-'],
        input=program.encode('utf-8'),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=NODE_TIMEOUT_SECONDS, check=False)
    if completed.returncode != 0:
        raise AssertionError('Node harness exited %d: %s' % (
            completed.returncode, completed.stderr.decode('utf-8', 'replace')))
    raw = completed.stdout.decode('utf-8', 'replace').strip()
    if not raw:
        raise AssertionError('Node harness produced no report')
    return json.loads(raw)


class _QuietHandler(Handler):
    """The real handler with request logging silenced."""

    def log_message(self, *args):
        pass


class ServiceStatusMarkupTests(unittest.TestCase):
    """``GET /`` must serve the accessible indicator with its initial text."""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), _QuietHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        import os
        self._saved_db = os.environ.get('FEEDBACK_DB_PATH')
        os.environ['FEEDBACK_DB_PATH'] = os.path.join(self._tmp.name, 'feedback.db')

    def tearDown(self):
        import os
        if self._saved_db is None:
            os.environ.pop('FEEDBACK_DB_PATH', None)
        else:
            os.environ['FEEDBACK_DB_PATH'] = self._saved_db
        self._tmp.cleanup()

    def get_root(self):
        request = Request('http://127.0.0.1:%d/' % self.port)
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            return response.read().decode('utf-8', 'replace')

    def test_root_serves_an_element_with_the_service_status_id_and_role(self):
        body = self.get_root()
        self.assertIn('id="service-status"', body,
                      "GET / must contain an element with id='service-status'")
        # The element carrying that id must declare role="status".
        self.assertRegex(
            body, r'<[^>]*id="service-status"[^>]*\brole="status"|<[^>]*\brole="status"[^>]*id="service-status"',
            "the #service-status element must declare role='status'")

    def test_root_ships_the_exact_initial_checking_text(self):
        body = self.get_root()
        self.assertIn(CHECKING_TEXT, body,
                      "the initial indicator text must be exactly 'Checking service\u2026'")


class ServiceStatusClientTests(unittest.TestCase):
    """The real ``app.js`` must fetch ``/service-status`` once and render state."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')

    def setUp(self):
        self.assertTrue(APP_JS_PATH.is_file(), 'declared client asset missing: %s' % APP_JS_PATH)
        self.assertTrue(INDEX_HTML_PATH.is_file(), 'declared page asset missing: %s' % INDEX_HTML_PATH)
        self.assertTrue(self.node, 'node executable is unavailable')
        self.report = _load_harness()
        self.assertEqual(self.report.get('filename'), str(APP_JS_PATH),
                         'the harness must execute the declared app.js')
        for mode in SCENARIOS:
            world = self.report.get('reports', {}).get(mode)
            self.assertIsNotNone(world, 'scenario %r missing from report' % mode)
            self.assertTrue(world.get('executed'),
                            'app.js did not run for %r: %s' % (mode, world.get('error')))

    def world(self, mode):
        return self.report['reports'][mode]

    def test_indicator_initial_text_is_exactly_checking_service(self):
        """The shipped element's initial text is exactly 'Checking service\u2026'."""
        for mode in SCENARIOS:
            initial = self.world(mode)['initial']
            self.assertEqual(
                initial['service_text'], CHECKING_TEXT,
                "before the response the indicator must read exactly 'Checking service\u2026', got %r in %r"
                % (initial['service_text'], mode))
            self.assertEqual(initial['service_role'], 'status',
                             "the indicator must be a role='status' live region in %r" % mode)

    def test_each_page_load_issues_exactly_one_same_origin_service_status_get(self):
        """Exactly one same-origin relative GET '/service-status' per page load."""
        for mode in SCENARIOS:
            world = self.world(mode)
            self.assertEqual(
                world['initial_service_calls'], 1,
                'a page load must issue exactly one /service-status request, got %r in %r'
                % (world['initial_service_calls'], mode))
            self.assertEqual(world['service_urls'], ['/service-status'],
                             'the request must target the relative path /service-status exactly in %r' % mode)
            self.assertEqual(world['service_methods'], ['GET'],
                             'the availability request must be a GET in %r' % mode)

    def test_indicator_does_not_repeat_or_poll(self):
        """No interval, polling or repeat request for availability."""
        for mode in SCENARIOS:
            world = self.world(mode)
            self.assertEqual(
                world['polled_service_calls'], 1,
                'a poll tick must not re-request /service-status, got %r in %r'
                % (world['polled_service_calls'], mode))
            if world['interval_delay'] is not None:
                self.assertGreater(world['interval_delay'], 0,
                                   'the board poll must remain a bounded numeric interval')

    def test_success_body_yields_service_available(self):
        """200 + parsed JSON exactly {'status':'available'} -> 'Service available'."""
        world = self.world('success')
        self.assertEqual(world['after_settle']['service_text'], AVAILABLE_TEXT,
                         'a successful probe must read exactly %r, got %r'
                         % (AVAILABLE_TEXT, world['after_settle']['service_text']))

    def test_every_non_exact_payload_yields_service_unavailable(self):
        """Network failure, non-200, bad JSON or any other body -> unavailable."""
        for mode in ('network', 'http500', 'badjson', 'wrongbody', 'extrafield'):
            world = self.world(mode)
            self.assertEqual(
                world['after_settle']['service_text'], UNAVAILABLE_TEXT,
                'scenario %r must read exactly %r, got %r'
                % (mode, UNAVAILABLE_TEXT, world['after_settle']['service_text']))

    def test_indicator_update_never_locks_form_or_disturbs_page_state(self):
        """The update must not lock the form, clear a draft or change filter/search/sort."""
        for mode in SCENARIOS:
            world = self.world(mode)
            before = world['before_settle']
            after = world['after_settle']
            self.assertNotEqual(before['service_text'], after['service_text'],
                                'the indicator must actually update in %r' % mode)
            self.assertEqual(after['service_text'], EXPECTED_TEXT[mode])
            self.assertFalse(after['submit_disabled'],
                             'the update must never disable the submit control in %r' % mode)
            self.assertEqual(after['form_aria_busy'], 'false',
                             'the form must not stay/become busy on the update in %r' % mode)
            self.assertEqual(after['draft_title'], 'Draft title',
                             'the update must never clear the typed title draft in %r' % mode)
            self.assertEqual(after['draft_description'], 'draft description',
                             'the update must never clear the typed description draft in %r' % mode)
            self.assertEqual(after['search_value'], 'needle',
                             'the update must never change search state in %r' % mode)
            self.assertEqual(after['sort_value'], 'oldest-first',
                             'the update must never change sort state in %r' % mode)
            self.assertEqual(after['filter_open_pressed'], 'true',
                             'the update must never change the active filter in %r' % mode)
            self.assertEqual(after['filter_completed_pressed'], 'false',
                             'the update must never change the active filter in %r' % mode)
            self.assertTrue(
                any('status=open' in url for url in world['before_settle_board_urls']),
                'the selected filter must drive the board request in %r: %r'
                % (mode, world['before_settle_board_urls']))

    def test_browser_contexts_remain_independent(self):
        """Each context issues its own request and shows its own state."""
        success = self.world('success')
        unavailable = self.world('network')
        self.assertEqual(success['initial_service_calls'], 1)
        self.assertEqual(unavailable['initial_service_calls'], 1)
        self.assertEqual(success['after_settle']['service_text'], AVAILABLE_TEXT)
        self.assertEqual(unavailable['after_settle']['service_text'], UNAVAILABLE_TEXT)
        self.assertNotEqual(success['after_settle']['service_text'],
                            unavailable['after_settle']['service_text'],
                            'two contexts must render their own independent state')


if __name__ == '__main__':
    unittest.main()
