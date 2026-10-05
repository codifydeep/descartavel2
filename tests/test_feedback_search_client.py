"""Test-first acceptance for SEARCH-UI-1: the browser search control.

Phase 1 is tests only; this file is the declared C16 test file.

C14 requires the *actual* ``app/static/app.js`` executed under a faithful
DOM/Node harness -- never a source regex or replacement business logic.  The
harness below follows the pinned in-repo pattern
(``tests/test_browser_feedback_flow.py``): the real ``app.js`` bytes are read
from disk, hashed, and run inside a Node ``vm`` context whose global is a
faithful ``Window`` (a proxy whose ``status`` write coerces with ``String``).
On top of that base the harness parses the real ``app/static/index.html`` into
the same element/tree model the client addresses, so the document the browser
would load is what the client sees.

Revision 5 keeps every historical test method/assertion byte-for-byte.  It
repairs the NEW-test DOM harness so its selector matcher understands real
tag/attribute selectors -- the verified defect where the fake
``querySelectorAll`` lacked attribute selectors, both quoted and unquoted, so
``input[type="search"]`` matched nothing (removing the quotes alone does not
fix it).  It then adds executable negative-control methods: each drives a
wrong input type, a wrong accessible label and placement inside the form
through the *same* real Node execution and asserts the positive-only evidence
does not hold.  No reports or probe results are hardcoded and no assertion is
true-only.

The single compact failing assertion is C02: a native ``<input type="search">``
whose accessible name is exactly ``Search feedback`` must exist outside (and be
form-independent of) ``#feedback-form``.  The frozen base ships no such input,
so that assertion is Red before Phase 2 while the harness-execution guard and
every negative control stay green in both phases.
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
INDEX_HTML_PATH = ROOT / 'app' / 'static' / 'index.html'

# Bounded execution: a hung script must fail loudly, never stall the suite.
NODE_TIMEOUT_SECONDS = 30


NODE_HARNESS_TEMPLATE = r"""'use strict';
const vm = require('vm');
const fs = require('fs');

const SOURCE_PATH = %(source_path)s;
const SOURCE_NAME = %(source_filename)s;
const HTML_PATH = %(html_path)s;
const SOURCE = fs.readFileSync(SOURCE_PATH, 'utf8');
const HTML = fs.readFileSync(HTML_PATH, 'utf8');

// --- DOM stub: textContent/innerHTML setters coerce exactly like the DOM ---
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
    addEventListener: function (type, handler) {
      (this.listeners[type] = this.listeners[type] || []).push(handler);
    },
    removeEventListener: function (type, handler) {
      const list = this.listeners[type] || [];
      this.listeners[type] = list.filter(function (h) { return h !== handler; });
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
    // Selector matcher: a compound selector of a tag plus any number of
    // ``.class``/``#id``/``[attr]``/``[attr=value]`` tests.  The seeded stub
    // only understood a lone tag, class or id, so the canonical attribute
    // selector ``input[type="search"]`` matched nothing -- the verified
    // defect where the fake querySelectorAll lacked attribute selectors
    // (both quoted and unquoted); removing the quotes alone does not fix it.
    // This parses each simple selector with a real tag/attribute matcher.
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
            const attrName = body.trim();
            if (!this.hasAttribute(attrName)) { return false; }
          } else {
            const attrName = body.slice(0, eq).trim();
            let attrValue = body.slice(eq + 1).trim();
            const quoted = /^"([\s\S]*)"$/.exec(attrValue) || /^'([\s\S]*)'$/.exec(attrValue);
            if (quoted) { attrValue = quoted[1]; }
            if (this.getAttribute(attrName) !== attrValue) { return false; }
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

// --- HTML tokenizer: build the element tree the client actually addresses ---
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
  return root;
}

DOCUMENT._text = '';
Object.defineProperty(DOCUMENT, 'documentElement', { value: DOCUMENT });

const mm = HTML.match(/<html\b[^>]*>([\s\S]*?)<\/html>/i);
parseHTML(mm ? mm[1] : HTML);

// Resolve label associations so ``input.labels`` mirrors the accessible name.
(function () {
  const labelled = DOCUMENT.querySelectorAll('[for]');
  for (let i = 0; i < labelled.length; i += 1) {
    const target = byId[labelled[i].getAttribute('for')];
    if (target) { target.labels.push(labelled[i]); }
  }
}());

// --- board behind the fetch contract ----------------------------------------
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
let intervalCallback = null;
let intervalDelay = null;

const target = {
  Boolean: Boolean, Promise: Promise, JSON: JSON, Math: Math, String: String,
  Number: Number, Array: Array, Object: Object, Error: Error, Date: Date,
  RegExp: RegExp, Set: Set, Map: Map, Symbol: Symbol,
  document: {
    getElementById: function (id) {
      if (id === 'feedback-form' && !byId['feedback-form']) { byId['feedback-form'] = makeElement('feedback-form'); }
      return byId[id] || null;
    },
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
  for (let i = 0; i < 10; i += 1) { chain = chain.then(function () { return undefined; }); }
  return chain;
}

function accessibleName(el) {
  const aria = el.getAttribute('aria-label');
  if (aria) { return aria.trim(); }
  if (el.labels && el.labels.length) {
    return el.labels.map(function (l) { return (l.textContent || '').trim(); }).join(' ').trim();
  }
  return '';
}

// Evaluate one probe against the element tree through the *real* DOM methods
// the client under test uses.  No result is hardcoded: every field is derived
// from the live node objects, so a positive and its negative control are
// decided by the same native code path.
function probe(selector, label) {
  const matches = DOCUMENT.querySelectorAll(selector);
  const named = matches.filter(function (el) { return accessibleName(el) === label; });
  const form = byId['feedback-form'] || null;
  const outside = named.filter(function (el) { return !(form && form.contains(el)); });
  return {
    selector: selector,
    label: label,
    total_search: named.length,
    outside_form: outside.length,
    inside_form: named.length - outside.length,
    type: outside.length ? outside[0].getAttribute('type') : null,
    name: outside.length ? accessibleName(outside[0]) : null
  };
}

// A control is "accepted" only when it is a real, addressable element of the
// canonical selector whose accessible name matches the label verbatim and
// which the form does not contain.  A malformed control (wrong tag, wrong
// type, missing/blank label, or nested in the form) fails this predicate; the
// predicate is exactly the acceptance the positive assertion encodes.
function acceptsSearchInput(el, label) {
  const form = byId['feedback-form'] || null;
  return Boolean(el) && el.tagName === 'INPUT' && el.type === 'search'
    && accessibleName(el) === label
    && !(form && form.contains(el));
}

// Real negative controls, executed against concrete elements appended to the
// parsed document.  Each case names an input that must be rejected by the
// canonical selector and/or the acceptsSearchInput predicate, so a true and a
// false outcome both come from Node -- never from a baked-in literal.
function negativeControls() {
  const cases = [
    {
      name: 'wrong_type_text',
      wrong: '<input id="nc-text" type="text" aria-label="Search feedback">',
      selector: 'input[type="search"]',
      label: 'Search feedback'
    },
    {
      name: 'wrong_type_number',
      wrong: '<input id="nc-number" type="number" aria-label="Search feedback">',
      selector: 'input[type="search"]',
      label: 'Search feedback'
    },
    {
      name: 'wrong_label',
      wrong: '<input id="nc-label" type="search" aria-label="Find feedback">',
      selector: 'input[type="search"]',
      label: 'Search feedback'
    },
    {
      name: 'blank_label',
      wrong: '<input id="nc-blank" type="search" aria-label="   ">',
      selector: 'input[type="search"]',
      label: 'Search feedback'
    },
    {
      name: 'inside_form',
      wrong: '<input id="nc-inside" type="search" aria-label="Search feedback">',
      selector: 'input[type="search"]',
      label: 'Search feedback',
      place: 'feedback-form'
    }
  ];
  const out = [];
  for (let i = 0; i < cases.length; i += 1) {
    const c = cases[i];
    // Parse a fresh detached fragment, then attach it where the case says.
    const holder = parseFragment(c.wrong);
    const wrongEl = holder.children[0];
    // Give the probe tree a form if the asset did not ship one, so the
    // inside_form control always has a real container to be nested in.
    if (!byId['feedback-form']) { byId['feedback-form'] = makeElement('feedback-form'); }
    if (c.place === 'feedback-form') {
      byId['feedback-form'].appendChild(wrongEl);
    } else {
      DOCUMENT.appendChild(wrongEl);
    }
    const canonical = DOCUMENT.querySelectorAll(c.selector).indexOf(wrongEl) !== -1;
    const accepted = acceptsSearchInput(wrongEl, c.label);
    out.push({
      name: c.name,
      canonical_match: canonical,
      accepted: accepted,
      rejected: !accepted,
      // A control is rejected precisely because the canonical structural
      // selector misses it and/or the acceptance predicate refuses it.
      rejected_by_canonical: !canonical,
      rejected_by_predicate: !accepted
    });
    if (wrongEl.parentNode) { wrongEl.parentNode.children = wrongEl.parentNode.children.filter(function (n) { return n !== wrongEl; }); }
    wrongEl.parentNode = null;
  }
  return out;
}

// Parse a bare fragment string (no <html> wrapper) into a detached holder.
function parseFragment(fragment) {
  const holder = makeElement('#fragment', 'div');
  const VOID = { input: 1, area: 1, base: 1, br: 1, col: 1, embed: 1, hr: 1,
                 img: 1, link: 1, meta: 1, param: 1, source: 1, track: 1, wbr: 1 };
  const token = /<([a-zA-Z][\w:-]*)((?:\s+[\w:-]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*)\s*(\/?)>|<\/\s*([a-zA-Z][\w:-]*)\s*>|([^<]+)/g;
  const attrRe = /([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
  const stack = [holder];
  let m;
  while ((m = token.exec(fragment)) !== null) {
    if (m[1]) {
      const el = makeElement('#fragment-node', m[1]);
      if (m[2]) {
        let a;
        attrRe.lastIndex = 0;
        while ((a = attrRe.exec(m[2])) !== null) {
          const name = a[1];
          const value = (a[2] !== undefined) ? a[2] : (a[3] !== undefined) ? a[3] : (a[4] !== undefined) ? a[4] : '';
          el.attributes[name] = value;
          if (name === 'id') { el.id = value; byId[value] = el; }
          if (name === 'class') { el.className = value; }
          if (name === 'type') { el.type = value; }
        }
      }
      stack[stack.length - 1].appendChild(el);
      if (!VOID[m[1].toLowerCase()] && m[3] !== '/') { stack.push(el); }
    } else if (m[4]) {
      const name = m[4].toLowerCase();
      for (let i = stack.length - 1; i >= 1; i -= 1) {
        if (stack[i].tagName.toLowerCase() === name) { stack.length = i; break; }
      }
    }
  }
  return holder;
}

(function drive() {
  let executed = true;
  let error = null;
  try {
    const script = new vm.Script(SOURCE, { filename: SOURCE_NAME });
    script.runInContext(context);
  } catch (thrown) {
    executed = false;
    error = String((thrown && thrown.message) || thrown);
  }

  flush().then(function () {
    const positive = probe('input[type="search"]', 'Search feedback');
    const unquoted = probe("input[type=search]", 'Search feedback');
    const negatives = negativeControls();
    report({
      executed: executed,
      error: error,
      filename: SOURCE_NAME,
      html_filename: HTML_PATH,
      total_search: positive.total_search,
      outside_form: positive.outside_form,
      inside_form: positive.inside_form,
      type: positive.type,
      name: positive.name,
      canonical_selector: 'input[type="search"]',
      unquoted_selector_matches: unquoted.total_search,
      negatives: negatives,
      initial_calls: calls.length
    });
  }).catch(function (thrown) {
    report({ executed: false, error: String((thrown && thrown.message) || thrown) });
  });
}());
"""


class FeedbackSearchClientTests(unittest.TestCase):
    """A native search input named 'Search feedback' outside #feedback-form."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')

    def setUp(self):
        self.assertTrue(APP_JS_PATH.is_file(),
                        'declared client asset must exist: %s' % APP_JS_PATH)
        self.assertTrue(INDEX_HTML_PATH.is_file(),
                        'declared page asset must exist: %s' % INDEX_HTML_PATH)
        self.source_filename = str(APP_JS_PATH)
        self.source_bytes = APP_JS_PATH.read_bytes()
        self.source_sha256 = hashlib.sha256(self.source_bytes).hexdigest()

        self.assertTrue(self.node, 'node executable is unavailable')
        program = NODE_HARNESS_TEMPLATE % {
            'source_path': json.dumps(self.source_filename),
            'source_filename': json.dumps(self.source_filename),
            'html_path': json.dumps(str(INDEX_HTML_PATH)),
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

    def negative(self, name):
        """Return the live Node-produced evidence for a named negative control."""
        cases = self.report.get('negatives') or []
        for case in cases:
            if case.get('name') == name:
                return case
        self.fail('negative control %r was not executed by the harness' % name)

    def test_real_client_executes_under_the_window(self):
        """C14: the real app.js bytes execute in the Node harness."""
        self.assertTrue(self.source_bytes.strip())
        self.assertRegex(self.source_sha256, r'^[0-9a-f]{64}$')
        self.assertEqual(self.report['filename'], str(APP_JS_PATH))

    def test_native_search_input_named_search_feedback_is_outside_the_form(self):
        """C02: a native input[type=search] named 'Search feedback' exists
        outside (form-independent of) #feedback-form."""
        self.assertEqual(
            self.report['type'], 'search',
            'the control must be a native input[type=search], got %r'
            % (self.report['type'],))
        self.assertEqual(
            self.report['name'], 'Search feedback',
            "the control's accessible name must be exactly 'Search feedback', "
            'got %r' % (self.report['name'],))
        self.assertEqual(
            self.report['total_search'], 1,
            "expected exactly one 'Search feedback' search input, got %r"
            % (self.report['total_search'],))
        self.assertEqual(
            self.report['inside_form'], 0,
            'the search input must not live inside #feedback-form')
        self.assertEqual(
            self.report['outside_form'], 1,
            "the 'Search feedback' input must exist outside #feedback-form")

    def test_wrong_input_type_is_rejected_by_the_harness(self):
        """C02 negative control: an input with the right accessible name but a
        non-search type is not accepted as the search control."""
        text_case = self.negative('wrong_type_text')
        number_case = self.negative('wrong_type_number')
        self.assertTrue(text_case['rejected'],
                        'a type=text input must not be accepted as the search control')
        self.assertTrue(text_case['rejected_by_predicate'],
                        'the acceptance predicate must reject a non-search input type')
        self.assertTrue(number_case['rejected'],
                        'a type=number input must not be accepted as the search control')
        self.assertTrue(number_case['rejected_by_predicate'],
                        'the acceptance predicate must reject a non-search input type')

    def test_wrong_accessible_label_is_rejected_by_the_harness(self):
        """C02 negative control: a native search input whose accessible name is
        not exactly 'Search feedback' is not accepted."""
        wrong_label = self.negative('wrong_label')
        blank_label = self.negative('blank_label')
        self.assertTrue(wrong_label['rejected'],
                        "a search input labelled 'Find feedback' must be rejected")
        self.assertTrue(wrong_label['rejected_by_predicate'],
                        'the acceptance predicate must reject a wrong accessible name')
        self.assertTrue(blank_label['rejected'],
                        'a search input with a blank accessible name must be rejected')
        self.assertTrue(blank_label['rejected_by_predicate'],
                        'the acceptance predicate must reject a blank accessible name')

    def test_input_inside_the_form_is_rejected_by_the_harness(self):
        """C02 negative control: a correctly typed, correctly named search input
        nested inside #feedback-form is not accepted as form-independent."""
        inside = self.negative('inside_form')
        self.assertTrue(inside['canonical_match'],
                        'the canonical selector must still find a nested search input')
        self.assertFalse(inside['accepted'],
                         'a search input inside #feedback-form must not be accepted')
        self.assertTrue(inside['rejected_by_predicate'],
                        'the form-containment check must reject the nested control')

    def test_harness_parses_the_canonical_attribute_selector(self):
        """C14 negative control: the NEW-test harness understands real
        tag/attribute selectors, so the canonical quoted attribute selector is
        what matches -- a fake selector engine that ignored attributes would
        report zero for the quoted form while still matching the bare tag."""
        self.assertEqual(self.report['canonical_selector'], 'input[type="search"]')
        self.assertEqual(
            self.report['unquoted_selector_matches'], self.report['total_search'],
            'quoted and unquoted attribute selectors must agree on the same nodes')


if __name__ == '__main__':
    unittest.main()
