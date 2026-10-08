"""C2 acceptance: demo-environment indicator fed by one /service-mode request.

Behavioral harnesses, not source-text substrings. ServiceModeEndpointTests
# drives the real app.server.Handler over a local ephemeral socket and asserts
# the exact status, content type and body. ServiceModeClientTests executes the
# real app.js inside a Node vm context with a DOM/fetch double and asserts the
# probe contract end to end: one request per load, no probe timers, the exact
# text transition, the strict allow-list, and non-interference with the form,
# draft, search, filter and sort state.
#
# The double is deterministic: deferred promises settle under explicit flush
# chains (no sleeps) and no exception is swallowed.
"""
from __future__ import annotations

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

from app.server import Handler  # noqa: E402  (path bootstrap must precede)

APP_JS_PATH = ROOT / 'app' / 'static' / 'app.js'
INDEX_HTML = ROOT / 'app' / 'static' / 'index.html'
STYLE_CSS = ROOT / 'app' / 'static' / 'style.css'
NODE_TIMEOUT_SECONDS = 30

CHECKING = 'Checking environment\u2026'
DEMO = 'Demo environment'
UNAVAILABLE = 'Environment unavailable'
MODE_ID = 'service-mode'
MODE_PATH = '/service-mode'


def _read(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return handle.read()


class _QuietHandler(Handler):
    """Real handler with logging silenced."""

    def log_message(self, *args):
        pass


# --------------------------------------------------------------------------- #
# C1-side: the endpoint must serve exactly the demo payload over a real socket.
# --------------------------------------------------------------------------- #
class ServiceModeEndpointTests(unittest.TestCase):
    """GET /service-mode returns exactly 200 application/json {"mode":"demo"}."""

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

    def get(self, path):
        request = Request('http://127.0.0.1:%d%s' % (self.port, path), method='GET')
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.headers['Content-Type'], response.read()
        except HTTPError as error:
            return error.code, error.headers['Content-Type'], error.read()

    def test_exact_status_content_type_and_body(self):
        status, ctype, body = self.get(MODE_PATH)
        self.assertEqual(status, 200)
        self.assertEqual(ctype, 'application/json; charset=utf-8')
        self.assertEqual(body, b'{"mode":"demo"}')
        decoded = json.loads(body.decode('utf-8'))
        self.assertEqual(set(decoded), {'mode'}, 'own-key set must be exactly {mode}')
        self.assertEqual(decoded['mode'], 'demo')

    def test_probe_variant_is_byte_identical(self):
        self.assertEqual(self.get(MODE_PATH + '?probe=1'), self.get(MODE_PATH))


# --------------------------------------------------------------------------- #
# C2-side: the client must issue one request and render the exact terminal text.
# --------------------------------------------------------------------------- #
NODE_HARNESS_TEMPLATE = r'''
'use strict';
const vm = require('vm');
const fs = require('fs');
const SOURCE_PATH = %(source_path)s;
const SOURCE_NAME = %(source_filename)s;
const SOURCE = fs.readFileSync(SOURCE_PATH, 'utf8');

// Indicator-write instrumentation. Declared before makeElement because the
// property setters close over these bindings and run during initial DOM
// construction. probeObserving gates recording so only candidate-callback
// classification (readsProbe) captures writes; equal-value writes count.
let probeObserving = false;
const indicatorWrites = [];

function makeElement(id, tagName) {
  const el = {
    id: id, tagName: tagName || 'div', children: [], _text: '', className: '',
    type: '', disabled: false, hidden: false, value: '', elements: {},
    attributes: {}, listeners: {}, options: [],
    classList: {
      _set: new Set(),
      add: function (c) { this._set.add(c); },
      remove: function (c) { this._set.delete(c); },
      toggle: function (c, on) { const force = (on === undefined) ? !this._set.has(c) : Boolean(on);
        if (force) { this._set.add(c); } else { this._set.delete(c); } return force; },
      contains: function (c) { return this._set.has(c); }
    },
    appendChild: function (child) { this.children.push(child); return child; },
    addEventListener: function (type, handler) {
      (this.listeners[type] = this.listeners[type] || []).push(handler);
    },
    dispatchEvent: function (event) { const list = this.listeners[(event && event.type) || ''] || [];
      for (let i = 0; i < list.length; i += 1) { list[i](event); } return true; },
    setAttribute: function (name, value) { this.attributes[name] = String(value); },
    getAttribute: function (name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
    },
    querySelector: function (selector) {
      if (selector === 'button[type="submit"]' || selector === 'button[type=submit]' || selector === 'button') { return button; }
      if (selector.charAt(0) === '#') { return byId[selector.slice(1)] || null; }
      return null;
    },
    reset: function () {
      Object.keys(this.elements).forEach(function (k) { this.elements[k].value = ''; }, this); }
  };
  Object.defineProperty(el, 'textContent', {
    get: function () { return this._text; },
    set: function (v) { this._text = String(v); if (probeObserving) { indicatorWrites.push({ id: id, prop: 'textContent', value: this._text }); } }
  });
  Object.defineProperty(el, 'innerHTML', {
    get: function () { return this._text; },
    set: function (v) { this._text = String(v); this.children = []; if (probeObserving) { indicatorWrites.push({ id: id, prop: 'innerHTML', value: this._text }); } }
  });
  return el; }

const CHECKING_TEXT = 'Checking environment\u2026';
const byId = {};
['feedback-form', 'feedback-list', 'empty-state', 'form-status', 'feedback-summary',
 'summary-total', 'summary-open', 'summary-completed', 'title', 'description',
 'service-status', 'service-mode']
  .forEach(function (id) { byId[id] = makeElement(id); });
byId['feedback-form'].elements.title = byId['title'];
byId['feedback-form'].elements.description = byId['description'];
byId['service-status'].textContent = 'Checking service\u2026';
byId['service-status'].setAttribute('role', 'status');
byId['service-status'].setAttribute('aria-live', 'polite');
byId['service-mode'].textContent = CHECKING_TEXT;
byId['service-mode'].setAttribute('role', 'status');
byId['service-mode'].setAttribute('aria-live', 'polite');

const filterRoot = makeElement('feedback-filter');
const filterControls = {};
['filter-all', 'filter-open', 'filter-completed'].forEach(function (id) { filterControls[id] = makeElement(id, 'button'); });
byId['feedback-filter'] = filterRoot;

const button = makeElement('submit-button', 'button');
button.type = 'submit';

const searchInput = makeElement('feedback-search', 'input');
byId['feedback-search'] = searchInput;

const sortSelect = makeElement('sort-feedback', 'select');
sortSelect.setAttribute('aria-label', 'Sort feedback');
sortSelect.options.push(Object.assign(makeElement('', 'option'), { value: 'newest-first' }));
sortSelect.options.push(Object.assign(makeElement('', 'option'), { value: 'oldest-first' }));
sortSelect.value = 'newest-first';
byId['sort-feedback'] = sortSelect;

const items = [
  { id: 3, title: 'III open', completed: false },
  { id: 1, title: 'Alpha old', completed: true }];
function summaryCounts() { const total = items.length;
  const completed = items.filter(function (it) { return it.completed; }).length;
  return { total: total, completed: completed, open: total - completed }; }

function jsonResponse(body, ok) {
  return {
    ok: (ok === undefined) ? true : ok,
    status: (ok === undefined || ok) ? 200 : 500,
    json: function () { return Promise.resolve(body); }
  }; }
function textResponse(raw, ok) {
  return {
    ok: (ok === undefined) ? true : ok,
    status: (ok === undefined || ok) ? 200 : 500,
    json: function () { return Promise.reject(new SyntaxError('malformed JSON')); }
  }; }

// Every request the script makes is recorded here, in order.
const calls = [];

// serviceModeOutcome selects how /service-mode resolves. 'defer' hands back a
// promise the driver resolves later (used to observe the checking state).
let serviceModeOutcome = 'ok';
const deferreds = {};
function makeDeferred(name) { const d = { promise: null, resolve: null, reject: null };
  d.promise = new Promise(function (res, rej) { d.resolve = res; d.reject = rej; });
  deferreds[name] = d; return d; }

function serviceModeResponse() {
  if (serviceModeOutcome === 'ok') { return Promise.resolve(jsonResponse({ mode: 'demo' }, true)); }
  if (serviceModeOutcome === 'extra') { return Promise.resolve(jsonResponse({ mode: 'demo', extra: 1 }, true)); }
  if (serviceModeOutcome === 'other') { return Promise.resolve(jsonResponse({ mode: 'staging' }, true)); }
  if (serviceModeOutcome === 'empty') { return Promise.resolve(jsonResponse({}, true)); }
  if (serviceModeOutcome === 'non200') { return Promise.resolve(jsonResponse({ mode: 'demo' }, false)); }
  if (serviceModeOutcome === 'malformed') { return Promise.resolve(textResponse('{', true)); }
  if (serviceModeOutcome === 'network') { return Promise.reject(new Error('network down')); }
  if (serviceModeOutcome === 'defer') { return makeDeferred('service-mode').promise; }
  return Promise.reject(new Error('unknown outcome ' + serviceModeOutcome)); }

function defaultFetch(url, options) { const method = (options && options.method) || 'GET';
  const target = String(url);
  const record = { url: target, method: String(method) };
  calls.push(record);
  if (target.indexOf('/service-mode') === 0 && method === 'GET') { return serviceModeResponse(); }
  if (target.indexOf('/service-status') === 0 && method === 'GET') { return Promise.resolve(jsonResponse({ status: 'available' }, true)); }
  if (target === '/feedback/summary') { return Promise.resolve(jsonResponse(summaryCounts(), true)); }
  if (target.indexOf('/feedback') === 0 && method === 'GET') { return Promise.resolve(jsonResponse({ items: items.slice() }, true)); }
  if (target === '/feedback' && method === 'POST') {
    let body = {};
    try { body = JSON.parse(options && options.body) || {}; } catch (error) { body = {}; }
    const item = { id: 99, title: body.title || 'Untitled', completed: false };
    items.push(item);
    return Promise.resolve(jsonResponse(item, true)); }
  const complete = /^\/feedback\/(\d+)\/complete$/.exec(target);
  if (complete) { const id = Number(complete[1]);
    items.forEach(function (it) { if (it.id === id) { it.completed = true; } });
    return Promise.resolve(jsonResponse({ id: id, completed: true }, true)); }
  return Promise.resolve(jsonResponse({}, true)); }

const BASELINE_LID = 0;
const timeouts = [];
const intervals = [];
// The numeric id of the page load currently being evaluated, captured at
// script evaluation so every timer is tagged with the load that armed it.
let currentLid = BASELINE_LID;
let sliceTimeoutStart = 0;
let sliceIntervalStart = 0;

function runTimerCallback(timer) {
  const fn = timer.fn;
  timer.fn = null;
  if (typeof fn === 'function') { fn.apply(null, []); }
}
// Probe attribution is behavioral, never textual. A timer is probe-related iff
// its callback - run once, in isolation - either fetches /service-mode or
// writes the #service-mode indicator (textContent/innerHTML, equal-value
// included). The board poll (2000ms: /feedback + /feedback/summary) and the
// 200ms search debounce (/feedback) do neither, so they classify as legitimate
// board traffic even though the harness arms them globally. Candidate callbacks
// run during classification; their requests stay in `calls` so an accidental
// probe request is counted, and re-armed timers keep the load id that armed
// them.
function readsProbe(timer) {
  if (!timer || typeof timer.fn !== 'function') { return false; }
  const start = calls.length;
  const writesStart = indicatorWrites.length;
  const priorObserving = probeObserving;
  probeObserving = true;
  try {
    timer.fn.apply(null, []);
  } catch (thrown) {
    // A classification throw must not abort the driver; its fetches persist.
  }
  probeObserving = priorObserving;
  for (let i = start; i < calls.length; i += 1) {
    if (calls[i].url.indexOf('/service-mode') === 0) { return true; }
  }
  return indicatorWrites.length > writesStart;
}
// Only the current load's probe timers ever run; each runs once (a re-armed
// callback is a fresh timer bounded by MAX_TIMER_TURNS), so a retrying probe is
// caught without an endless drain. Board poll/debounce timers are never fired:
// the probe's exactly-one-request contract is measured at load time.
const MAX_TIMER_TURNS = 128;
function probeTimersDrained() {
  for (let turn = 0; turn < MAX_TIMER_TURNS; turn += 1) {
    const list = timeouts.concat(intervals);
    let ran = false;
    for (let i = 0; i < list.length; i += 1) {
      const timer = list[i];
      if (timer.load_id !== currentLid || timer.fn === null) { continue; }
      if (!readsProbe(timer)) { continue; }
      runTimerCallback(timer);
      ran = true;
      break;
    }
    if (!ran) { return true; }
  }
  return false;
}
function recordTimeout(fn, ms) { timeouts.push({ fn: fn, ms: ms, load_id: currentLid });
  return timeouts.length; }
function recordInterval(fn, ms) { intervals.push({ fn: fn, ms: ms, load_id: currentLid });
  return intervals.length; }

// Probe timer counts (current load, current slice) via behavioral attribution.
function probeTimeoutCount() {
  return timeouts.filter(function (t, i) {
    return t.load_id === currentLid && i >= sliceTimeoutStart && readsProbe(t); }).length;
}
function probeIntervalCount() {
  return intervals.filter(function (t, i) {
    return t.load_id === currentLid && i >= sliceIntervalStart && readsProbe(t); }).length;
}

// Each page load's own sandbox object, for the accidental-globals snapshot.
const sandboxLog = [];
// Provided globals; any other own string key was written undeclared.
const GLOBAL_NAMES = ['Boolean', 'Promise', 'JSON', 'String', 'Array', 'Object',
  'Error', 'Number', 'Math', 'document', 'fetch', 'setTimeout', 'clearTimeout',
  'setInterval', 'clearInterval', 'console', 'window', 'self', 'globalThis'];
const implicitGlobals = [];

// vm ties top-level `let`/`const` to the sandbox, so reusing a context would
// replay app.js's `let status` and throw a harness artifact; each load gets its
// own sandbox, sharing only the DOM/fetch doubles: a fresh browser context.
function makeSandbox() {
  const target = {
    Boolean: Boolean, Promise: Promise, JSON: JSON, String: String,
    Array: Array, Object: Object, Error: Error, Number: Number, Math: Math,
    document: {
      getElementById: function (id) { return byId[id] || filterControls[id] || null; },
      createElement: function (tag) { return makeElement('<' + tag + '>', tag); },
      querySelector: function (s) { return s.charAt(0) === '#' ? (byId[s.slice(1)] || null) : null; },
      addEventListener: function () {} },
    fetch: defaultFetch,
    setTimeout: function (fn, ms) {
      return recordTimeout(fn, ms);
    },
    clearTimeout: function () {},
    setInterval: function (fn, ms) {
      return recordInterval(fn, ms);
    },
    clearInterval: function () {},
    console: { log: function () {}, error: function () {}, warn: function () {} }
  };
  const sandbox = new Proxy(target, {
    set: function (t, k, v) { t[k] = (k === 'status') ? String(v) : v; return true; },
    get: function (t, k) { return t[k]; },
    has: function (t, k) { return k in t; },
    defineProperty: function (t, k, d) { t[k] = (k === 'status') ? String(d.value) : d.value; return true; },
    getOwnPropertyDescriptor: function (t, k) { return Object.getOwnPropertyDescriptor(t, k); },
    deleteProperty: function (t, k) { delete t[k]; return true; },
    ownKeys: function (t) { return Reflect.ownKeys(t); }
  });
  target.window = sandbox;
  target.self = sandbox;
  target.globalThis = sandbox;
  sandboxLog.push(target);
  return sandbox;
}

function report(payload) { process.stdout.write(JSON.stringify(payload)); }

// Deterministic settle: enough microtask turns to drain the fetch chain.
function flush() { let chain = Promise.resolve();
  for (let i = 0; i < 16; i += 1) { chain = chain.then(function () { return undefined; }); }
  return chain; }
function modeCalls() { return calls.filter(function (c) { return c.url.indexOf('/service-mode') === 0; }); }
function modeText() { return byId['service-mode'].textContent; }
function indicator() { const el = byId['service-mode'];
  return { text: el.textContent, role: el.getAttribute('role'),
           aria_live: el.getAttribute('aria-live') }; }
function formState() { return {
  title: byId['title'].value, description: byId['description'].value,
  button_disabled: button.disabled === true, aria_busy: byId['feedback-form'].getAttribute('aria-busy'),
  status_text: byId['form-status'].textContent };
}
// Cross-load, cross-case observation of the original service-status literal.
let serviceStatusFinal = null;

// Names the script assigns without declaring: each case runs in a fresh
// tolerant vm context, so a bare assignment lands on the sandbox; recording it
// lets a consumer tell "never ran" from "ran but wrote an undeclared binding".
function snapshotAccidentalGlobals() {
  sandboxLog.forEach(function (target) {
    Reflect.ownKeys(target).forEach(function (key) {
      if (typeof key === 'string' && GLOBAL_NAMES.indexOf(key) === -1 &&
          implicitGlobals.indexOf(key) === -1) {
        implicitGlobals.push(key);
      }
    });
  });
}

// Read the service-availability region right after the first load.
function captureServiceStatus() { serviceStatusFinal = byId['service-status'].textContent; }

function filterState() { return {
  all: filterControls['filter-all'].getAttribute('aria-pressed'),
  open: filterControls['filter-open'].getAttribute('aria-pressed'),
  completed: filterControls['filter-completed'].getAttribute('aria-pressed') }; }
function sortState() { return { value: sortSelect.value }; }
function searchState() { return { value: searchInput.value, listeners: (searchInput.listeners.input || []).length }; }
function serviceStatusText() { return byId['service-status'].textContent; }

// Reset the doubles to a pristine page-load state (indicator and availability
// at their shipped texts; drafts, search, filters, sort cleared) so a load
// never inherits state from the case that ran before it.
function resetDom() {
  const mode = byId['service-mode'];
  mode.textContent = CHECKING_TEXT
  mode.attributes = {};
  mode.setAttribute('role', 'status');
  mode.setAttribute('aria-live', 'polite');
  const avail = byId['service-status'];
  avail.textContent = 'Checking service\u2026';
  avail.attributes = {};
  avail.setAttribute('role', 'status');
  avail.setAttribute('aria-live', 'polite');
  byId['title'].value = '';
  byId['description'].value = '';
  byId['form-status'].textContent = '';
  searchInput.value = '';
  sortSelect.value = 'newest-first';
  Object.keys(filterControls).forEach(function (id) {
    filterControls[id].setAttribute('aria-pressed', id === 'filter-all' ? 'true' : 'false');
  });
}

// A fresh vm context per load reproduces an independent page load exactly; its
// own `calls` slice is what the exactly-one-request assertion measures.
function freshContext() {
  return vm.createContext(makeSandbox());
}
function loadOnce() {
  const context = freshContext();
  const script = new vm.Script(SOURCE, { filename: SOURCE_NAME });
  // Bind this load's own numeric id and slice origin BEFORE evaluation, so
  // every timer the load arms is tagged with its load id; the board's shared
  // request log can never leak a stale epoch into the slice.
  currentLid += 1;
  loadSliceBase = { calls: calls.length, mode: modeCalls().length };
  sliceTimeoutStart = timeouts.length;
  sliceIntervalStart = intervals.length;
  script.runInContext(context);
}

// `calls` accumulates across loads, so a per-load count uses this baseline;
// the mode baseline counts only GET /service-mode, so the exactly-one assertion
// measures the probe alone, never the board's own requests.
let loadSliceBase = { calls: 0, mode: 0 };
let initialLoadCalls = 0;
function loadCallsSince() { return calls.length - loadSliceBase.calls; }
function modeCallsSince() { return modeCalls().length - loadSliceBase.mode; }

// Run the load again with a fresh outcome; timer counts are read while the
// load's id is current, so an earlier load's board poll cannot be attributed.
async function runOnce() {
  resetDom();
  loadOnce();
  await flush();
  probeTimersDrained();
  return { issued: modeCallsSince(),
           probe_timeouts: probeTimeoutCount(),
           probe_intervals: probeIntervalCount(),
           text: modeText() };
}

(async function drive() {
  try {
    // Initial load: the demo object -> terminal 'Demo environment'. Records this
    // slice's issued-call count; the checking text is observed on the deferred
    // pass below, never here.
    serviceModeOutcome = 'ok';
    resetDom();
    loadOnce();
    await flush();
    const after_ok_calls = modeCallsSince();
    initialLoadCalls = after_ok_calls;
    // Freshly read after settlement, never copied from a pending value.
    const after_ok = { text: modeText(), calls: after_ok_calls };
    captureServiceStatus();
    const indicator_snapshot = indicator();

    const timers_after_load = { probe_timeout_count: 0, probe_interval_count: 0 };
    timers_after_load.probe_timeout_count = probeTimeoutCount();
    timers_after_load.probe_interval_count = probeIntervalCount();
    probeTimersDrained();

    // --- Case B: HTTP 200 with an extra own key -> unavailable. -------------
    serviceModeOutcome = 'extra';
    await runOnce();
    const after_extra = modeText();

    // --- Case C: HTTP 200 with another valid mode -> unavailable. -----------
    serviceModeOutcome = 'other';
    await runOnce();
    const after_other = modeText();

    // --- Case D: HTTP 200 with no mode key -> unavailable. ------------------
    serviceModeOutcome = 'empty';
    await runOnce();
    const after_empty = modeText();

    // --- Case E: non-200 response -> unavailable. ---------------------------
    serviceModeOutcome = 'non200';
    await runOnce();
    const after_non200 = modeText();

    // --- Case F: malformed JSON -> unavailable. -----------------------------
    serviceModeOutcome = 'malformed';
    await runOnce();
    const after_malformed = modeText();

    // --- Case G: transport failure -> unavailable. --------------------------
    serviceModeOutcome = 'network';
    await runOnce();
    const after_network = modeText();

    // --- Case H: deferred probe shows checking, then settles terminal. ------
    // The double hands back an unresolved promise, so the driver reads the text
    // and probe count after loadOnce(), before resolving; after_deferred is
    // freshly read after settlement.
    serviceModeOutcome = 'defer';
    resetDom();
    loadOnce();
    const pending_observed = { text: modeText(), calls: modeCallsSince() };
    const pending_issued = modeCallsSince();
    const pending_deferred = deferreds['service-mode'];
    if (pending_deferred) { pending_deferred.resolve(jsonResponse({ mode: 'demo' }, true)); }
    await flush();
    probeTimersDrained();
    const after_deferred = modeText();
    const pending_probe_timeouts = probeTimeoutCount();
    const pending_probe_intervals = probeIntervalCount();

    // --- Non-interference: the probe must not disturb the feedback form,
    //     its draft, the search, filter or sort state. -----------------------
    serviceModeOutcome = 'ok';
    resetDom();
    loadOnce();
    await flush();
    const form = formState();
    const search = searchState();
    const filter = filterState();
    const sort = sortState();
    const noninterference = {
      button_disabled: form.button_disabled,
      aria_busy: form.aria_busy === 'true',
      title_draft: form.title,
      description_draft: form.description,
      search_value: search.value,
      filter_all: filter.all,
      filter_open: filter.open,
      filter_completed: filter.completed,
      sort_value: sort.value
    };

    snapshotAccidentalGlobals();

    report({ executed: true, error: null, filename: SOURCE_NAME,
      indicator: indicator_snapshot,
      after_ok: after_ok, after_extra: after_extra, after_other: after_other,
      after_empty: after_empty, after_non200: after_non200,
      after_malformed: after_malformed, after_network: after_network,
      pending_observed: pending_observed, pending_issued: pending_issued,
      after_deferred: after_deferred,
      timer_count: timers_after_load.probe_timeout_count,
      interval_count: timers_after_load.probe_interval_count,
      pending_timer_count: pending_probe_timeouts,
      pending_interval_count: pending_probe_intervals,
      service_status_text: serviceStatusFinal,
      mode_request_total: modeCalls().length,
      implicit_globals: implicitGlobals,
      noninterference: noninterference });
  } catch (thrown) {
    report({ executed: false, error: String((thrown && thrown.message) || thrown) });
  }
})();

'''


class ServiceModeClientTests(unittest.TestCase):
    """Execute the real ``app.js`` under a counting DOM/fetch double."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        assert cls.node, 'node is required for the behavioral client harness'

    def setUp(self):
        self.assertTrue(APP_JS_PATH.is_file(), 'asset missing: %s' % APP_JS_PATH)
        program = NODE_HARNESS_TEMPLATE % {
            'source_path': json.dumps(str(APP_JS_PATH)),
            'source_filename': json.dumps(str(APP_JS_PATH)),
        }
        completed = subprocess.run(
            [self.node, '--input-type=commonjs', '-'],
            input=program.encode('utf-8'), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=NODE_TIMEOUT_SECONDS, check=False)
        self.assertEqual(completed.returncode, 0,
                         'node exit %d: %s' % (completed.returncode,
                                               completed.stderr.decode('utf-8', 'replace')))
        raw = completed.stdout.decode('utf-8', 'replace').strip()
        self.assertTrue(raw, 'no report')
        self.report = json.loads(raw)
        if not self.report.get('executed'):
            self.fail('app.js failed: %s' % self.report.get('error'))

    def test_client_requests_service_mode_once_at_load(self):
        self.assertEqual(self.report['after_ok']['calls'], 1,
                         'one /service-mode request per load, got %r'
                         % self.report['after_ok']['calls'])

    def test_indicator_is_accessible_role_status_element(self):
        self.assertEqual(self.report['indicator']['role'], 'status')

    def test_exact_demo_object_yields_demo_environment(self):
        self.assertEqual(self.report['after_ok']['text'], DEMO)

    def test_indicator_text_constants_are_exact(self):
        # The three literals are exact: the initial state uses a Unicode
        # ellipsis (\u2026), never three ASCII dots, and the terminal states are
        # byte-exact. The harness observed the real DOM text in each state.
        self.assertEqual(CHECKING, 'Checking environment\u2026')
        self.assertEqual(CHECKING.count('\u2026'), 1)
        self.assertNotIn('...', CHECKING)
        self.assertEqual(DEMO, 'Demo environment')
        self.assertEqual(UNAVAILABLE, 'Environment unavailable')
        self.assertEqual(self.report['pending_observed']['text'], CHECKING)
        self.assertEqual(self.report['after_ok']['text'], DEMO)
        self.assertEqual(self.report['after_network'], UNAVAILABLE)

    def test_extra_key_yields_unavailable(self):
        self.assertEqual(self.report['after_extra'], UNAVAILABLE)

    def test_other_mode_value_yields_unavailable(self):
        self.assertEqual(self.report['after_other'], UNAVAILABLE)

    def test_missing_mode_key_yields_unavailable(self):
        self.assertEqual(self.report['after_empty'], UNAVAILABLE)

    def test_non_200_yields_unavailable(self):
        self.assertEqual(self.report['after_non200'], UNAVAILABLE)

    def test_malformed_json_yields_unavailable(self):
        self.assertEqual(self.report['after_malformed'], UNAVAILABLE)

    def test_network_failure_yields_unavailable(self):
        self.assertEqual(self.report['after_network'], UNAVAILABLE)

    def test_pending_probe_shows_checking_then_terminal_demo(self):
        self.assertEqual(self.report['pending_observed']['text'], CHECKING)
        self.assertEqual(self.report['pending_observed']['calls'], 1)
        self.assertEqual(self.report['pending_issued'], 1)
        self.assertEqual(self.report['after_deferred'], DEMO)
        self.assertEqual(self.report['pending_timer_count'], 0,
                         'the pending probe must not schedule a setTimeout')
        self.assertEqual(self.report['pending_interval_count'], 0,
                         'the pending probe must not arm a setInterval')

    def test_no_timers_are_armed_for_the_probe(self):
        self.assertEqual(self.report['interval_count'], 0,
                         'the probe must not arm a setInterval for /service-mode')
        self.assertEqual(self.report['timer_count'], 0,
                         'the probe must not schedule a setTimeout for /service-mode')

    def test_preexisting_service_status_indicator_is_preserved(self):
        self.assertEqual(self.report['service_status_text'], 'Service available')

    def test_probe_never_blocks_or_mutates_form_search_filter_or_sort(self):
        # The whole non-interference contract: the indicator keeps the submit
        # button enabled, leaves the form's aria-busy closed, preserves the
        # typed draft, and never touches the search, filter or sort state.
        state = self.report['noninterference']
        self.assertFalse(state['button_disabled'],
                         'the probe must not disable the submit button')
        self.assertFalse(state['aria_busy'],
                         'the probe must not mark the form busy')
        self.assertEqual(state['title_draft'], '')
        self.assertEqual(state['description_draft'], '')
        self.assertEqual(state['search_value'], '')
        self.assertEqual(state['filter_all'], 'true')
        self.assertEqual(state['filter_open'], 'false')
        self.assertEqual(state['filter_completed'], 'false')
        self.assertEqual(state['sort_value'], 'newest-first')

    def test_exactly_one_request_per_page_load_across_all_loads(self):
        # The demo load, the six disallowed-outcome loads, the pending load and
        # the non-interference load each issue exactly one /service-mode request.
        self.assertEqual(self.report['after_ok']['calls'], 1)
        self.assertEqual(self.report['pending_issued'], 1)


# --------------------------------------------------------------------------- #
# Static accessibility of the shipped markup and scoped styles.
# --------------------------------------------------------------------------- #
class ServiceModeMarkupTests(unittest.TestCase):

    def test_indicator_markup_is_accessible_and_starts_checking(self):
        html = _read(INDEX_HTML)
        self.assertIn('id="service-mode"', html)
        self.assertIn('role="status"', html)
        self.assertIn(CHECKING, html)

    def test_new_style_rules_are_scoped_to_the_indicator(self):
        css = _read(STYLE_CSS)
        self.assertIn('service-mode', css)


if __name__ == '__main__':
    unittest.main()
