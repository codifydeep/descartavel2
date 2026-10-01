"""Test-first acceptance for FILTER-1 C2: the browser filter control.

Phase 1 is tests only; this file is the declared C2 test file.

Backend guards (the C1 contract the C2 UI consumes) run over the real stdlib
``http.server`` handler on loopback against a temporary SQLite file. The CTO
contract is ``{"parameter": "status", "absent": "all", "empty": "400",
"explicit_all": "400", "unknown": "400"}``: All omits ``status``; ``open`` and
``completed`` narrow to that state; an empty, explicit ``all``, unknown or
repeated value is a 400 JSON error.

Client behavior runs for real under a Node ``vm`` whose global is a faithful
``Window`` (harness shape of ``tests/test_feedback_pending_submit.py``): filter
control, empty messages, polling survival, draft preservation, in-flight submit
protection, accessibility and the stale-response discard rule are observed by
behavior. The frozen base has no filter control and never reads ``status``, so
every client assertion fails Red before Phase 2. Runs are bounded by a subprocess
timeout and settle promises deterministically, with no sleeps, skips or
swallowed exceptions.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.server import Handler  # noqa: E402

APP_JS_PATH = ROOT / 'app' / 'static' / 'app.js'
NODE_TIMEOUT_SECONDS = 30

FILTER_IDS = ('filter-all', 'filter-open', 'filter-completed')
OPEN_TERMS = ('open', 'active')
COMPLETED_TERMS = ('completed', 'done', 'complete')


class _QuietHandler(Handler):
    """The real handler with request logging silenced for clean test output."""

    def log_message(self, *args):  # noqa: D401 - test helper
        pass


class StatusFilterBackendTests(unittest.TestCase):
    """``GET /feedback`` must honour the CTO status contract for the UI."""

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
        self._saved = os.environ.get('FEEDBACK_DB_PATH')
        os.environ['FEEDBACK_DB_PATH'] = os.path.join(self._tmp.name, 'feedback.db')

    def tearDown(self):
        if self._saved is None:
            os.environ.pop('FEEDBACK_DB_PATH', None)
        else:
            os.environ['FEEDBACK_DB_PATH'] = self._saved
        self._tmp.cleanup()

    def call(self, method, path, payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = Request('http://127.0.0.1:%d%s' % (self.port, path),
                          data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                status = response.status
                content_type = response.headers.get('Content-Type', '')
                raw = response.read()
        except HTTPError as error:
            status = error.code
            content_type = error.headers.get('Content-Type', '') if error.headers else ''
            raw = error.read()
        try:
            body = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            body = None
        return status, content_type, raw, body

    def create(self, title):
        status, _, _, body = self.call('POST', '/feedback', {'title': title})
        self.assertEqual(status, 201, 'fixture create must succeed')
        return body

    def complete(self, item_id):
        status, _, _, body = self.call('POST', '/feedback/%d/complete' % item_id)
        self.assertEqual(status, 200, 'fixture complete must succeed')
        return body

    def seed_mixed_board(self):
        done = self.create('Done first')
        self.complete(done['id'])
        self.create('Open second')
        self.create('Open third')
        return done

    def test_absent_status_is_all_items_in_insertion_order(self):
        self.seed_mixed_board()
        status, _, _, body = self.call('GET', '/feedback')
        self.assertEqual(status, 200)
        self.assertEqual([item['title'] for item in body['items']],
                         ['Done first', 'Open second', 'Open third'])

    def test_status_open_and_completed_narrow_to_that_state(self):
        self.seed_mixed_board()
        _, _, _, opened = self.call('GET', '/feedback?status=open')
        self.assertEqual([item['title'] for item in opened['items']],
                         ['Open second', 'Open third'])
        self.assertTrue(all(item['completed'] is False for item in opened['items']))
        _, _, _, completed = self.call('GET', '/feedback?status=completed')
        self.assertEqual([item['title'] for item in completed['items']], ['Done first'])
        self.assertTrue(all(item['completed'] is True for item in completed['items']))

    def test_empty_result_for_a_state_with_no_items(self):
        self.create('Only open')
        status, _, _, body = self.call('GET', '/feedback?status=completed')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'items': []})

    def test_empty_explicit_all_and_unknown_status_are_400_json(self):
        self.seed_mixed_board()
        for query in ('status=', 'status=all', 'status=bogus',
                      'status=open&status=completed'):
            status, content_type, raw, body = self.call('GET', '/feedback?%s' % query)
            self.assertEqual(status, 400,
                             'the UI omits status for All; %r must be rejected' % query)
            self.assertTrue(content_type.lower().startswith('application/json'))
            self.assertIn('error', body)
            self.assertNotIn(b'items', raw)

    def test_summary_stays_whole_board_regardless_of_status(self):
        self.seed_mixed_board()
        _, _, _, base = self.call('GET', '/feedback/summary')
        self.assertEqual(base, {'total': 3, 'completed': 1, 'open': 2})
        for query in ('status=open', 'status=completed'):
            _, _, _, body = self.call('GET', '/feedback/summary?%s' % query)
            self.assertEqual(body, base,
                             'summary must stay whole-board for %r' % query)


# --- client harness: execute the real app.js under a Node vm Window ---------

NODE_HARNESS_TEMPLATE = r"""'use strict';
const vm = require('vm');
const fs = require('fs');

const SOURCE_PATH = %(source_path)s;
const SOURCE_NAME = %(source_filename)s;
const SOURCE = fs.readFileSync(SOURCE_PATH, 'utf8');

function makeElement(id, tagName) {
  const el = {
    id: id, tagName: tagName || 'div', children: [], _text: '', className: '',
    type: '', disabled: false, hidden: false, value: '', elements: {},
    attributes: {}, listeners: {},
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
    appendChild: function (child) { this.children.push(child); return child; },
    addEventListener: function (type, handler) {
      (this.listeners[type] = this.listeners[type] || []).push(handler);
    },
    setAttribute: function (name, value) { this.attributes[name] = String(value); },
    getAttribute: function (name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name)
        ? this.attributes[name] : null;
    },
    dispatchEvent: function (event) {
      const list = this.listeners[(event && event.type) || ''] || [];
      for (let i = 0; i < list.length; i += 1) { list[i](event); }
      return true;
    },
    querySelector: function (selector) {
      if (selector === 'button[type="submit"]' || selector === 'button[type=submit]' ||
          selector === 'button') { return button; }
      if (selector.charAt(0) === '#') { return byId[selector.slice(1)] || null; }
      return null;
    },
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

const byId = {};
['feedback-form', 'feedback-list', 'empty-state', 'form-status',
 'feedback-summary', 'summary-total', 'summary-open', 'summary-completed',
 'title', 'description'].forEach(function (id) { byId[id] = makeElement(id); });
byId['feedback-form'].elements.title = byId['title'];
byId['feedback-form'].elements.description = byId['description'];

const FILTER_IDS = ['filter-all', 'filter-open', 'filter-completed'];
const filterControls = {};
FILTER_IDS.forEach(function (id) {
  filterControls[id] = makeElement(id, 'button');
  filterControls[id].type = 'button';
});

const button = makeElement('submit-button', 'button');
button.type = 'submit';

const items = [];
let nextId = 1;

function summaryCounts() {
  const total = items.length;
  const completed = items.filter(function (it) { return it.completed; }).length;
  return { total: total, completed: completed, open: total - completed };
}

function jsonResponse(body, ok) {
  return {
    ok: (ok === undefined) ? true : ok,
    status: (ok === undefined || ok) ? 200 : 500,
    json: function () { return Promise.resolve(body); }
  };
}

const deferreds = {};
function makeDeferred(name) {
  const d = { promise: null, resolve: null, reject: null };
  d.promise = new Promise(function (resolve, reject) { d.resolve = resolve; d.reject = reject; });
  deferreds[name] = d;
  return d;
}

const calls = [];
const posts = [];
let postMode = 'defer';
let postDeferredName = 'post';

function filterFromUrl(target) {
  const query = String(target).split('?')[1] || '';
  const pairs = query.split('&');
  for (let i = 0; i < pairs.length; i += 1) {
    const bits = pairs[i].split('=');
    if (decodeURIComponent(bits[0]) === 'status') { return decodeURIComponent(bits[1] || ''); }
  }
  return null;
}

function rowsFor(wanted) {
  return items.filter(function (it) {
    return wanted === null ? true
         : wanted === 'open' ? it.completed !== true : it.completed === true;
  });
}

// A promise factory here answers the next board GET, injecting a stale
// response without committing invented backend state.
let heldBoardGet = null;

function defaultFetch(url, options) {
  const method = (options && options.method) || 'GET';
  const target = String(url);
  const isBoardGet = target.indexOf('/feedback') === 0 && method === 'GET' &&
                     target.indexOf('/feedback/summary') !== 0;
  const record = { url: target, method: String(method), status: filterFromUrl(target) };
  calls.push(record);
  if (isBoardGet) {
    if (heldBoardGet !== null) {
      const producer = heldBoardGet;
      heldBoardGet = null;
      return producer();
    }
    return Promise.resolve(jsonResponse({ items: rowsFor(filterFromUrl(target)).slice() }, true));
  }
  if (target === '/feedback' && method === 'POST') {
    let body = {};
    try { body = JSON.parse(options && options.body) || {}; } catch (error) { body = {}; }
    const p = { url: target, method: 'POST', body: body };
    posts.push(p);
    calls[calls.length - 1] = p;
    if (postMode === 'http-error') {
      return Promise.resolve(jsonResponse({ error: 'Unable to submit feedback.' }, false));
    }
    if (postMode === 'reject') { return Promise.reject(new Error('network down')); }
    if (postMode === 'ok') {
      const item = { id: nextId, title: body.title || 'Untitled', completed: false };
      nextId += 1; items.push(item);
      return Promise.resolve(jsonResponse(item, true));
    }
    // Defer: hold the request unresolved; a pending POST commits nothing.
    return makeDeferred(postDeferredName).promise;
  }
  if (target === '/feedback/summary') {
    return Promise.resolve(jsonResponse(summaryCounts(), true));
  }
  const complete = /^\/feedback\/(\d+)\/complete$/.exec(target);
  if (complete) {
    const id = Number(complete[1]);
    items.forEach(function (it) { if (it.id === id) { it.completed = true; } });
    return Promise.resolve(jsonResponse({ id: id, completed: true }, true));
  }
  return Promise.resolve(jsonResponse({}, true));
}

function controlRoot() {
  const containers = [byId['feedback-form'], byId['feedback-list'],
                      byId['feedback-summary'], byId['empty-state']];
  for (let i = 0; i < containers.length; i += 1) {
    if ((containers[i].listeners.click || []).length) { return containers[i]; }
  }
  return null;
}

function clickControl(id) {
  const control = filterControls[id];
  const result = { threw: null };
  const direct = control.listeners.click || [];
  try {
    if (direct.length) {
      for (let i = 0; i < direct.length; i += 1) {
        direct[i]({ type: 'click', target: control, currentTarget: control,
                    preventDefault: function () {} });
      }
    } else {
      const root = controlRoot();
      if (root) {
        root.dispatchEvent({ type: 'click', target: control, currentTarget: root,
                             preventDefault: function () {} });
      }
    }
  } catch (thrown) { result.threw = String((thrown && thrown.message) || thrown); }
  return result;
}

function hasControl() {
  return FILTER_IDS.some(function (id) {
    return (filterControls[id].listeners.click || []).length > 0;
  }) || controlRoot() !== null;
}

let intervalCallback = null;
let intervalDelay = null;

const target = {
  Boolean: Boolean, Promise: Promise, JSON: JSON, Math: Math, String: String,
  Number: Number, Array: Array, Object: Object, Error: Error, Date: Date,
  RegExp: RegExp, Set: Set, Map: Map, Symbol: Symbol,
  document: {
    getElementById: function (id) {
      if (byId[id]) { return byId[id]; }
      if (filterControls[id]) { return filterControls[id]; }
      return null;
    },
    createElement: function (tag) { return makeElement('<' + tag + '>', tag); },
    querySelector: function (selector) {
      if (selector.charAt(0) === '#') { return byId[selector.slice(1)] || null; }
      return null;
    },
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
    t[key] = (key === 'status') ? String(descriptor.value) : descriptor.value;
    return true;
  },
  getOwnPropertyDescriptor: function (t, key) {
    return Object.getOwnPropertyDescriptor(t, key);
  },
  deleteProperty: function (t, key) { delete t[key]; return true; },
  ownKeys: function (t) { return Reflect.ownKeys(t); }
});
target.window = sandbox;
target.self = sandbox;
target.globalThis = sandbox;
const context = vm.createContext(sandbox);

function report(payload) { process.stdout.write(JSON.stringify(payload)); }

function flush() {
  let chain = Promise.resolve();
  for (let i = 0; i < 12; i += 1) { chain = chain.then(function () { return undefined; }); }
  return chain;
}

function boardTitles() {
  return byId['feedback-list'].children.map(function (entry) {
    const kids = entry.children || [];
    const label = kids.filter(function (k) {
      return String(k.className).indexOf('feedback-title') !== -1;
    })[0];
    return label ? label.textContent : (kids[0] ? kids[0].textContent : '');
  });
}

function state() {
  return {
    status: byId['form-status'].textContent,
    is_error: byId['form-status'].classList.contains('is-error'),
    title: byId['title'].value,
    description: byId['description'].value,
    board_titles: boardTitles(),
    empty_text: byId['empty-state'].textContent,
    empty_hidden: byId['empty-state'].hidden === true,
    total: byId['summary-total'].textContent,
    open: byId['summary-open'].textContent,
    completed: byId['summary-completed'].textContent,
    button_disabled: button.disabled === true,
    aria_busy: byId['feedback-form'].getAttribute('aria-busy')
  };
}

function dispatchSubmit() {
  const result = { threw: null };
  try {
    byId['feedback-form'].dispatchEvent({
      type: 'submit', preventDefault: function () {}, target: byId['feedback-form'] });
  } catch (thrown) { result.threw = String((thrown && thrown.message) || thrown); }
  return result;
}

function dispatchKeydown(key) {
  const result = { threw: null };
  try {
    byId['feedback-form'].dispatchEvent({
      type: 'keydown', key: key, bubbles: true, target: byId['feedback-form'],
      preventDefault: function () {} });
  } catch (thrown) { result.threw = String((thrown && thrown.message) || thrown); }
  return result;
}

function fillForm(title, description) {
  byId['title'].value = title; byId['description'].value = description;
}

function completeOpenItem() {
  const result = { threw: null };
  try {
    const rendered = byId['feedback-list'].children;
    let toggle = null;
    for (let i = 0; i < rendered.length && toggle === null; i += 1) {
      const kids = rendered[i].children || [];
      for (let j = 0; j < kids.length; j += 1) {
        if (String(kids[j].className).indexOf('complete-button') !== -1 &&
            kids[j].disabled !== true) { toggle = kids[j]; break; }
      }
    }
    if (!toggle) { result.threw = 'no enabled complete button rendered'; return result; }
    const handlers = toggle.listeners.click || [];
    for (let i = 0; i < handlers.length; i += 1) {
      handlers[i]({ type: 'click', target: toggle, preventDefault: function () {} });
    }
  } catch (thrown) { result.threw = String((thrown && thrown.message) || thrown); }
  return result;
}

let executed = true;
let error = null;

(async function drive() {
  try {
    const script = new vm.Script(SOURCE, { filename: SOURCE_NAME });
    script.runInContext(context);
  } catch (thrown) { executed = false; error = String((thrown && thrown.message) || thrown); }
  if (!executed) { report({ executed: false, error: error }); return; }

  await flush();
  const initial_calls = calls.slice();

  postMode = 'ok';
  fillForm('Open one', 'd1'); dispatchSubmit(); await flush();
  fillForm('Open two', 'd2'); dispatchSubmit(); await flush();
  items.push({ id: nextId, title: 'Walrus done', completed: true }); nextId += 1;
  await flush();
  if (typeof intervalCallback === 'function') { intervalCallback(); }
  await flush();
  const seeded_summary = state();

  const filter_present = hasControl();
  const default_state = state();
  const default_filter_calls = calls.filter(function (c) {
    return c.method === 'GET' && c.status !== null;
  }).length;

  const before = calls.length;
  const open_click = clickControl('filter-open');
  await flush();
  const open_state = state();
  const open_calls = calls.slice(before).filter(function (c) { return c.method === 'GET'; });

  const before_completed = calls.length;
  const completed_click = clickControl('filter-completed');
  await flush();
  const completed_state = state();
  const completed_calls = calls.slice(before_completed).filter(function (c) {
    return c.method === 'GET';
  });

  const open_row = items.filter(function (it) { return !it.completed; })[0];
  const only_open_id = open_row ? open_row.id : null;
  items.forEach(function (it) { it.completed = true; });
  await flush();
  const empty_before = calls.length;
  clickControl('filter-open');
  await flush();
  const empty_state = state();
  const empty_calls = calls.slice(empty_before).filter(function (c) { return c.method === 'GET'; });
  items.forEach(function (it) { if (it.id === only_open_id) { it.completed = false; } });

  clickControl('filter-open');
  await flush();
  const before_stale = calls.length;
  heldBoardGet = function () { return makeDeferred('stale-poll').promise; };
  if (typeof intervalCallback === 'function') { intervalCallback(); }
  await flush();
  const during_stale = state();
  clickControl('filter-completed');
  await flush();
  const stale_poll_calls = calls.slice(before_stale).filter(function (c) {
    return c.method === 'GET';
  });
  if (deferreds['stale-poll'] && deferreds['stale-poll'].resolve) {
    deferreds['stale-poll'].resolve(jsonResponse(
      { items: [{ id: 999, title: 'STALE MARKER', completed: false }] }, true));
  }
  await flush();
  const after_stale = state();
  clickControl('filter-all'); await flush();

  fillForm('Draft title', 'draft description');
  clickControl('filter-completed'); await flush();
  clickControl('filter-all'); await flush();
  const draft_state = state();
  const draft_posts = posts.length;

  postMode = 'defer';
  postDeferredName = 'filter-pending';
  fillForm('Pending title', 'pending description');
  dispatchSubmit();
  await flush();
  const pending_before_switch = state();
  const before_switch_posts = posts.length;
  clickControl('filter-open'); await flush();
  clickControl('filter-completed'); await flush();
  const pending_after_switch = state();
  const after_switch_posts = posts.length;
  if (deferreds['filter-pending'] && deferreds['filter-pending'].resolve) {
    deferreds['filter-pending'].resolve(jsonResponse(
      { id: nextId, title: 'Pending title', completed: false }, true));
    nextId += 1;
    items.push({ id: nextId - 1, title: 'Pending title', completed: false });
  }
  await flush();

  const escape_result = dispatchKeydown('Escape');
  await flush();

  postMode = 'ok';
  clickControl('filter-completed'); await flush();
  const completed_view_state = state();
  fillForm('Finish me', ''); dispatchSubmit(); await flush();
  const complete_click = completeOpenItem();
  await flush();
  const after_complete_state = state();

  report({
    executed: true, error: null, filename: SOURCE_NAME,
    filter_present: filter_present, initial_calls: initial_calls,
    seeded_summary: seeded_summary, default_state: default_state,
    default_filter_calls: default_filter_calls,
    open_click: open_click, open_state: open_state, open_calls: open_calls,
    completed_click: completed_click, completed_state: completed_state,
    completed_calls: completed_calls, empty_state: empty_state, empty_calls: empty_calls,
    stale_poll_calls: stale_poll_calls, during_stale: during_stale,
    after_stale: after_stale, draft_state: draft_state, draft_posts: draft_posts,
    pending_before_switch: pending_before_switch,
    pending_after_switch: pending_after_switch,
    before_switch_posts: before_switch_posts, after_switch_posts: after_switch_posts,
    escape_result: escape_result, completed_view_state: completed_view_state,
    complete_click: complete_click, after_complete_state: after_complete_state,
    interval_delay: intervalDelay
  });
})().catch(function (thrown) {
  report({ executed: false, error: String((thrown && thrown.message) || thrown) });
});
"""


class ClientFilterHarnessCase(unittest.TestCase):
    """Run the real ``app.js`` once under the filter harness, expose its report."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')

    def setUp(self):
        self.assertTrue(APP_JS_PATH.is_file(),
                        'declared client asset must exist: %s' % APP_JS_PATH)
        self.source_filename = str(APP_JS_PATH)
        self.source_bytes = APP_JS_PATH.read_bytes()
        self.source_sha256 = hashlib.sha256(self.source_bytes).hexdigest()
        self.assertTrue(self.node, 'node executable is unavailable')
        program = NODE_HARNESS_TEMPLATE % {
            'source_path': json.dumps(self.source_filename),
            'source_filename': json.dumps(self.source_filename),
        }
        completed = subprocess.run(
            [self.node, '--input-type=commonjs', '-'],
            input=program.encode('utf-8'), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=NODE_TIMEOUT_SECONDS, check=False)
        self.assertEqual(
            completed.returncode, 0,
            'Node harness exited %d: %s' % (
                completed.returncode, completed.stderr.decode('utf-8', 'replace')))
        raw = completed.stdout.decode('utf-8', 'replace').strip()
        self.assertTrue(raw, 'Node harness produced no report')
        self.report = json.loads(raw)
        self.assertEqual(self.report.get('filename'), self.source_filename,
                         'the harness must record the declared source filename')
        if not self.report.get('executed'):
            self.fail('the real app.js did not run to completion: %s'
                      % self.report.get('error'))

    def statuses(self, calls):
        return [c['status'] for c in calls if c['method'] == 'GET']


class FilterControlPresenceTests(ClientFilterHarnessCase):
    """The board must offer a filter control a browser can address."""

    def test_real_client_executes_under_the_window(self):
        self.assertTrue(self.source_bytes.strip())
        self.assertRegex(self.source_sha256, r'^[0-9a-f]{64}$')

    def test_filter_controls_are_available(self):
        self.assertTrue(self.report['filter_present'],
                        'the client must bind an addressable filter control '
                        '(ids %r)' % list(FILTER_IDS))


class DefaultAndStateFilterTests(ClientFilterHarnessCase):
    """All is the default; Open/Completed show only that state."""

    def test_default_view_shows_every_item(self):
        titles = self.report['default_state']['board_titles']
        self.assertEqual(sorted(titles), sorted(['Open one', 'Open two', 'Walrus done']),
                         'the default (All) view must list every item, got %r' % titles)

    def test_default_view_does_not_send_a_status_parameter(self):
        self.assertEqual(self.report['default_filter_calls'], 0,
                         'the All view must omit the status parameter entirely')

    def test_open_filter_sends_status_open_and_shows_only_open(self):
        statuses = self.statuses(self.report['open_calls'])
        self.assertIn('open', statuses,
                      'selecting Open must request status=open, got %r' % statuses)
        titles = self.report['open_state']['board_titles']
        self.assertEqual(sorted(titles), sorted(['Open one', 'Open two']),
                         'Open must show only open items, got %r' % titles)
        self.assertNotIn('Walrus done', titles, 'Open must exclude completed items')

    def test_completed_filter_sends_status_completed_and_shows_only_completed(self):
        statuses = self.statuses(self.report['completed_calls'])
        self.assertIn('completed', statuses,
                      'selecting Completed must request status=completed, got %r' % statuses)
        titles = self.report['completed_state']['board_titles']
        self.assertEqual(titles, ['Walrus done'],
                         'Completed must show only completed items, got %r' % titles)

    def test_switching_does_not_throw(self):
        self.assertIsNone(self.report['open_click']['threw'])
        self.assertIsNone(self.report['completed_click']['threw'])


class EmptyFilterMessageTests(ClientFilterHarnessCase):
    """An empty filtered result shows a filter-specific message."""

    def test_empty_filter_requests_the_selected_state(self):
        statuses = self.statuses(self.report['empty_calls'])
        self.assertIn('open', statuses,
                      'the empty filtered load must still request the selected state')

    def test_empty_filter_message_is_visible_and_filter_specific(self):
        empty = self.report['empty_state']
        self.assertFalse(empty['empty_hidden'],
                         'an empty filtered result must reveal the empty message')
        self.assertEqual(empty['board_titles'], [], 'the filtered list must be empty')
        text = empty['empty_text'].lower()
        self.assertTrue(text.strip(), 'the empty message must not be blank')
        self.assertTrue(any(term in text for term in OPEN_TERMS),
                        'the empty message must name the Open filter, got %r'
                        % empty['empty_text'])
        self.assertNotIn('no feedback yet', text,
                         'the empty message must be filter-specific, not the generic text')


class PollingAndStaleResponseTests(ClientFilterHarnessCase):
    """The selected filter survives polling and stale responses are discarded."""

    def test_polling_keeps_requesting_the_selected_filter(self):
        statuses = self.statuses(self.report['stale_poll_calls'])
        self.assertIn('open', statuses,
                      'a poll tick under Open must request status=open, got %r' % statuses)

    def test_stale_poll_response_is_discarded(self):
        # A board GET issued under Open is left unresolved while the user
        # switches to Completed; resolving it delivers a marker body never part
        # of any filter. The client must discard it, so the marker never lands.
        after = self.report['after_stale']['board_titles']
        self.assertNotIn('STALE MARKER', after,
                         'a poll response whose filter no longer matches the '
                         'current filter must be discarded, not rendered')
        self.assertEqual(after, ['Open two', 'Walrus done'],
                         'the Completed view must show only live completed '
                         'items, got %r' % after)


class DraftAndInFlightTests(ClientFilterHarnessCase):
    """Filter switches keep a typed draft and do not disturb an in-flight POST."""

    def test_switching_filters_preserves_the_typed_draft(self):
        draft = self.report['draft_state']
        self.assertEqual(draft['title'], 'Draft title',
                         'a filter switch must not clear the typed title')
        self.assertEqual(draft['description'], 'draft description',
                         'a filter switch must not clear the typed description')

    def test_switching_filters_does_not_submit(self):
        self.assertEqual(self.report['draft_posts'], 2,
                         'filter switches must not issue a POST (only the two '
                         'seeding submissions may exist)')

    def test_switch_during_in_flight_submit_keeps_the_post_pending(self):
        before = self.report['pending_before_switch']
        after = self.report['pending_after_switch']
        self.assertTrue(before['button_disabled'],
                        'the submit button must be disabled while pending')
        self.assertEqual(before['status'], 'Submitting...',
                         'the pending window must show Submitting...')
        self.assertEqual(after['button_disabled'], before['button_disabled'],
                         'a filter switch must not re-enable the button mid-submit')
        self.assertEqual(after['status'], before['status'],
                         'a filter switch must not disturb the pending status')
        self.assertEqual(after['title'], before['title'],
                         'a filter switch must not clear the in-flight draft')

    def test_no_extra_post_from_switching(self):
        self.assertEqual(self.report['after_switch_posts'],
                         self.report['before_switch_posts'],
                         'filter switches must not issue an extra POST')
