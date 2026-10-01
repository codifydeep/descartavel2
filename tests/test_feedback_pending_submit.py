"""Test-first regression for AUTOBROWSER-3: one POST per pending submission.

Phase 1 is tests only. These tests load the *real* ``app/static/app.js`` from
disk into a Node ``vm`` context whose global object is a faithful ``Window`` --
a proxy whose ``status`` write coerces with ``String(...)``, exactly as
``tests/test_browser_feedback_flow.py`` establishes -- and prove the board
client's duplicate-submission contract by the HTTP traffic it emits, never by
matching source text.

Why the frozen base is Red, behaviourally. The approved contract is: while a
valid submission POST is pending, the form's ``Submit feedback`` button is
disabled and further submit events (including programmatically dispatched form
events) are ignored, so exactly one POST is issued; the button is re-enabled
after success, HTTP failure or transport failure; and empty-title validation
must not lock the form. The frozen client binds one submit listener and always
fires a POST with no pending guard, so a second dispatched ``submit`` event
issues a second POST while the first is still unresolved. The Phase 2 fix adds
the pending guard and button state. Every assertion below pins that behaviour.

The harness runs the real application logic and does not reimplement the client.
The POST mock returns a promise the test controls, so the pending window is real
rather than a sleep. Only the successful response path mutates mocked stored
state; failed POSTs insert nothing. The Node program is generated from the
template below and piped to ``node`` over stdin (no temporary files), bounded by
a subprocess timeout, and every run flushes promises deterministically with no
sleeps, skips or swallowed exceptions.
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


# Node program. ``%(source_path)s`` / ``%(source_filename)s`` are filled from the
# path actually read; the bytes loaded are hashed in Python from that same path.
# The submit button is supplied as a real form element found through the form's
# own ``querySelector`` (so the mock resolves it the way a browser would), the
# POST promise is held unresolved via a deferred, and the same reusable harness
# drives every scenario. Nothing here reimplements the client.
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
    dispatchEvent: function (event) {
      const list = this.listeners[(event && event.type) || ''] || [];
      for (let i = 0; i < list.length; i += 1) { list[i](event); }
      return true;
    },
    querySelector: function (selector) {
      // resolve the real submit button the way the browser would, so the client
      // can disable it while the POST is pending.
      if (selector === 'button[type="submit"]' ||
          selector === 'button[type=submit]' ||
          selector === 'button') {
        return button;
      }
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

// The real submit control the form owns, found through the form's querySelector.
const button = makeElement('submit-button', 'button');
button.type = 'submit';

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

// A deferred whose promise the test resolves by name, so "pending" is a real
// unresolved promise rather than a sleep.
const deferreds = {};
function makeDeferred(name) {
  const d = { promise: null, resolve: null, reject: null };
  d.promise = new Promise(function (resolve, reject) {
    d.resolve = resolve; d.reject = reject;
  });
  deferreds[name] = d;
  return d;
}

const calls = [];
const posts = [];          // POST /feedback records with parsed body
let postMode = 'defer';    // 'defer' | 'ok' | 'http-error' | 'reject'

function defaultFetch(url, options) {
  const method = (options && options.method) || 'GET';
  const target = String(url);
  calls.push({ url: target, method: String(method) });
  if (target === '/feedback' && method === 'GET') {
    return Promise.resolve(jsonResponse({ items: items.slice() }, true));
  }
  if (target === '/feedback' && method === 'POST') {
    let body = {};
    try { body = JSON.parse(options && options.body) || {}; } catch (error) { body = {}; }
    // While deferring, record the request but touch no stored state: a pending
    // POST has not succeeded, so the board must stay unchanged.
    const record = { url: target, method: 'POST', body: body };
    calls[calls.length - 1] = record;
    posts.push(record);
    if (postMode === 'http-error') {
      return Promise.resolve(jsonResponse({ error: 'Unable to submit feedback.' }, false));
    }
    if (postMode === 'reject') {
      return Promise.reject(new Error('network down'));
    }
    if (postMode === 'ok') {
      const item = { id: nextId, title: body.title || 'Untitled', completed: false };
      nextId += 1;
      items.push(item);
      return Promise.resolve(jsonResponse(item, true));
    }
    // Defer: resolve through the deferred the driver controls. The stored item
    // is inserted only on the successful response path, inside ``settlePost``.
    return makeDeferred('post').promise;
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
// coercing setter instead of the private binding a bare ``vm`` context would
// silently create.
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

// Deterministic promise flushing -- a fixed chain of microtask turns.
function flush() {
  let chain = Promise.resolve();
  for (let i = 0; i < 12; i += 1) { chain = chain.then(function () { return undefined; }); }
  return chain;
}

function snapshot() {
  return {
    total: byId['summary-total'].textContent,
    open: byId['summary-open'].textContent,
    completed: byId['summary-completed'].textContent,
    status: byId['form-status'].textContent,
    status_count: byId['feedback-list'].children.length,
    button_disabled: button.disabled === true,
    button_present: button !== null
  };
}

// Dispatch a submit through the form's own event target, exactly as a browser
// would, rather than calling the listener directly.
function dispatchSubmit() {
  const result = { threw: null };
  try {
    byId['feedback-form'].dispatchEvent({
      type: 'submit',
      preventDefault: function () {},
      target: byId['feedback-form']
    });
  } catch (thrown) {
    result.threw = String((thrown && thrown.message) || thrown);
  }
  return result;
}

function fillForm(title, description) {
  byId['title'].value = title;
  byId['description'].value = description;
  return { title: byId['title'].value, description: byId['description'].value };
}

let executed = true;
let error = null;

(async function drive() {
  try {
    const script = new vm.Script(SOURCE, { filename: SOURCE_NAME });
    script.runInContext(context);
  } catch (thrown) {
    executed = false;
    error = String((thrown && thrown.message) || thrown);
  }

  if (!executed) { report({ executed: false, error: error }); return; }

  // Stage 0: settle the client's execute-time load (summary then board).
  await flush();
  const load_calls = calls.length;

  // Stage 1: pre-submit -- form filled, nothing submitted yet. Recorded as a
  // distinct observation before any submit event is dispatched.
  const filled = fillForm('First idea', 'details');
  const pre_submit = snapshot();
  const pre_submit_posts = posts.length;

  // Stage 2: first submit while the POST is deferred; the button must disable
  // and exactly one POST must be issued, held pending.
  const button_at_bind = button;
  const first = dispatchSubmit();
  await flush();
  const pending = snapshot();
  const after_first = { posts: posts.length, calls: calls.slice(load_calls) };

  // Stage 3: a second submit event while the first POST is still pending must be
  // ignored -- no second POST, the button stays disabled.
  const second = dispatchSubmit();
  await flush();
  const after_second = { posts: posts.length, calls: calls.slice(load_calls) };

  // Stage 4: resolve the pending POST as a success; the board must record one
  // item, clear the form, show the success message and re-enable the button.
  if (deferreds.post && deferreds.post.resolve) {
    deferreds.post.resolve(jsonResponse(
      { id: nextId, title: filled.title, completed: false }, true));
    nextId += 1;
    items.push({ id: nextId - 1, title: filled.title, completed: false });
  }
  await flush();
  const success = snapshot();
  const success_message = byId['form-status'].textContent;
  const success_polls = calls.slice(load_calls).filter(function (c) {
    return c.method === 'GET' && c.url === '/feedback';
  }).length;

  // Stage 5: a later valid resubmission must POST again. This one uses a
  // synchronous OK mock so it settles immediately.
  postMode = 'ok';
  fillForm('Second idea', 'again');
  const resubmit = dispatchSubmit();
  await flush();
  const after_resubmit = snapshot();
  const resubmit_posts = posts.length;

  // Stage 6: non-OK HTTP response must re-enable the button, show an error and
  // insert nothing into the board.
  postMode = 'http-error';
  fillForm('Bad idea', 'nope');
  const before_http = snapshot();
  const http_error_dispatch = dispatchSubmit();
  await flush();
  const after_http = snapshot();

  // Stage 7: rejected transport (network failure) must also unlock the form.
  postMode = 'reject';
  fillForm('Unlucky idea', 'oops');
  const reject_dispatch = dispatchSubmit();
  await flush();
  const after_reject = snapshot();

  // Stage 8: empty-title validation must not lock the form -- no POST, error
  // message, and the button must stay enabled so a valid retry can follow.
  postMode = 'ok';
  fillForm('', 'missing title');
  const empty_dispatch = dispatchSubmit();
  await flush();
  const after_empty = snapshot();

  report({
    executed: true,
    error: null,
    filename: SOURCE_NAME,
    button_present: button !== null,
    button_at_bind: button_at_bind !== null,
    initial_load_calls: load_calls,
    filled: filled,
    pre_submit_posts: pre_submit_posts,
    pre_submit: pre_submit,
    pending: pending,
    after_first: after_first,
    after_second: after_second,
    first_dispatch: first,
    second_dispatch: second,
    success: success,
    success_message: success_message,
    success_polls: success_polls,
    resubmitted_posts: resubmit_posts - after_second.posts,
    after_resubmit: after_resubmit,
    resubmit_dispatch: resubmit,
    http_error_dispatch: http_error_dispatch,
    before_http: before_http,
    after_http: after_http,
    reject_dispatch: reject_dispatch,
    after_reject: after_reject,
    empty_dispatch: empty_dispatch,
    after_empty: after_empty,
    interval_delay: intervalDelay
  });
})().catch(function (thrown) {
  report({ executed: false, error: String((thrown && thrown.message) || thrown) });
});
"""


class PendingSubmitHarnessCase(unittest.TestCase):
    """Shared harness: run the real ``app.js`` once and expose its report."""

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


class ArtifactTests(PendingSubmitHarnessCase):
    """The real client must execute under the Window and expose its form control."""

    def test_executes_the_real_app_js_in_a_node_vm(self):
        self.assertTrue(self.source_bytes.strip(),
                        'the real app.js must be non-empty')
        self.assertEqual(self.source_filename, str(APP_JS_PATH))
        self.assertRegex(self.source_sha256, r'^[0-9a-f]{64}$')
        # Real execution: the client's execute-time work issued its two GETs.
        self.assertEqual(self.report['initial_load_calls'], 2,
                         'the initial load must issue exactly two GETs')

    def test_form_exposes_a_submit_button_through_query_selector(self):
        self.assertTrue(self.report['button_present'],
                        'the form must expose a real submit button')
        self.assertTrue(self.report['button_at_bind'],
                        'the submit button must be resolvable by the client')


class PendingDuplicateSuppressionTests(PendingSubmitHarnessCase):
    """While a valid POST is pending: one POST, button disabled, extras ignored."""

    def test_pre_submit_state_is_distinct_from_pending_state(self):
        # Two distinct observations of the same run: the snapshot before any
        # submit and the snapshot while the POST is deferred.
        self.assertEqual(self.report['pre_submit_posts'], 0,
                         'no POST may be issued before the first submit')
        self.assertFalse(self.report['pre_submit']['button_disabled'],
                         'the button must be enabled before submitting')
        self.assertEqual(self.report['pre_submit']['status_count'], 0,
                         'the board is empty before the first submit')
        self.assertEqual(self.report['pre_submit']['status'], '',
                         'no status message before the first submit')
        # The pending observation is distinct: a submit is in flight with the
        # button disabled, which the pre-submit observation did not show.
        self.assertTrue(self.report['pending']['button_disabled'],
                        'the pending state must disable the button')
        self.assertNotEqual(self.report['pre_submit']['button_disabled'],
                            self.report['pending']['button_disabled'],
                            'pre-submit and pending button states must differ')

    def test_first_submit_issues_one_post_and_disables_the_button(self):
        self.assertEqual(self.report['after_first']['posts'], 1,
                         'the first submit must issue exactly one POST; '
                         'got %d' % self.report['after_first']['posts'])
        posts = [c for c in self.report['after_first']['calls']
                 if c['method'] == 'POST' and c['url'] == '/feedback']
        self.assertEqual(len(posts), 1,
                         'exactly one POST /feedback must be pending')
        self.assertTrue(self.report['pending']['button_disabled'],
                        'the Submit button must be disabled while the POST '
                        'is pending')

    def test_second_submit_event_while_pending_is_ignored(self):
        self.assertEqual(self.report['after_second']['posts'], 1,
                         'a second submit event while pending must not POST '
                         'again; got %d' % self.report['after_second']['posts'])
        posts = [c for c in self.report['after_second']['calls']
                 if c['method'] == 'POST' and c['url'] == '/feedback']
        self.assertEqual(len(posts), 1,
                         'exactly one POST /feedback total across two events')
        self.assertTrue(self.report['pending']['button_disabled'],
                        'the button must stay disabled after the extra event')
        self.assertIsNone(self.report['first_dispatch']['threw'])
        self.assertIsNone(self.report['second_dispatch']['threw'])

    def test_a_pending_post_does_not_yet_update_the_board(self):
        self.assertEqual(self.report['pending']['status_count'], 0,
                         'a pending POST must not insert a stored item')
        self.assertEqual(self.report['pending']['total'], '0',
                         'the summary must not count an unresolved POST')
        self.assertEqual(self.report['pending']['status'], 'Submitting...',
                         'the pending window must show the submitting message')


class SuccessUnlockTests(PendingSubmitHarnessCase):
    """Resolving the POST as a success must complete the flow and unlock."""

    def test_success_reenables_the_button(self):
        self.assertFalse(self.report['success']['button_disabled'],
                         'a successful POST must re-enable the Submit button')

    def test_success_records_one_item_and_clears_the_form(self):
        self.assertEqual(self.report['success']['status_count'], 1,
                         'a successful POST must insert exactly one item')
        self.assertEqual(self.report['success']['total'], '1',
                         'the summary must count the stored item')
        self.assertEqual(self.report['filled']['title'], 'First idea')
        self.assertEqual(self.report['success_message'],
                         'Thanks! Your feedback was added.',
                         'the success message must be preserved')

    def test_success_refreshes_the_board_from_the_api(self):
        self.assertGreaterEqual(
            self.report['success_polls'], 1,
            'a successful POST must refresh the board via GET /feedback')


class FailureAndValidationTests(PendingSubmitHarnessCase):
    """HTTP failure, transport failure and empty-title validation unlocked."""

    def test_later_valid_resubmission_posts_again(self):
        self.assertEqual(self.report['resubmitted_posts'], 1,
                         'a later valid resubmission must issue a new POST; '
                         'got %d' % self.report['resubmitted_posts'])
        self.assertFalse(self.report['after_resubmit']['button_disabled'],
                         'the button must be enabled again after resubmitting')
        self.assertEqual(self.report['after_resubmit']['status_count'], 2,
                         'the resubmission must add a second stored item')
        self.assertIsNone(self.report['resubmit_dispatch']['threw'])

    def test_non_ok_response_unlocks_and_reports_an_error(self):
        self.assertFalse(self.report['after_http']['button_disabled'],
                         'an HTTP failure must re-enable the Submit button')
        self.assertNotIn('Thanks',
                         self.report['after_http']['status'],
                         'an HTTP failure must not report success')
        self.assertTrue(self.report['after_http']['status'],
                        'an HTTP failure must surface a message')
        self.assertEqual(
            self.report['after_http']['status_count'],
            self.report['before_http']['status_count'],
            'a failed POST must not insert a stored item')
        self.assertIsNone(self.report['http_error_dispatch']['threw'])

    def test_rejected_fetch_unlocks_and_reports_an_error(self):
        self.assertFalse(self.report['after_reject']['button_disabled'],
                         'a rejected fetch must re-enable the Submit button')
        self.assertTrue(self.report['after_reject']['status'],
                        'a rejected fetch must surface a message')
        self.assertNotIn('Thanks',
                         self.report['after_reject']['status'],
                         'a rejected fetch must not report success')
        self.assertEqual(
            self.report['after_reject']['status_count'],
            self.report['after_resubmit']['status_count'],
            'a rejected fetch must not insert a stored item')
        self.assertIsNone(self.report['reject_dispatch']['threw'])

    def test_empty_title_validation_does_not_lock_the_form(self):
        self.assertFalse(self.report['after_empty']['button_disabled'],
                         'empty-title validation must not lock the form')
        self.assertTrue(self.report['after_empty']['status'],
                        'empty-title validation must surface a message')
        self.assertNotIn('Thanks', self.report['after_empty']['status'])
        self.assertIsNone(self.report['empty_dispatch']['threw'])

    def test_polling_interval_is_preserved(self):
        self.assertIsInstance(self.report['interval_delay'], int)
        self.assertGreater(self.report['interval_delay'], 0)


if __name__ == '__main__':
    unittest.main()
