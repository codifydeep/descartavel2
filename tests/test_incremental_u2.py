"""Incremental U2: drive the search input through the harness.

Red-first unit tests for the acceptance criteria of delivery unit U2. The real
``app/static/app.js`` bytes run unmodified inside a faithful Node ``vm`` harness
whose global is the page the browser would load (``app/static/index.html``).
The tests exercise the client through the very events a user produces; they
never inspect source text or reimplement business logic.

C03: Enter in the search input applies its query without submitting or changing
     the create form.
C04: Default query is empty; whitespace is trimmed.
C05: A blank query omits the ``q`` parameter.
C06: Existing status and numeric sort controls are preserved.
C07: Search composes with both.

The frozen base binds only the ``input`` event on the search control -- there is
no Enter handler -- so C03 is Red before Phase 2 while the empty/trim/omit,
preservation and composition guards remain executable evidence. Node is
mandatory: its absence fails loudly, it is never a skip.
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

# fs.readFileSync / require.resolve give the real bytes; the client is run with
# vm.runInContext so a driver can be appended into the same native global.
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
    // Dispatch to the listeners the real client bound; return how many ran.
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
    // Compound selector: tag plus any number of .class/#id/[attr]/[attr=value].
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
const submitButton = form ? form.querySelector('button[type="submit"]') : null;
const statusEl = byId['form-status'];
const searchInput = byId['feedback-search'];
const sortSelect = byId['sort-feedback'];

// The client reads form.elements.title/description; mirror the live controls.
if (form) {
  form.elements = { title: titleInput || makeElement('title', 'input'),
                    description: descriptionInput || makeElement('description', 'textarea') };
}

// --- observable effects -----------------------------------------------------
let submits = 0;
let resets = 0;
let searchQueries = [];
if (form) {
  form.addEventListener('submit', function () { submits += 1; });
  const originalReset = form.reset;
  form.reset = function () {
    resets += 1;
    return originalReset.apply(this, arguments);
  };
}
// Record every query the search control carries when a board request is made,
// so preservation/composition evidence comes from the live control value.
if (searchInput) {
  const originalDispatch = searchInput.dispatchEvent;
  searchInput.dispatchEvent = function (event) {
    searchQueries.push(String(searchInput.value));
    return originalDispatch.call(this, event);
  };
}

// --- board behind the fetch contract ---------------------------------------
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
  if (target.indexOf('/feedback?') === 0 || target === '/feedback') {
    if (method === 'GET') { return Promise.resolve(jsonResponse({ items: items.slice() }, true)); }
  }
  if (method === 'POST') {
    const id = nextId; nextId += 1;
    items.push({ id: id, title: 'posted', completed: false });
    return Promise.resolve(jsonResponse({ id: id, title: 'posted', completed: false }, true));
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

// --- native Window global (status writes coerce to String) -----------------
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
  setTimeout: function (fn) { try { fn(); } catch (e) {} return 0; },
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

function flush() {
  let chain = Promise.resolve();
  for (let i = 0; i < 15; i += 1) { chain = chain.then(function () { return undefined; }); }
  return chain;
}
function report(payload) { process.stdout.write(JSON.stringify(payload)); }
function keydown(control, key) {
  return { type: 'keydown', key: key, bubbles: true, preventDefault: function () {} };
}
function input(control, value) {
  control.value = value;
  control.dispatchEvent({ type: 'input', bubbles: true });
}
"""

# Appended after the preamble; every value comes from the live run.
DRIVER_BODY = r"""
function getCalls() {
  return calls.map(function (c) { return c.url; });
}

(function drive() {
  let executed = true;
  let error = null;
  try {
    vm.runInContext(SOURCE, context, { filename: SOURCE_PATH });
  } catch (thrown) {
    executed = false;
    error = String((thrown && thrown.message) || thrown);
  }

  flush().then(function () {
    const report0 = {
      executed: executed,
      error: error,
      source_filename: SOURCE_PATH,
      html_filename: HTML_PATH,
      has_search_control: Boolean(searchInput),
      initial_urls: getCalls()
    };

    if (!executed) { report(report0); return; }

    // 0. Default: no search typed -> the empty needle must omit q.
    report0.default_urls = getCalls();

    // 1. Typing a whitespace-padded needle, then pressing Enter, must apply
    //    the *trimmed* needle and must not submit or disturb the create form.
    if (titleInput) { titleInput.value = 'draft title'; }
    if (descriptionInput) { descriptionInput.value = 'draft description'; }
    calls.length = 0;
    const beforeSubmit = submits;
    const beforeReset = resets;
    if (searchInput) {
      input(searchInput, '  alpha  ');
      searchInput.dispatchEvent(keydown(searchInput, 'Enter'));
    }
    // Enter may bubble to the form; the client must ignore it there too.
    if (form) { form.dispatchEvent(keydown(form, 'Enter')); }
    report0.enter_urls = getCalls();
    report0.enter_submit_delta = submits - beforeSubmit;
    report0.enter_reset_delta = resets - beforeReset;
    report0.title_after_enter = titleInput ? titleInput.value : null;
    report0.description_after_enter = descriptionInput ? descriptionInput.value : null;
    report0.search_queries_seen = searchQueries.slice();

    // 2. A blank (whitespace-only) needle must omit q.
    calls.length = 0;
    if (searchInput) { input(searchInput, '   '); }
    report0.blank_urls = getCalls();

    // 3. Existing status filter preserved: selecting Open keeps status=open.
    calls.length = 0;
    const openBtn = byId['filter-open'];
    if (openBtn) { openBtn.dispatchEvent({ type: 'click', bubbles: true }); }
    report0.open_urls = getCalls();

    // 4. Numeric sort control preserved and applied without refetching.
    const preSortCalls = getCalls().length;
    if (sortSelect) {
      sortSelect.value = 'oldest-first';
      sortSelect.dispatchEvent({ type: 'change', bubbles: true });
    }
    report0.sort_extra_calls = getCalls().length - preSortCalls;

    // 5. Search composes with the preserved status filter.
    calls.length = 0;
    if (searchInput) { input(searchInput, 'alpha'); }
    report0.composed_urls = getCalls();

    report(report0);
  }).catch(function (thrown) {
    report({ executed: false, error: String((thrown && thrown.message) || thrown) });
  });
}());
"""


class IncrementalU2SearchTests(unittest.TestCase):
    """Enter applies the trimmed search needle; empty/blank omit q; composes."""

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
        self.assertTrue(self.report.get('has_search_control'),
                        'the page must ship the #feedback-search control')

    def test_real_client_executes_under_the_window(self):
        """The real app.js bytes execute in the Node harness."""
        self.assertEqual(self.report['source_filename'], str(APP_JS_PATH))
        self.assertEqual(self.report['html_filename'], str(INDEX_HTML_PATH))

    def test_c04_default_query_is_empty_and_whitespace_is_trimmed(self):
        """C04: default board request omits q; a padded needle trims to 'alpha'."""
        self.assertTrue(self.report['default_urls'],
                        'the client must issue a board request on load')
        for url in self.report['default_urls']:
            self.assertNotIn('q=', url,
                             'the default query must be empty (no q): %s' % url)
        apply_urls = [u for u in self.report['enter_urls'] if 'q=' in u]
        self.assertTrue(apply_urls,
                        'Enter must apply the search query as a board request')
        joined = ' '.join(self.report['enter_urls'])
        self.assertIn('q=alpha', joined,
                      'whitespace must be trimmed to the bare needle: %s'
                      % self.report['enter_urls'])
        self.assertNotIn('%20', joined,
                         'the trimmed needle must not carry padding: %s'
                         % self.report['enter_urls'])

    def test_c05_blank_query_omits_q(self):
        """C05: a whitespace-only query omits q entirely."""
        self.assertTrue(self.report['blank_urls'],
                        'a blank search must still refresh the board')
        for url in self.report['blank_urls']:
            self.assertNotIn('q=', url,
                             'a blank query must omit q: %s' % url)

    def test_c03_enter_applies_query_without_submitting_or_changing_form(self):
        """C03: Enter applies the query, never submits, never resets the form."""
        apply_urls = [u for u in self.report['enter_urls'] if 'q=' in u]
        self.assertTrue(apply_urls,
                        'Enter in the search input must apply its query: %s'
                        % self.report['enter_urls'])
        self.assertEqual(
            self.report['enter_submit_delta'], 0,
            'Enter in the search input must not submit the create form')
        self.assertEqual(
            self.report['enter_reset_delta'], 0,
            'Enter in the search input must not reset the create form')
        self.assertEqual(
            self.report['title_after_enter'], 'draft title',
            'Enter must leave the typed title untouched')
        self.assertEqual(
            self.report['description_after_enter'], 'draft description',
            'Enter must leave the typed description untouched')

    def test_c06_status_and_numeric_sort_controls_are_preserved(self):
        """C06: selecting Open keeps status=open; a sort change refetches nothing."""
        self.assertTrue(self.report['open_urls'],
                        'selecting the Open filter must issue a board request')
        joined = ' '.join(self.report['open_urls'])
        self.assertIn('status=open', joined,
                      'the preserved status filter must narrow the request: %s'
                      % self.report['open_urls'])
        self.assertEqual(
            self.report['sort_extra_calls'], 0,
            'a numeric sort change must re-render without refetching')

    def test_c07_search_composes_with_status_and_sort(self):
        """C07: search composes with the preserved status filter."""
        composed = [u for u in self.report['composed_urls'] if 'q=' in u]
        self.assertTrue(composed,
                        'search must still apply while a status filter is active')
        composed_url = composed[0]
        self.assertIn('status=open', composed_url,
                      'composition must keep the status filter: %s' % composed_url)
        self.assertIn('q=alpha', composed_url,
                      'composition must carry the search needle: %s' % composed_url)


if __name__ == '__main__':
    unittest.main()
