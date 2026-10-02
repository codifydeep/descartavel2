"""Test-first acceptance for SORT-1: newest/oldest feedback sort views.

A native select named ``Sort feedback`` offers ``Newest first`` (first, default)
and ``Oldest first``. The client orders the rendered board by numeric ``id`` --
descending for newest, ascending for oldest -- per page, never by timestamps,
fetched order, string sort, URL or storage. The selection survives polling,
filters, creation and completion while drafts, the pending guard, Escape, the
filter, the whole-board summary and all existing tests are preserved.
``GET /feedback`` is unchanged and the fetched array is never mutated. The real
``app.js`` runs under a Node ``vm`` Window and settles deterministically.
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
from app.server import Handler
APP_JS_PATH = ROOT / 'app' / 'static' / 'app.js'
NODE_TIMEOUT_SECONDS = 30
SORT_ID = 'sort-feedback'
SORT_NAME = 'Sort feedback'
NEWEST_VALUE = 'newest-first'
OLDEST_VALUE = 'oldest-first'
NEWEST_IDS = [10, 3, 2, 1]
OLDEST_IDS = [1, 2, 3, 10]

class _QuietHandler(Handler):
    """Real handler with logging silenced."""

    def log_message(self, *args):
        pass

class SortApiContractTests(unittest.TestCase):
    """``GET /feedback`` stays ascending and sort-free."""

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
        request = Request('http://127.0.0.1:%d%s' % (self.port, path), data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                status = response.status
                raw = response.read()
        except HTTPError as error:
            status = error.code
            raw = error.read()
        return (status, raw)

    def seed(self):
        for title in ('First', 'Second', 'Third'):
            status, _ = self.call('POST', '/feedback', {'title': title})
            self.assertEqual(status, 201, 'create must succeed')

    def test_list_is_ascending_by_numeric_id(self):
        self.seed()
        status, raw = self.call('GET', '/feedback')
        self.assertEqual(status, 200)
        body = json.loads(raw.decode('utf-8'))
        ids = [item['id'] for item in body['items']]
        self.assertEqual(ids, sorted(ids), 'list ascends, got %r' % ids)
        self.assertEqual([item['title'] for item in body['items']], ['First', 'Second', 'Third'])

    def test_api_ignores_a_sort_parameter_and_stays_untouched(self):
        self.seed()
        base_status, base_raw = self.call('GET', '/feedback')
        for query in ('sort=oldest', 'sort=newest', 'sort='):
            status, raw = self.call('GET', '/feedback?%s' % query)
            self.assertEqual(status, base_status, 'sort=%r status stable' % query)
            self.assertEqual(raw, base_raw, 'sort=%r bytes identical' % query)
NODE_HARNESS_TEMPLATE = '\'use strict\';\nconst vm = require(\'vm\');\nconst fs = require(\'fs\');\nconst SOURCE_PATH = %(source_path)s;\nconst SOURCE_NAME = %(source_filename)s;\nconst SOURCE = fs.readFileSync(SOURCE_PATH, \'utf8\');\nfunction makeElement(id, tagName) {\n  const el = {\n    id: id, tagName: tagName || \'div\', children: [], _text: \'\', className: \'\',\n    type: \'\', disabled: false, hidden: false, value: \'\', elements: {},\n    attributes: {}, listeners: {}, options: [],\n    classList: {\n      _set: new Set(),\n      add: function (c) { this._set.add(c); },\n      remove: function (c) { this._set.delete(c); },\n      toggle: function (c, on) { const force = (on === undefined) ? !this._set.has(c) : Boolean(on);\n        if (force) { this._set.add(c); } else { this._set.delete(c); } return force;\n      },\n      contains: function (c) { return this._set.has(c); }\n    },\n    appendChild: function (child) { this.children.push(child); return child; },\n    addEventListener: function (type, handler) {\n      (this.listeners[type] = this.listeners[type] || []).push(handler);\n    },\n    dispatchEvent: function (event) { const list = this.listeners[(event && event.type) || \'\'] || [];\n      for (let i = 0; i < list.length; i += 1) { list[i](event); } return true;\n    },\n    setAttribute: function (name, value) { this.attributes[name] = String(value); },\n    getAttribute: function (name) {\n      return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;\n    },\n    querySelector: function (selector) {\n      if (selector === \'button[type="submit"]\' || selector === \'button[type=submit]\' || selector === \'button\') { return button; }\n      if (selector.charAt(0) === \'#\') { return byId[selector.slice(1)] || null; }\n      return null;\n    },\n    reset: function () {\n      Object.keys(this.elements).forEach(function (k) { this.elements[k].value = \'\'; }, this); }\n  };\n  Object.defineProperty(el, \'textContent\', {\n    get: function () { return this._text; }, set: function (v) { this._text = String(v); }\n  });\n  Object.defineProperty(el, \'innerHTML\', {\n    get: function () { return this._text; },\n    set: function (v) { this._text = String(v); this.children = []; }\n  });\n  return el; }\nfunction makeOption(text, value) { const option = makeElement(\'\', \'option\');\n  option.textContent = text; option.value = value === undefined ? text : value;\n  return option; }\nconst byId = {};\n[\'feedback-form\', \'feedback-list\', \'empty-state\', \'form-status\', \'feedback-summary\',\n \'summary-total\', \'summary-open\', \'summary-completed\', \'title\', \'description\']\n  .forEach(function (id) { byId[id] = makeElement(id); });\nbyId[\'feedback-form\'].elements.title = byId[\'title\'];\nbyId[\'feedback-form\'].elements.description = byId[\'description\'];\nconst filterRoot = makeElement(\'feedback-filter\');\nconst filterControls = {};\n[\'filter-all\', \'filter-open\', \'filter-completed\'].forEach(function (id) { filterControls[id] = makeElement(id, \'button\'); });\nbyId[\'feedback-filter\'] = filterRoot;\nconst button = makeElement(\'submit-button\', \'button\');\nbutton.type = \'submit\';\nconst sortSelect = makeElement(\'sort-feedback\', \'select\');\nconst sortLabel = makeElement(\'sort-feedback-label\', \'label\');\nsortLabel.setAttribute(\'for\', \'sort-feedback\');\nsortLabel.textContent = \'Sort feedback\';\nsortSelect.setAttribute(\'aria-label\', \'Sort feedback\');\nsortSelect.options.push(makeOption(\'Newest first\', \'newest-first\'));\nsortSelect.options.push(makeOption(\'Oldest first\', \'oldest-first\'));\nsortSelect.value = \'newest-first\';\nbyId[\'sort-feedback\'] = sortSelect;\nbyId[\'sort-feedback-label\'] = sortLabel;\nconst items = [\n  { id: 3, title: \'III open\', completed: false }, { id: 10, title: \'TEN newest\', completed: false },\n  { id: 1, title: \'Alpha old\', completed: true }, { id: 2, title: \'II open\', completed: false }];\nlet nextId = 11;\nfunction summaryCounts() { const total = items.length;\n  const completed = items.filter(function (it) { return it.completed; }).length;\n  return { total: total, completed: completed, open: total - completed }; }\nfunction jsonResponse(body, ok) {\n  return {\n    ok: (ok === undefined) ? true : ok,\n    status: (ok === undefined || ok) ? 200 : 500,\n    json: function () { return Promise.resolve(body); }\n  }; }\nconst deferreds = {};\nfunction makeDeferred(name) { const d = { promise: null, resolve: null, reject: null };\n  d.promise = new Promise(function (res, rej) { d.resolve = res; d.reject = rej; });\n  deferreds[name] = d; return d; }\nconst calls = [];\nconst posts = [];\nlet postMode = \'ok\';\nlet postDeferredName = \'post\';\nfunction filterFromUrl(target) { const query = String(target).split(\'?\')[1] || \'\';\n  const pairs = query.split(\'&\');\n  for (let i = 0; i < pairs.length; i += 1) { const bits = pairs[i].split(\'=\');\n    if (decodeURIComponent(bits[0]) === \'status\') { return decodeURIComponent(bits[1] || \'\'); }\n  }\n  return null; }\nfunction rowsFor(wanted) {\n  return items.filter(function (it) {\n    return wanted === null ? true\n         : wanted === \'open\' ? it.completed !== true : it.completed === true;\n  }); }\nfunction defaultFetch(url, options) { const method = (options && options.method) || \'GET\';\n  const target = String(url);\n  const isBoardGet = target.indexOf(\'/feedback\') === 0 && method === \'GET\' &&\n                     target.indexOf(\'/feedback/summary\') !== 0;\n  const record = { url: target, method: String(method), status: filterFromUrl(target) };\n  calls.push(record);\n  if (isBoardGet) {\n    return Promise.resolve(jsonResponse({ items: rowsFor(filterFromUrl(target)).slice() }, true)); }\n  if (target === \'/feedback\' && method === \'POST\') { let body = {};\n    try { body = JSON.parse(options && options.body) || {}; } catch (error) { body = {}; }\n    const p = { url: target, method: \'POST\', body: body };\n    posts.push(p);\n    calls[calls.length - 1] = p;\n    if (postMode === \'error\') {\n      return Promise.resolve(jsonResponse({ error: \'Unable to submit feedback.\' }, false)); }\n    if (postMode === \'ok\') { const item = { id: nextId, title: body.title || \'Untitled\', completed: false };\n      nextId += 1; items.push(item);\n      return Promise.resolve(jsonResponse(item, true)); }\n    return makeDeferred(postDeferredName).promise; }\n  if (target === \'/feedback/summary\') { return Promise.resolve(jsonResponse(summaryCounts(), true));\n  }\n  const complete = /^\\/feedback\\/(\\d+)\\/complete$/.exec(target);\n  if (complete) { const id = Number(complete[1]);\n    items.forEach(function (it) { if (it.id === id) { it.completed = true; } });\n    return Promise.resolve(jsonResponse({ id: id, completed: true }, true)); }\n  return Promise.resolve(jsonResponse({}, true)); }\nlet intervalCallback = null;\nconst target = {\n  Boolean: Boolean, Promise: Promise, JSON: JSON, String: String,\n  Array: Array, Object: Object, Error: Error, Number: Number, Math: Math,\n  document: {\n    getElementById: function (id) { return byId[id] || filterControls[id] || null; },\n    createElement: function (tag) { return makeElement(\'<\' + tag + \'>\', tag); },\n    querySelector: function (s) { return s.charAt(0) === \'#\' ? (byId[s.slice(1)] || null) : null; },\n    addEventListener: function () {} },\n  fetch: defaultFetch,\n  setTimeout: function () { return 0; }, clearTimeout: function () {},\n  setInterval: function (fn) { intervalCallback = fn; return 0; }, clearInterval: function () {},\n  console: { log: function () {}, error: function () {}, warn: function () {} }\n};\nconst sandbox = new Proxy(target, {\n  set: function (t, k, v) { t[k] = (k === \'status\') ? String(v) : v; return true; },\n  get: function (t, k) { return t[k]; },\n  has: function (t, k) { return k in t; },\n  defineProperty: function (t, k, d) { t[k] = (k === \'status\') ? String(d.value) : d.value; return true; },\n  getOwnPropertyDescriptor: function (t, k) { return Object.getOwnPropertyDescriptor(t, k); },\n  deleteProperty: function (t, k) { delete t[k]; return true; },\n  ownKeys: function (t) { return Reflect.ownKeys(t); }\n});\ntarget.window = sandbox;\ntarget.self = sandbox;\ntarget.globalThis = sandbox;\nconst context = vm.createContext(sandbox);\nfunction report(payload) { process.stdout.write(JSON.stringify(payload)); }\nfunction flush() { let chain = Promise.resolve();\n  for (let i = 0; i < 16; i += 1) { chain = chain.then(function () { return undefined; }); }\n  return chain; }\nfunction boardTitles() {\n  return byId[\'feedback-list\'].children.map(function (entry) { const kids = entry.children || [];\n    const label = kids.filter(function (k) { return String(k.className).indexOf(\'feedback-title\') !== -1;\n    })[0];\n    return label ? label.textContent : (kids[0] ? kids[0].textContent : \'\');\n  }); }\nfunction controlPresent() {\n  return Boolean(byId[\'sort-feedback\'] &&\n    (byId[\'sort-feedback\'].options || []).length >= 2); }\nfunction accessName() { let name = sortSelect.getAttribute(\'aria-label\') || \'\';\n  if (sortLabel.getAttribute(\'for\') === \'sort-feedback\') { name = (sortLabel.textContent + \' \' + name).trim(); }\n  return name; }\nfunction fire(control, type, extra) {\n  const event = Object.assign({ type: type, target: control, currentTarget: control,\n                                preventDefault: function () {} }, extra || {});\n  try { const handlers = control.listeners[type] || [];\n    for (let i = 0; i < handlers.length; i += 1) { handlers[i](event); }\n    return { threw: null };\n  } catch (thrown) { return { threw: String((thrown && thrown.message) || thrown) }; }\n}\nfunction dispatchChange(value) { sortSelect.value = value;\n  return Object.assign(fire(sortSelect, \'change\'), { value: value }); }\nfunction clickFilter(id) { const control = filterControls[id];\n  const root = byId[\'feedback-filter\'];\n  const event = { type: \'click\', target: control, currentTarget: root,\n                  preventDefault: function () {} };\n  try {\n    if (root && (root.listeners.click || []).length) { root.dispatchEvent(event); }\n    const handlers = (control && control.listeners.click) || [];\n    for (let i = 0; i < handlers.length; i += 1) { handlers[i](event); }\n    return { threw: null };\n  } catch (thrown) { return { threw: String((thrown && thrown.message) || thrown) }; }\n}\nfunction dispatchSubmit() { return fire(byId[\'feedback-form\'], \'submit\');\n}\nfunction dispatchKeydown(key) {\n  return Object.assign(fire(byId[\'feedback-form\'], \'keydown\', { key: key, bubbles: true }), { key: key }); }\nfunction fillForm(title, description) { byId[\'title\'].value = title; byId[\'description\'].value = description;\n}\nfunction completeOpenItem() { const rendered = byId[\'feedback-list\'].children;\n  let toggle = null;\n  for (let i = 0; i < rendered.length && toggle === null; i += 1) { const kids = rendered[i].children || [];\n    for (let j = 0; j < kids.length; j += 1) {\n      if (String(kids[j].className).indexOf(\'complete-button\') !== -1 &&\n          kids[j].disabled !== true) { toggle = kids[j]; break; }\n    }\n  }\n  if (!toggle) { return { threw: \'no enabled complete button rendered\' }; }\n  return fire(toggle, \'click\'); }\nfunction boardOrder() {\n  return boardTitles().map(function (title) {\n    for (let i = 0; i < items.length; i += 1) { if (items[i].title === title) { return items[i].id; } }\n    return null;\n  }); }\nfunction state() {\n  return { ids: boardOrder(), count: byId[\'feedback-list\'].children.length,\n    status: byId[\'form-status\'].textContent, is_error: byId[\'form-status\'].classList.contains(\'is-error\'),\n    title: byId[\'title\'].value, description: byId[\'description\'].value,\n    total: byId[\'summary-total\'].textContent, completed: byId[\'summary-completed\'].textContent,\n    button_disabled: button.disabled === true,\n    aria_busy: byId[\'feedback-form\'].getAttribute(\'aria-busy\'), sort_value: sortSelect.value }; }\nlet executed = true;\nlet error = null;\n(async function drive() {\n  try { const script = new vm.Script(SOURCE, { filename: SOURCE_NAME });\n    script.runInContext(context);\n  } catch (thrown) { executed = false; error = String((thrown && thrown.message) || thrown); }\n  if (!executed) { report({ executed: false, error: error }); return; }\n  await flush();\n  const initial_calls = calls.slice().map(function (c) { return { url: c.url, method: c.method, status: c.status }; });\n  const default_state = state();\n  const control_snapshot = { present: controlPresent(), name: accessName(),\n                             value: sortSelect.value };\n  const open_click = clickFilter(\'filter-open\');\n  await flush();\n  const open_state = state();\n  const to_oldest = dispatchChange(\'oldest-first\');\n  await flush();\n  const oldest_open_state = state();\n  const back_newest = dispatchChange(\'newest-first\');\n  await flush();\n  const newest_open_state = state();\n  const filter_all = clickFilter(\'filter-all\');\n  await flush();\n  const default_restored = state();\n  if (typeof intervalCallback === \'function\') { intervalCallback(); }\n  await flush();\n  const polled_state = state();\n  // Pure pre-create Oldest view, then back to Newest; after-create Oldest is separate.\n  const to_oldest_before_create = dispatchChange(\'oldest-first\');\n  await flush();\n  const oldest_before_create_state = state();\n  const back_newest_before_create = dispatchChange(\'newest-first\');\n  await flush();\n  fillForm(\'Fresh item\', \'details\');\n  dispatchSubmit();\n  await flush();\n  const after_create_state = state();\n  const to_oldest_again = dispatchChange(\'oldest-first\');\n  await flush();\n  const oldest_state = state();\n  const oldest_value_compatible = oldest_state.sort_value !== \'newest-first\';\n  const value_effect = dispatchChange(\'newest-first\');\n  await flush();\n  const newest_state = state();\n  const newest_value_compatible = newest_state.sort_value !== \'oldest-first\';\n  const complete_click = completeOpenItem();\n  await flush();\n  const after_complete_state = state();\n  fillForm(\'Draft title\', \'draft description\');\n  if (typeof intervalCallback === \'function\') { intervalCallback(); }\n  clickFilter(\'filter-completed\');\n  await flush();\n  clickFilter(\'filter-all\');\n  await flush();\n  const draft_state = state();\n  const posts_before_pending = posts.length;\n  const pre_submit = state();\n  postMode = \'defer\';\n  postDeferredName = \'sort-pending\';\n  fillForm(\'Pending title\', \'pending description\');\n  dispatchSubmit();\n  await flush();\n  const pending_before = state();\n  const to_oldest_pending = dispatchChange(\'oldest-first\');\n  const to_newest_pending = dispatchChange(\'newest-first\');\n  clickFilter(\'filter-open\');\n  await flush();\n  const pending_after = state();\n  const posts_after_pending = posts.length;\n  const pending_settle = { resolved: false };\n  if (deferreds[\'sort-pending\'] && deferreds[\'sort-pending\'].resolve) {\n    deferreds[\'sort-pending\'].resolve(jsonResponse(\n      { id: nextId, title: \'Pending title\', completed: false }, true));\n    nextId += 1;\n    items.push({ id: nextId - 1, title: \'Pending title\', completed: false });\n    pending_settle.resolved = true; }\n  await flush();\n  const after_pending_settle = state();\n  postMode = \'error\';\n  fillForm(\'Failed item\', \'nope\');\n  const before_fail = state();\n  const fail_dispatch = dispatchSubmit();\n  await flush();\n  const after_fail = state();\n  postMode = \'ok\';\n  const escape_result = dispatchKeydown(\'Escape\');\n  await flush();\n  report({ executed: true, error: null, filename: SOURCE_NAME, initial_calls: initial_calls,\n    default_state: default_state, control_snapshot: control_snapshot, open_click: open_click,\n    open_state: open_state, to_oldest: to_oldest, oldest_open_state: oldest_open_state,\n    back_newest: back_newest, newest_open_state: newest_open_state, filter_all: filter_all,\n    default_restored: default_restored, polled_state: polled_state,\n    to_oldest_before_create: to_oldest_before_create,\n    oldest_before_create_state: oldest_before_create_state,\n    back_newest_before_create: back_newest_before_create,\n    after_create_state: after_create_state, to_oldest_again: to_oldest_again,\n    oldest_state: oldest_state, value_effect: value_effect, newest_state: newest_state,\n    oldest_value_compatible: oldest_value_compatible, newest_value_compatible: newest_value_compatible,\n    complete_click: complete_click, after_complete_state: after_complete_state,\n    draft_state: draft_state, posts_before_pending: posts_before_pending,\n    pending_before: pending_before, to_oldest_pending: to_oldest_pending,\n    to_newest_pending: to_newest_pending, pending_after: pending_after,\n    posts_after_pending: posts_after_pending, pending_settle: pending_settle,\n    after_pending_settle: after_pending_settle, pre_submit: pre_submit, before_fail: before_fail,\n    fail_dispatch: fail_dispatch, after_fail: after_fail, escape_result: escape_result });\n})().catch(function (thrown) { report({ executed: false, error: String((thrown && thrown.message) || thrown) });\n});\n'

class SortClientHarnessCase(unittest.TestCase):
    """Run the real ``app.js`` once; expose its report."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')

    def setUp(self):
        self.assertTrue(APP_JS_PATH.is_file(), 'asset missing: %s' % APP_JS_PATH)
        self.source_filename = str(APP_JS_PATH)
        self.source_bytes = APP_JS_PATH.read_bytes()
        self.source_sha256 = hashlib.sha256(self.source_bytes).hexdigest()
        self.assertTrue(self.node, 'node unavailable')
        program = NODE_HARNESS_TEMPLATE % {'source_path': json.dumps(self.source_filename), 'source_filename': json.dumps(self.source_filename)}
        completed = subprocess.run([self.node, '--input-type=commonjs', '-'], input=program.encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=NODE_TIMEOUT_SECONDS, check=False)
        self.assertEqual(completed.returncode, 0, 'node exit %d: %s' % (completed.returncode, completed.stderr.decode('utf-8', 'replace')))
        raw = completed.stdout.decode('utf-8', 'replace').strip()
        self.assertTrue(raw, 'no report')
        self.report = json.loads(raw)
        self.assertEqual(self.report.get('filename'), self.source_filename, 'filename must match')
        if not self.report.get('executed'):
            self.fail('app.js failed: %s' % self.report.get('error'))

    def ids(self, key):
        return self.report[key]['ids']

class SortControlPresenceTests(SortClientHarnessCase):
    """A native, accessible sort select."""

    def test_real_client_executes_under_the_window(self):
        self.assertTrue(self.source_bytes.strip())
        self.assertRegex(self.source_sha256, '^[0-9a-f]{64}$')
        self.assertEqual(len(self.report['initial_calls']), 2, 'initial load: two GETs')

    def test_sort_control_is_available(self):
        self.assertTrue(self.report['control_snapshot']['present'], 'must address select %s' % SORT_ID)

    def test_sort_control_is_labelled_sort_feedback(self):
        name = self.report['control_snapshot']['name']
        self.assertIn(SORT_NAME, name, 'must name %r, got %r' % (SORT_NAME, name))

    def test_newest_is_the_default_selection(self):
        self.assertEqual(self.report['default_state']['sort_value'], NEWEST_VALUE, 'default %r' % self.report['default_state']['sort_value'])

class DefaultAndDirectionalOrderTests(SortClientHarnessCase):
    """Default newest; both numeric directions."""

    def test_default_view_orders_newest_by_numeric_id_descending(self):
        ids = self.ids('default_state')
        self.assertEqual(ids, sorted(ids, reverse=True), 'newest descends, got %r' % ids)
        self.assertEqual(ids, NEWEST_IDS, 'default newest, got %r' % ids)
        self.assertLess(ids.index(10), ids.index(2), 'numeric: 10 before 2')

    def test_oldest_view_orders_numeric_id_ascending_with_id_2_before_10(self):
        # Pre-create board: the pure directional view.
        ids = self.ids('oldest_before_create_state')
        self.assertEqual(ids, sorted(ids), 'oldest ascends, got %r' % ids)
        self.assertEqual(ids, OLDEST_IDS, 'oldest oldest, got %r' % ids)
        self.assertLess(ids.index(2), ids.index(10), 'numeric: 2 before 10')

    def test_both_directions_are_the_exact_reverse_of_each_other(self):
        # Same-board pairs: each comparison is a true reverse.
        self.assertEqual(self.ids('default_restored'),
                         list(reversed(self.ids('oldest_before_create_state'))),
                         'newest reverses oldest')
        self.assertEqual(self.ids('newest_state'),
                         list(reversed(self.ids('oldest_state'))),
                         'reverses after create')
        self.assertTrue(self.report['oldest_value_compatible'], 'Oldest stays Oldest')
        self.assertTrue(self.report['newest_value_compatible'], 'Newest stays Newest')

    def test_direction_changes_do_not_throw(self):
        for key in ('to_oldest', 'back_newest', 'to_oldest_before_create',
                    'back_newest_before_create', 'to_oldest_again', 'value_effect',
                    'to_oldest_pending', 'to_newest_pending'):
            self.assertIsNone(self.report[key]['threw'], '%s change must not throw' % key)

class FilterCompositionTests(SortClientHarnessCase):
    """Sort composes with the filter."""

    def test_open_filter_composes_with_the_default_newest_order(self):
        ids = self.ids('open_state')
        self.assertEqual(ids, sorted(ids, reverse=True), 'Newest/Open descends, %r' % ids)
        self.assertTrue(all((item in (2, 3, 10) for item in ids)), 'Open excludes completed, %r' % ids)
        self.assertEqual(self.report['open_state']['sort_value'], NEWEST_VALUE)

    def test_oldest_applies_inside_the_open_filter(self):
        ids = self.ids('oldest_open_state')
        self.assertEqual(ids, sorted(ids), 'Oldest/Open ascends, %r' % ids)
        self.assertLess(ids.index(2), ids.index(10), 'Open numeric order')
        self.assertTrue(all((item in (2, 3, 10) for item in ids)))
        self.assertNotEqual(self.report['oldest_open_state']['sort_value'], NEWEST_VALUE)

    def test_newest_is_restored_inside_the_open_filter(self):
        ids = self.ids('newest_open_state')
        self.assertEqual(ids, sorted(ids, reverse=True), 'Newest/Open returns, %r' % ids)
        self.assertTrue(all((item in (2, 3, 10) for item in ids)))
        self.assertEqual(self.report['newest_open_state']['sort_value'], NEWEST_VALUE)

    def test_returning_to_all_keeps_the_selected_order(self):
        ids = self.ids('default_restored')
        self.assertEqual(ids, sorted(ids, reverse=True), 'All keeps Newest, %r' % ids)
        self.assertEqual(sorted(ids), sorted(OLDEST_IDS), 'All shows all, got %r' % ids)

    def test_filter_clicks_do_not_throw(self):
        self.assertIsNone(self.report['open_click']['threw'])
        self.assertIsNone(self.report['filter_all']['threw'])

class PersistenceAcrossEventsTests(SortClientHarnessCase):
    """The selection survives poll, create, complete."""

    def test_polling_keeps_the_selected_order(self):
        ids = self.ids('polled_state')
        self.assertEqual(ids, sorted(ids, reverse=True), 'poll keeps Newest, %r' % ids)
        self.assertEqual(self.report['polled_state']['sort_value'], NEWEST_VALUE, 'poll keeps select')

    def test_creation_keeps_the_selection_and_orders_the_new_item_first(self):
        ids = self.ids('after_create_state')
        self.assertEqual(ids[0], 11, 'Newest: 11 leads, %r' % ids)
        self.assertEqual(ids, sorted(ids, reverse=True), 'create keeps Newest, %r' % ids)
        self.assertEqual(self.report['after_create_state']['status'], 'Thanks! Your feedback was added.', 'success msg remains')
        self.assertEqual(self.report['after_create_state']['title'], '', 'create clears form')
        self.assertFalse(self.report['after_create_state']['is_error'])

    def test_creation_keeps_the_selection_under_oldest_too(self):
        ids = self.ids('oldest_state')
        self.assertEqual(ids, sorted(ids), 'create keeps Oldest, %r' % ids)
        self.assertEqual(ids[-1], 11, 'Oldest: 11 last, %r' % ids)

class DraftPersistenceTests(SortClientHarnessCase):
    """Drafts survive; sorts never submit."""

    def test_typed_draft_survives_polling_and_filter_changes(self):
        draft = self.report['draft_state']
        self.assertEqual(draft['title'], 'Draft title', 'poll/filter keeps title')
        self.assertEqual(draft['description'], 'draft description', 'poll/filter keeps desc')

    def test_sort_interactions_issue_no_post(self):
        self.assertEqual(self.report['posts_before_pending'], 1, 'create is the only POST')

class PendingSubmitProtectionTests(SortClientHarnessCase):
    """Sorting mid-submit keeps the pending guard."""

    def test_pre_submit_is_distinct_from_the_pending_window(self):
        pre = self.report['pre_submit']
        pending = self.report['pending_before']
        self.assertFalse(pre['button_disabled'], 'pre-submit enabled')
        self.assertFalse(pre['aria_busy'] == 'true', 'pre-submit not busy')
        self.assertTrue(pending['button_disabled'], 'pending disabled')
        self.assertNotEqual(pre['status'], 'Submitting...', 'pre-submit not the pending copy')
        self.assertNotEqual(pre['status'], pending['status'], 'pre-submit vs pending')

    def test_failed_submit_commits_no_row_and_keeps_the_selection(self):
        before = self.report['before_fail']
        after = self.report['after_fail']
        self.assertIsNone(self.report['fail_dispatch']['threw'], 'fail must not throw')
        self.assertEqual(after['count'], before['count'], 'fail commits no row')
        self.assertEqual(after['sort_value'], NEWEST_VALUE, 'fail keeps select')
        self.assertEqual(after['status'], 'Unable to submit feedback.', 'fail surfaces error')

    def test_pending_state_shows_submitting_and_busy(self):
        pending = self.report['pending_before']
        self.assertEqual(pending['status'], 'Submitting...', 'pending shows Submitting..., %r' % pending['status'])
        self.assertTrue(pending['button_disabled'], 'disabled pending')
        self.assertEqual(pending['aria_busy'], 'true', 'aria-busy pending')

    def test_sort_switch_during_pending_keeps_the_guard_and_draft(self):
        before = self.report['pending_before']
        after = self.report['pending_after']
        self.assertTrue(after['button_disabled'], 'no re-enable mid-submit')
        self.assertEqual(after['status'], before['status'], 'no disturb pending')
        self.assertEqual(after['title'], before['title'], 'keeps draft')
        self.assertEqual(after['aria_busy'], 'true', 'keeps aria-busy')
        self.assertEqual(self.report['posts_after_pending'], 2, 'no POST')

    def test_pending_post_settles_and_keeps_the_selection(self):
        self.assertTrue(self.report['pending_settle']['resolved'], 'harness settles the POST')
        after = self.report['after_pending_settle']
        self.assertFalse(after['button_disabled'], 'settling re-enables')
        self.assertEqual(after['aria_busy'], 'false')
        self.assertEqual(after['sort_value'], NEWEST_VALUE, 'settling keeps select')

class PreservedInteractionTests(SortClientHarnessCase):
    """Escape and the summary stay intact."""

    def test_escape_dismissal_still_runs_without_error(self):
        self.assertIsNone(self.report['escape_result']['threw'], 'Escape survives')
        self.assertEqual(self.report['escape_result']['key'], 'Escape')

    def test_completion_keeps_the_selection_and_marks_the_item(self):
        self.assertIsNone(self.report['complete_click']['threw'], 'toggle must not throw')
        after = self.report['after_complete_state']
        self.assertEqual(after['sort_value'], NEWEST_VALUE, 'completion keeps order')
        self.assertEqual(after['completed'], '2', 'reaches summary')

    def test_summary_stays_whole_board_with_the_sort_control(self):
        self.assertEqual(self.report['default_restored']['total'], '4', 'summary whole-board')
if __name__ == '__main__':
    unittest.main()
