import os
import re
import subprocess
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_JS = os.path.join(ROOT, "app", "static", "app.js")

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const body = src.replace(/^\s*loadSummary\(\);\s*$/m, '');
const stub = () => ({ value: '', textContent: '', hidden: false, classList: { toggle() {} },
  setAttribute() {}, addEventListener() {}, appendChild() {}, querySelector() { return null; },
  elements: {}, reset() {}, innerHTML: '' });
const elements = {};
const document = {
  getElementById(id) { if (!elements[id]) elements[id] = stub(); return elements[id]; },
  createElement() { return stub(); },
  createTextNode() { return stub(); },
  querySelector() { return null; },
};
const requests = [];
const fetch = (url) => { requests.push(url); return new Promise(() => {}); };
const context = { document, fetch, setTimeout() { return 0; }, clearTimeout() {},
  setInterval() { return 0; }, Promise, Object, String, Error, JSON, Math,
  console, encodeURIComponent, unescape };
const vm = require('vm');
vm.runInNewContext(body + '\n;globalThis.__api = { setFilter: function (f) { currentFilter = f; },' +
  ' setSearch: function (s) { currentSearch = s; }, feedbackUrl: feedbackUrl };', context);
const api = context.__api;
const cases = JSON.parse(process.argv[2]);
const out = {};
for (const c of cases) {
  api.setFilter(c.filter);
  api.setSearch(c.search);
  out[c.name] = api.feedbackUrl(c.filter);
}
process.stdout.write(JSON.stringify(out));
"""

CASES = [
    {"name": "open_search", "filter": "open", "search": "Detail UI"},
    {"name": "all_search", "filter": "all", "search": "Detail UI"},
    {"name": "open_blank", "filter": "open", "search": "   "},
]


def run_cases():
    import json

    result = subprocess.run(
        ["node", "-e", HARNESS, APP_JS, json.dumps(CASES)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


class FeedbackUrlCompositionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.urls = run_cases()

    def test_open_filter_with_search_uses_ampersand_before_q(self):
        url = self.urls["open_search"]
        self.assertEqual(url, "/feedback?status=open&q=Detail%20UI")
        self.assertEqual(url.count("?"), 1)

    def test_all_filter_with_search_uses_single_question_mark(self):
        url = self.urls["all_search"]
        self.assertEqual(url, "/feedback?q=Detail%20UI")
        self.assertEqual(url.count("?"), 1)

    def test_open_filter_with_blank_search_has_no_extra_separator(self):
        url = self.urls["open_blank"]
        self.assertEqual(url, "/feedback?status=open")
        self.assertNotIn("&", url)


if __name__ == "__main__":
    unittest.main()
