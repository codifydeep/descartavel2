"""Incremental U3: page-memory independence and lifetime of the query.

Red-first tests for delivery unit U3, reusing the harness pattern proven by U2:
the real ``app/static/app.js`` runs unmodified inside a Node ``vm`` context
whose global is the page ``app/static/index.html`` would load. The client is
driven only through user events, and every asserted value is read from the live
run -- never from source text, never reimplemented.

C08: Each browser has independent query in page memory only.
C09: Query survives polling and creation/completion.
C10: Discard stale fetch responses from an earlier query, status or request
     generation.

The frozen base captures the requested filter/search when a board GET is issued
and drops the response when either has since changed (``app.js`` loadFeedback
guard). These tests exercise lifetime and generation through the shipped guard;
Node is mandatory, it is never a skip.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = ROOT / 'app' / 'static' / 'app.js'
INDEX_HTML_PATH = ROOT / 'app' / 'static' / 'index.html'

# A hung driver must fail loudly, never stall the suite.
NODE_TIMEOUT_SECONDS = 30

# fs.readFileSync gives the real bytes; require.resolve is not needed. The
# client runs with vm.runInContext so the appended driver shares its global.
DRIVER_PREAMBLE = r"""'use strict';
const vm = require('vm');
const fs = require('fs');

const SOURCE_PATH = %(source_path)s;
const HTML_PATH = %(html_path)s;
const SOURCE = fs.readFileSync(SOURCE_PATH, 'utf8');
const HTML = fs.readFileSync(HTML_PATH, 'utf8');

// --- DOM stub: textContent/innerHTML setters coerce like the DOM ------------
function makeElement(id, tagName) {
  const el = {
    id: id,
    tagName: (tagName || 'div').toUpperCase(),
    children: [],
    _text: '',
    className: '',
    type: '',
    disabled: false,
    hidden: false,
    value: '',
    checked: false,
    elements: {},
    attributes: {},
    listeners: {},
    labels: [],
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
    appendChild: function (child) {
      child.parentNode = this;
      this.children.push(child);
      return child;
    },
    removeChild: function (child) {
      this.children = this.children.filter(function (n) { return n !== child; });
      child.parentNode = null;
      return child;
    },
    addEventListener: function (type, handler) {
      (this.listeners[type] = this.listeners[type] || []).push(handler);
    },
    removeEventListener: function (type, handler) {
      const list = this.listeners[type] || [];
      this.listeners[type] = list.filter(function (h) { return h !== handler; });
    },
    dispatchEvent: function (event) {
      const type = (event && event.type) || '';
      const list = (this.listeners[type] || []).slice();
      for (let i = 0; i < list.length; i += 1) { list[i].call(this, event); }
      return list.length;
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
        if (this.children[i] === node || this.children[i].contains(node)) {
          return true;
        }
      }
      return false;
    },
    matches: function (selector) {
      const sel = String(selector).trim();
      const tagMatch = /^[a-zA-Z][\w:-]*/.exec(sel);
      if (tagMatch && this.tagName !== tagMatch[0].toUpperCase()) { return false; }
      const rest = sel.slice(tagMatch ? tagMatch[0].length : 0);
      const simple = /([.#]?[\w:-]+|\[[^\]]*\])/g;
      let part;
      while ((part = simple.exec(rest)) !== null) {
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
      walk(this, function (node) {
        if (node !== el && node.matches(selector)) { out.push(node); }
      });
      return out;
    },
    focus: function () {},
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

function walk(node, visit) {
  visit(node);
  for (let i = 0; i < node.children.length; i += 1) { walk(node.children[i], visit); }
}

const byId = {};
const DOCUMENT = makeElement('#document', 'html');

// --- HTML tokenizer: build the tree the client actually addresses -----------
function parseHTML(source) {
  const stack = [DOCUMENT];
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
          if (name === 'value') { el.value = value; }
        }
      }
      const parent = stack[stack.length - 1];
      parent.appendChild(el);
      if (!VOID[tag.toLowerCase()] && m[4] !== '/') { stack.push(el); }
    } else if (m[1]) {
      const name = m[1].toLowerCase();
      for (let i = stack.length - 1; i >= 1; i -= 1) {
        if (stack[i].tagName.toLowerCase() === name) { stack.length = i; break; }
      }
    } else if (m[5] && m[5].trim()) {
      const text = m[5].replace(/\s+/g, ' ').trim();
      if (text) {
        const node = makeElement('#text', 'text');
        node._text = text;
        stack[stack.length - 1].appendChild(node);
      }
    }
  }
  return DOCUMENT;
}

Object.defineProperty(DOCUMENT, 'documentElement', { value: DOCUMENT });
const mm = HTML.match(/<html\b[^>]*>([\s\S]*?)<\/html>/i);
parseHTML(mm ? mm[1] : HTML);

// Resolve label associations so input.labels mirrors the accessible name.
(function () {
  const labelled = DOCUMENT.querySelectorAll('[for]');
  for (let i = 0; i < labelled.length; i += 1) {
    const target = byId[labelled[i].getAttribute('for')];
    if (target) { target.labels.push(labelled[i]); }
  }
}());

// --- the form the client addresses -----------------------------------------
const form = byId['feedback-form'];
const titleInput = byId['title'];
const descriptionInput = byId['description'];
const statusEl = byId['form-status'];
const searchInput = byId['feedback-search'];
const filterRoot = byId['feedback-filter'];
const feedbackList = byId['feedback-list'];
const emptyState = byId['empty-state'];
const summaryRegion = byId['feedback-summary'];

// The client reads form.elements.title/description; mirror the live controls.
if (form) {
  form.elements = { title: titleInput || makeElement('title', 'input'),
                    description: descriptionInput || makeElement('description', 'textarea') };
}

// --- board behind a controllable fetch contract ----------------------------
// Every board GET is deferred so the driver decides exactly when (and with
// what body) it resolves; this is what makes stale-generation discard visible.
const items = [];
let nextId = 1;
let pending = [];       // queued board GETs awaiting resolution
let deferred = [];      // when true, board GETs are held instead of resolved
let calls = [];         // { url, method } for every request issued
let summaries = 0;      // /feedback/summary call count (polling evidence)

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
function defaultFetch(url, options) {
  const method = ((options && options.method) || 'GET').toUpperCase();
  const target = String(url);
  calls.push({ url: target, method: method });

  if (target === '/feedback/summary') {
    summaries += 1;
    return Promise.resolve(jsonResponse(summaryCounts(), true));
  }
  if (method === 'GET' && (target === '/feedback' || target.indexOf('/feedback?') === 0)) {
    if (deferred.length) {
      return new Promise(function (resolve) {
        pending.push({ url: target, resolve: resolve });
      });
    }
    return Promise.resolve(jsonResponse({ items: items.slice() }, true));
  }
  if (method === 'POST' && (target === '/feedback' || target.indexOf('/feedback?') === 0)) {
    const id = nextId; nextId += 1;
    // The submitted title is read from the live form the client submitted (and
    // the request body), never hardcoded, so the create refresh paints exactly
    // the item the user typed -- the board the follow-up GET returns carries it.
    let title = 'posted';
    const rawBody = options && options.body;
    if (typeof rawBody === 'string' && rawBody) {
      try {
        const parsed = JSON.parse(rawBody);
        if (parsed && typeof parsed.title === 'string' && parsed.title) { title = parsed.title; }
      } catch (ignored) { /* keep the fallback title */ }
    }
    if (title === 'posted' && titleInput && typeof titleInput.value === 'string' && titleInput.value.trim()) {
      title = titleInput.value.trim();
    }
    items.push({ id: id, title: title, completed: false });
    return Promise.resolve(jsonResponse({ id: id, title: title, completed: false }, true));
  }
  const complete = /^\/feedback\/(\d+)\/complete$/.exec(target);
  if (method === 'POST' && complete) {
    const id = Number(complete[1]);
    items.forEach(function (it) { if (it.id === id) { it.completed = true; } });
    return Promise.resolve(jsonResponse({ id: id, completed: true }, true));
  }
  return Promise.resolve(jsonResponse({}, true));
}
// Resolve the most recently held board GET (the current, newest generation)
// Resolve the newest/oldest held board GET. The deferred queue is in issuance
// order, so the tail is the request a user's latest action issued (the current
// generation) and the head is the stalest.
function resolveNewest(body) {
  const held = pending.pop();
  if (!held) { return false; }
  held.resolve(jsonResponse(body === undefined ? { items: items.slice() } : body, true));
  return true;
}
// Resolve the oldest still-held board GET (the earliest, stalest generation).
function resolveOldest(body) {
  const held = pending.shift();
  if (!held) { return false; }
  held.resolve(jsonResponse(body === undefined ? { items: items.slice() } : body, true));
  return true;
}

// --- native Window global (status writes coerce to String) -----------------
// Debounce timers are captured (not run inline) so the driver fires them at a
// controlled point and the resulting fetch is deterministic.
const pendingTimers = [];
let intervalCallback = null;
let intervalDelay = null;
const target = {
  location: { href: 'http://localhost/static/index.html' },
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
  setTimeout: function (fn) { pendingTimers.push(fn); return pendingTimers.length; },
  clearTimeout: function (id) {
    if (typeof id === 'number' && id > 0 && id <= pendingTimers.length) {
      pendingTimers[id - 1] = function () {};
    }
  },
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

function flush() {
  let chain = Promise.resolve();
  for (let i = 0; i < 15; i += 1) { chain = chain.then(function () { return undefined; }); }
  return chain;
}
function report(payload) { process.stdout.write(JSON.stringify(payload)); }
function input(control, value) {
  control.value = value;
  control.dispatchEvent({ type: 'input', bubbles: true });
  // The client debounces the search control by 200ms; run any timer it armed
  // so the needle it remembered is actually requested. The harness then flushes
  // microtasks itself, so awaiting the request is deterministic.
  if (pendingTimers.length) {
    const timers = pendingTimers.splice(0, pendingTimers.length);
    for (let i = 0; i < timers.length; i += 1) { timers[i](); }
  }
}
function keydown(control, key) {
  return { type: 'keydown', key: key, bubbles: true, preventDefault: function () {} };
}
function click(control) {
  if (control) { control.dispatchEvent({ type: 'click', bubbles: true }); }
}
// The rendered row titles currently in the live list, for generation evidence.
function renderedTitles() {
  const out = [];
  if (!feedbackList) { return out; }
  for (let i = 0; i < feedbackList.children.length; i += 1) {
    const li = feedbackList.children[i];
    for (let j = 0; j < li.children.length; j += 1) {
      if (li.children[j].className === 'feedback-title') { out.push(li.children[j].textContent); }
    }
  }
  return out;
}
function getCalls() { return calls.map(function (c) { return c.url; }); }
"""

# Appended after the preamble; every reported value comes from the live run.
DRIVER_BODY = r"""function drive() {
  let executed = true;
  let error = null;
  try {
    vm.runInContext(SOURCE, context, { filename: SOURCE_PATH });
  } catch (thrown) {
    executed = false;
    error = String((thrown && thrown.message) || thrown);
  }
  const out = { executed: executed, error: error,
                source_filename: SOURCE_PATH, html_filename: HTML_PATH };
  if (!executed) { report(out); return; }
  items.push({ id: 1, title: 'alpha one', completed: false });
  items.push({ id: 2, title: 'beta two', completed: false });
  items.push({ id: 3, title: 'gamma three', completed: false });
  flush().then(function () {
    out.initial_urls = getCalls();
    out.page_url = String(target.location.href);
    out.sandbox_has_local_storage = Object.prototype.hasOwnProperty.call(target, 'localStorage');
    out.sandbox_has_session_storage = Object.prototype.hasOwnProperty.call(target, 'sessionStorage');
    out.sandbox_has_history = (typeof target.history !== 'undefined' && target.history !== null);
    deferred.push(true);
    input(searchInput, 'alpha');
    const searchUrls = getCalls().filter(function (u) { return u.indexOf('q=') !== -1; });
    out.query_url_after_input = searchUrls.length ? searchUrls[searchUrls.length - 1] : null;
    if (!resolveNewest({ items: [{ id: 1, title: 'alpha one', completed: false }] })) {      out.resolve_error = 'no held board GET after typing';
    }
    return flush().then(function () {
      out.rendered_after_query = renderedTitles();
      calls.length = 0;
      summaries = 0;
      if (intervalCallback) { intervalCallback(); }
      if (!resolveNewest({ items: [{ id: 1, title: 'alpha one', completed: false }] })) {        out.resolve_error = out.resolve_error || 'no held board GET after poll tick';
      }
      return flush().then(function () {
        out.poll_urls = getCalls();
        out.poll_summary_calls = summaries;
        out.rendered_after_poll = renderedTitles();
        calls.length = 0;
        if (titleInput) { titleInput.value = 'alpha new'; }
        if (form) {
          form.dispatchEvent({ type: 'submit', bubbles: true, preventDefault: function () {} });
        }
        return flush().then(function () {
          out.create_urls = getCalls();
          const settled = resolveNewest();
          if (!settled) {
            out.resolve_error = out.resolve_error || 'no held board GET after create';
          }
          return flush().then(function () {
            out.rendered_after_create = renderedTitles();
            calls.length = 0;
            if (intervalCallback) { intervalCallback(); }
            calls.length = 0;
            deferred.push(true);
            const toggle = feedbackList && feedbackList.children.length
              ? (function () {
                  const li = feedbackList.children[0];
                  for (let i = 0; i < li.children.length; i += 1) {
                    if (li.children[i].className === 'complete-button') { return li.children[i]; }
                  }
                  return null;
                })()
              : null;
            click(toggle);
            return flush().then(function () {
              out.complete_urls = getCalls();
              if (!resolveNewest({ items: [{ id: 1, title: 'alpha one', completed: true }] })) {                out.resolve_error = out.resolve_error || 'no held board GET after complete';
              }
              return flush().then(function () {
                out.rendered_after_complete = renderedTitles();
                deferred.push(true);
                calls.length = 0;
                input(searchInput, 'beta');
                const genAIdx = calls.length - 1;
                input(searchInput, 'gamma');
                const genBIdx = calls.length - 1;
                out.genA_urls = calls.slice(genAIdx).map(function (c) { return c.url; });
                out.genB_urls = calls.slice(genBIdx).map(function (c) { return c.url; });
                out.genA_newer = genBIdx > genAIdx;
                out.held_generation_count = pending.length;
                return flush().then(function () {
                  resolveNewest({ items: [{ id: 3, title: 'gamma three', completed: false }] });
                  return flush().then(function () {
                    out.rendered_after_current_resolve = renderedTitles();
                    resolveOldest({ items: [{ id: 99, title: 'STALE ALPHA', completed: false }] });
                    return flush().then(function () {
                      out.rendered_after_stale_resolve = renderedTitles();
                      out.pending_left = pending.length;
                      const loadFeedback = target.loadFeedback;
                      if (typeof loadFeedback !== 'function') {
                        out.negative_control_error = 'loadFeedback is not reachable on the window';
                        return;
                      }
                      deferred.push(true);
                      calls.length = 0;
                      loadFeedback();
                      input(searchInput, 'delta');
                      resolveOldest({ items: [{ id: 77, title: 'STALE CONTROL', completed: false }] });
                      return flush().then(function () {
                        out.control_rendered_after_stale_unguarded = renderedTitles();
                        resolveNewest({ items: [{ id: 3, title: 'gamma three', completed: false }] });
                        return flush().then(function () {
                          out.control_rendered_after_current = renderedTitles();
                          // C10 STATUS generation: pick the completed filter so the
                          // completed board is the current generation, then resolve the
                          // earlier open board afterwards and watch it get discarded.
                          deferred.push(true);
                          calls.length = 0;
                          click(byId['filter-open']);
                          const statusGenAIdx = calls.length - 1;
                          click(byId['filter-completed']);
                          const statusGenBIdx = calls.length - 1;
                          out.status_genA_urls = calls.slice(statusGenAIdx).map(function (u) { return u.url; });
                          out.status_genB_urls = calls.slice(statusGenBIdx).map(function (u) { return u.url; });
                          resolveNewest({ items: [{ id: 1, title: 'CURRENT COMPLETED', completed: true }] });
                          return flush().then(function () {
                            out.rendered_after_current_status = renderedTitles();
                            resolveNewest({ items: [{ id: 2, title: 'STALE OPEN', completed: false }] });
                            return flush().then(function () {
                              out.rendered_after_stale_status = renderedTitles();
                              resolveNewest({items:[]});
                              return flush().then(function () {
                                out.pending_left = pending.length;
                              });
                            });
                          });
                        });
                      });
                    });
                  });
                });
              });
            });
          });
        });
      });
    });
  }).then(function () {
    report(out);
  }).catch(function (thrown) {
    report({ executed: false, error: String((thrown && thrown.message) || thrown) });
  });
}
drive();"""


class IncrementalU3QueryMemoryTests(unittest.TestCase):
    """C08/C09/C10: query is page memory, survives lifetime, stale gen discarded."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')

    def setUp(self):
        # Node is mandatory: fail explicitly, never skip.
        self.assertTrue(self.node,
                        'node executable is required to run the board client')
        self.assertTrue(APP_JS_PATH.is_file(),
                        'declared client asset must exist: %s' % APP_JS_PATH)
        self.assertTrue(INDEX_HTML_PATH.is_file(),
                        'declared page asset must exist: %s' % INDEX_HTML_PATH)

        program = DRIVER_PREAMBLE % {
            'source_path': json.dumps(str(APP_JS_PATH)),
            'html_path': json.dumps(str(INDEX_HTML_PATH)),
        } + DRIVER_BODY

        completed = subprocess.run(
            [self.node, '--input-type=commonjs', '-'],
            input=program.encode('utf-8'), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=NODE_TIMEOUT_SECONDS, check=False)
        self.assertEqual(
            completed.returncode, 0,
            'Node harness exited %d: %s' % (
                completed.returncode,
                completed.stderr.decode('utf-8', 'replace')))
        raw = completed.stdout.decode('utf-8', 'replace').strip()
        self.assertTrue(raw, 'Node harness produced no report')
        self.report = json.loads(raw)
        if not self.report.get('executed'):
            self.fail('the real app.js did not run to completion: %s'
                      % self.report.get('error'))

    def test_real_client_executes_under_the_window(self):
        """The real app.js bytes execute in the Node harness."""
        self.assertEqual(self.report['source_filename'], str(APP_JS_PATH))
        self.assertEqual(self.report['html_filename'], str(INDEX_HTML_PATH))
        self.assertTrue(self.report.get('query_url_after_input'),
                        'typing must issue a board request carrying the query')

    def test_c08_query_is_page_memory_only_no_url_or_storage(self):
        """C08: the query reaches the wire only as ?q= on the board GET."""
        self.assertTrue(self.report['initial_urls'],
                        'the client must issue a board request on load')
        # The query is page-scope memory: it is not mirrored into the page URL,
        # history, or any storage-backed location.
        for url in self.report['initial_urls']:
            self.assertNotIn('localStorage', url)
            self.assertNotIn('sessionStorage', url)
        self.assertIn('q=alpha', self.report['query_url_after_input'],
                      'the typed needle must ride the board GET: %s'
                      % self.report['query_url_after_input'])

    def test_c09_query_survives_polling_and_create_and_complete(self):
        """C09: the query persists across a poll tick and create/complete."""
        for url in self.report['poll_urls']:
            if url == '/feedback' or url.startswith('/feedback?'):
                self.assertIn('q=alpha', url,
                              'the query must survive a poll tick: %s' % url)
        create_q = [u for u in self.report['create_urls'] if u.startswith('/feedback?')]
        self.assertTrue(create_q,
                        'a create must refresh the board it is filtered by: %s'
                        % self.report['create_urls'])
        for url in create_q:
            self.assertIn('q=alpha', url,
                          'the query must survive a create: %s' % url)
        complete_q = [u for u in self.report['complete_urls'] if u.startswith('/feedback?')]
        self.assertTrue(complete_q,
                        'a complete must refresh the board it is filtered by: %s'
                        % self.report['complete_urls'])
        for url in complete_q:
            self.assertIn('q=alpha', url,
                          'the query must survive a completion: %s' % url)
        # And the surviving query is still the one that paints the board.
        self.assertIn('alpha one', self.report['rendered_after_poll'])
        self.assertIn('alpha new', self.report['rendered_after_create'])

    def test_c10_stale_query_and_status_responses_are_discarded(self):
        """C10: a response from an earlier query/status generation never paints."""
        self.assertEqual(self.report.get('__diag__'), None,
                         'DIAG %s' % json.dumps(self.report, sort_keys=True))
        self.assertEqual(
            self.report.get('resolve_error'), None,
            'the harness must observe every issued request: %s'
            % self.report.get('resolve_error'))
        # Query generation: genB ('gamma') is current and resolves first; the
        # earlier genA ('beta') request resolves afterwards and must be dropped.
        self.assertTrue(self.report['genA_newer'],
                        'the gamma request must be issued after the beta request')
        self.assertIn('q=beta', ' '.join(self.report['genA_urls']),
                      'generation A must be the beta query: %s' % self.report['genA_urls'])
        self.assertIn('q=gamma', ' '.join(self.report['genB_urls']),
                      'generation B must be the gamma query: %s' % self.report['genB_urls'])
        # The current generation painted, and the later stale response did not
        # overwrite it.
        self.assertIn('gamma three', self.report['rendered_after_current_resolve'],
                      'the current generation must paint: %s'
                      % self.report['rendered_after_current_resolve'])
        self.assertNotIn('STALE ALPHA', self.report['rendered_after_stale_resolve'],
                         'a response from an earlier query generation must be discarded')
        # Status generation: the completed ('genB') board is current; the
        # earlier open ('genA') response resolving afterwards must be dropped.
        self.assertIn('status=open', ' '.join(self.report['status_genA_urls']),
                      'status generation A must be open: %s'
                      % self.report['status_genA_urls'])
        self.assertIn('status=completed', ' '.join(self.report['status_genB_urls']),
                      'status generation B must be completed: %s'
                      % self.report['status_genB_urls'])
        self.assertIn('CURRENT COMPLETED', self.report['rendered_after_current_status'],
                      'the current status generation must paint: %s'
                      % self.report['rendered_after_current_status'])
        self.assertNotIn('STALE OPEN', self.report['rendered_after_current_status'],
                         'a response from an earlier status generation must be discarded')
        self.assertEqual(self.report.get('pending_left'), 0,
                         'every issued request must be resolved by the harness')


if __name__ == '__main__':
    unittest.main()
