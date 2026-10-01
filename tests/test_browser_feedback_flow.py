"""Test-first regression for the NEW Node VM browser flow (BROWSERFIX-2).

Phase 1 is tests only. This file is the corrected revision of the new Node VM
regression. It loads the *real* ``app/static/app.js`` from disk into a Node
``vm`` context whose global object is a faithful ``Window`` -- a proxy whose
``status`` write coerces with ``String(...)`` -- and proves the board client's
behaviour by the HTTP traffic it emits and the DOM text it writes, never by
matching source text.

Why the frozen base is Red, behaviourally. In a browser the global object is the
``Window`` and ``window.status`` is a native string property. ``app.js`` declares
``var status`` at top level for the ``#form-status`` element; under the native
Window contract that top-level binding is the window's own ``status`` property,
so storing the element there string-coerces it to ``"[object Object]"``. Every
later ``status.classList`` use inside ``setStatus`` then fails: the real submit
handler raises ``TypeError: Cannot read properties of undefined (reading
'toggle')`` and aborts before it can POST. That is the collision this issue is
named for. The Phase 2 fix moves the binding off the global object so the element
survives and the client runs; this suite pins the behaviour that proves it.

The harness runs the real application logic. It does not reimplement the client:
it records the ``fetch`` calls the real source issues -- including the ones its
own ``setInterval`` callback issues when the test invokes it to simulate an
external change -- and the text the real source writes through DOM stubs whose
``textContent``/``innerHTML`` setters coerce with ``String``. A regex over the
served script could never satisfy these assertions. The Node program is
generated from the declared template below and piped to ``node`` over stdin (no
temporary files are created); every run is bounded by a subprocess timeout and
settles its promises deterministically.

This is a Node harness, not real-browser acceptance: it executes the shipped
client and observes its contract, which is enough to catch a global-collision
regression without a browser.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = ROOT / 'app' / 'static' / 'app.js'

# Bounded execution: a hung script must fail loudly, never stall the suite.
NODE_TIMEOUT_SECONDS = 30

# The frozen client's execute-time work is top-level ``loadSummary()`` then
# ``loadFeedback()``: exactly two GETs before any interaction. Used to prove the
# real file actually executed rather than being short-circuited.
INITIAL_GETS = 2


# Node program. ``%(source_path)s`` / ``%(source_filename)s`` are filled from the
# path actually read; the bytes loaded are hashed in Python from that same path.
# Nothing here reimplements the client -- every recorded call and DOM write comes
# from running the real file.
NODE_HARNESS_TEMPLATE = r"""'use strict';
const vm = require('vm');
const fs = require('fs');

const SOURCE_PATH = %(source_path)s;
const SOURCE_NAME = %(source_filename)s;
const SOURCE = fs.readFileSync(SOURCE_PATH, 'utf8');

// --- DOM stub: textContent/innerHTML setters coerce exactly like the DOM ---
function makeElement(id, tagName) {
  const el = {
    id: id,
    tagName: tagName || 'div',
    children: [],
    _text: '',
    className: '',
    type: '',
    disabled: false,
    hidden: false,
    value: '',
    elements: {},
    attributes: {},
    listeners: {},
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
    removeEventListener: function (type, handler) {
      const list = this.listeners[type] || [];
      this.listeners[type] = list.filter(function (h) { return h !== handler; });
    },
    setAttribute: function (name, value) { this.attributes[name] = String(value); },
    getAttribute: function (name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name)
        ? this.attributes[name] : null;
    },
    querySelector: function (selector) {
      if (selector.charAt(0) === '#') { return byId[selector.slice(1)] || null; }
      return null;
    },
    reset: function () {
      Object.keys(this.elements).forEach(function (k) {
        this.elements[k].value = '';
      }, this);
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

// --- in-memory board behind the fetch contract ------------------------------
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

const calls = [];
function defaultFetch(url, options) {
  const method = (options && options.method) || 'GET';
  const target = String(url);
  calls.push({ url: target, method: String(method) });
  if (target === '/feedback' && method === 'GET') {
    return Promise.resolve(jsonResponse({ items: items.slice() }, true));
  }
  if (target === '/feedback' && method === 'POST') {
    let title = 'Untitled';
    try {
      const body = JSON.parse(options && options.body);
      title = (body && body.title) || title;
    } catch (error) { /* keep the default title */ }
    const item = { id: nextId, title: title, completed: false };
    nextId += 1;
    items.push(item);
    return Promise.resolve(jsonResponse(item, true));
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

// --- native Window global ----------------------------------------------------
// A browser's global object IS the Window, whose ``status`` property coerces
// its value with ``String``. The proxy below is passed to ``vm.createContext``
// so the real source's top-level ``var status = <element>`` binds through the
// coercing setter -- the collision -- instead of the private binding a bare
// ``vm`` context would silently create.
let intervalCallback = null;
let intervalDelay = null;

const target = {
  Boolean: Boolean, Promise: Promise, JSON: JSON, Math: Math, String: String,
  Number: Number, Array: Array, Object: Object, Error: Error, Date: Date,
  RegExp: RegExp, Set: Set, Map: Map, Symbol: Symbol,
  document: {
    getElementById: function (id) { return byId[id] || null; },
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

// Deterministic promise flushing between stages.
function flush() {
  return Promise.resolve()
    .then(function () { return undefined; })
    .then(function () { return undefined; })
    .then(function () { return undefined; })
    .then(function () { return undefined; })
    .then(function () { return undefined; })
    .then(function () { return undefined; })
    .then(function () { return undefined; })
    .then(function () { return undefined; })
    .then(function () { return undefined; })
    .then(function () { return undefined; });
}

function snapshot() {
  return {
    total: byId['summary-total'].textContent,
    open: byId['summary-open'].textContent,
    completed: byId['summary-completed'].textContent,
    status: byId['form-status'].textContent
  };
}

(async function drive() {
  let executed = true;
  let error = null;
  try {
    // The filename is passed explicitly; ``vm.Script`` exposes no ``filename``
    // property, so the test records the name supplied here instead.
    const script = new vm.Script(SOURCE, { filename: SOURCE_NAME });
    script.runInContext(context);
  } catch (thrown) {
    executed = false;
    error = String((thrown && thrown.message) || thrown);
  }

  // Stage 1: the real client's execute-time load (summary then board).
  await flush();
  const initialCalls = calls.slice();
  const initialRecords = snapshot();

  // Stage 2: a change made in another browser -- a single externally added open
  // item -- then the client's own captured poll callback is invoked and the
  // promises it starts are settled, so the board reflects the external change.
  items.push({ id: nextId, title: 'Externally added', completed: false });
  nextId += 1;
  const beforePoll = calls.length;
  if (typeof intervalCallback === 'function') { intervalCallback(); }
  await flush();
  const polledCalls = calls.slice(beforePoll);
  const pollRecords = snapshot();

  // Stage 3: drive the real form submit listener the client bound; this is the
  // client's own creation path (POST /feedback).
  const submitHandlers = byId['feedback-form'].listeners.submit || [];
  const beforeSubmit = calls.length;
  const submitErrors = [];
  if (submitHandlers.length) {
    byId['title'].value = 'Submitted from the form';
    byId['description'].value = 'details';
    try {
      submitHandlers[0]({ preventDefault: function () {} });
    } catch (thrown) {
      submitErrors.push(String((thrown && thrown.message) || thrown));
    }
    await flush();
  }
  const submitCalls = calls.slice(beforeSubmit);

  // Stage 4: drive a rendered item's completion toggle the client bound; this is
  // the client's own completion path (POST /feedback/<id>/complete). The first
  // enabled "Mark complete" button is used, so the completion is meaningful.
  const rendered = byId['feedback-list'].children;
  let toggle = null;
  for (let i = 0; i < rendered.length && toggle === null; i += 1) {
    const kids = rendered[i].children || [];
    for (let j = 0; j < kids.length; j += 1) {
      if (String(kids[j].className).indexOf('complete-button') !== -1 &&
          kids[j].disabled !== true) {
        toggle = kids[j];
        break;
      }
    }
  }
  const completeHandlers = toggle ? (toggle.listeners.click || []) : [];
  const beforeComplete = calls.length;
  const completeErrors = [];
  if (completeHandlers.length) {
    try {
      completeHandlers[0]({ preventDefault: function () {} });
    } catch (thrown) {
      completeErrors.push(String((thrown && thrown.message) || thrown));
    }
    await flush();
  }
  const completeCalls = calls.slice(beforeComplete);

  // Stage 5: the board after the client's own creation and completion, plus the
  // external open item: the summary must read total=2, open=1, completed=1.
  const finalRecords = snapshot();

  report({
    executed: executed,
    error: error,
    filename: SOURCE_NAME,
    calls: calls,
    initial_calls: initialCalls,
    initial_records: initialRecords,
    polled_calls: polledCalls,
    poll_records: pollRecords,
    submit_calls: submitCalls,
    submit_errors: submitErrors,
    complete_calls: completeCalls,
    complete_errors: completeErrors,
    final_records: finalRecords,
    listeners: {
      form_submit: submitHandlers.length,
      toggle_click: completeHandlers.length
    },
    interval_delay: intervalDelay
  });
})().catch(function (thrown) {
  report({ executed: false, error: String((thrown && thrown.message) || thrown) });
});
"""


class BrowserFeedbackFlowTests(unittest.TestCase):
    """The real ``app/static/app.js`` must run under a Node ``vm`` Window."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')

    def setUp(self):
        # Read the declared asset and hash the exact bytes that are loaded.
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
            input=program.encode('utf-8'),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=NODE_TIMEOUT_SECONDS,
            check=False,
        )
        self.assertEqual(
            completed.returncode, 0,
            'Node harness exited %d: %s' % (
                completed.returncode,
                completed.stderr.decode('utf-8', 'replace')))
        raw = completed.stdout.decode('utf-8', 'replace').strip()
        self.assertTrue(raw, 'Node harness produced no report')
        self.report = json.loads(raw)
        self.assertEqual(
            self.report.get('filename'), self.source_filename,
            'the harness must record the declared source filename')
        if not self.report.get('executed'):
            self.fail('the real app.js did not run to completion: %s'
                      % self.report.get('error'))
        self.calls = self.report['calls']
        self.initial_calls = self.report['initial_calls']
        self.polled_calls = self.report['polled_calls']
        self.poll_records = self.report['poll_records']
        self.final_records = self.report['final_records']
        self.submit_calls = self.report['submit_calls']
        self.complete_calls = self.report['complete_calls']
        self.listeners = self.report['listeners']

    def calls_of(self, calls, method, url):
        return [c for c in calls if c['method'] == method and c['url'] == url]

    # --- the five preserved regression methods ------------------------------

    def test_executes_the_real_app_js_in_a_node_vm(self):
        """The real app.js executes, bound to the declared path and its hash."""
        self.assertTrue(self.source_bytes.strip(),
                        'the real app.js must be non-empty')
        self.assertEqual(self.source_filename, str(APP_JS_PATH))
        self.assertRegex(self.source_sha256, r'^[0-9a-f]{64}$')
        # Real execution: the client's execute-time work issued its two GETs.
        self.assertEqual(len(self.initial_calls), INITIAL_GETS,
                         'the initial load must issue exactly two GETs, got %r'
                         % self.initial_calls)
        self.assertEqual(
            [c['url'] for c in self.initial_calls].count('/feedback'), 1,
            'the initial load must fetch the board once')
        self.assertEqual(
            [c['url'] for c in self.initial_calls].count('/feedback/summary'), 1,
            'the initial load must fetch the summary once')

    def test_submits_feedback_with_a_post_to_feedback(self):
        """Driving the bound submit listener must POST /feedback."""
        self.assertEqual(self.listeners['form_submit'], 1,
                         'the client must bind one submit listener to the form')
        self.assertEqual(
            self.report['submit_errors'], [],
            'the submit handler must run without throwing: %s'
            % self.report['submit_errors'])
        posts = self.calls_of(self.submit_calls, 'POST', '/feedback')
        self.assertTrue(
            posts, 'submitting must POST /feedback; recorded %r'
            % self.submit_calls)

    def test_requests_the_completion_api_for_an_item(self):
        """Completing a rendered item must POST /feedback/<id>/complete."""
        self.assertEqual(self.listeners['toggle_click'], 1,
                         'the rendered item must bind one completion toggle')
        self.assertEqual(
            self.report['complete_errors'], [],
            'the completion handler must run without throwing: %s'
            % self.report['complete_errors'])
        completes = [c for c in self.complete_calls
                     if c['method'] == 'POST' and c['url'].endswith('/complete')]
        self.assertTrue(
            completes, 'completion must POST /complete; recorded %r'
            % self.complete_calls)
        self.assertRegex(completes[0]['url'], r'^/feedback/\d+/complete$')

    def test_updates_the_summary_after_creation_and_completion(self):
        """Summary counts must obey total = open + completed after changes.

        After the client's own creation (submit) and completion (toggle) plus
        one externally added open item, the region must read total=2, open=1,
        completed=1.
        """
        records = self.final_records
        self.assertEqual(records['total'], '2')
        self.assertEqual(records['open'], '1')
        self.assertEqual(records['completed'], '1')
        total = int(records['total'])
        open_count = int(records['open'])
        completed = int(records['completed'])
        self.assertEqual(total, open_count + completed,
                         'summary must satisfy total = open + completed')
        self.assertEqual(
            self.calls_of(self.polled_calls, 'GET', '/feedback/summary')[0]['method'],
            'GET')

    def test_captures_polling_after_an_external_change(self):
        """Invoking the captured poll callback must re-read board and summary."""
        polled_urls = [c['url'] for c in self.polled_calls]
        self.assertTrue(polled_urls,
                        'the captured poll callback must issue requests')
        self.assertIn('/feedback', polled_urls)
        self.assertIn('/feedback/summary', polled_urls)
        self.assertIsInstance(self.report['interval_delay'], int,
                              'the client must register a numeric interval delay')
        self.assertGreater(self.report['interval_delay'], 0)
        # The poll must actually repaint the summary from the external change:
        # before it the region was empty, after it the externally added open item
        # is reflected, so total tracks the change rather than a static value.
        self.assertEqual(self.report['initial_records']['total'], '0')
        self.assertEqual(self.poll_records['total'], '1')
        self.assertEqual(self.poll_records['open'], '1')
        self.assertEqual(self.poll_records['completed'], '0')


if __name__ == '__main__':
    unittest.main()
