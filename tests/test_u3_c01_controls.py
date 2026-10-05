"""C01 controls: clearing the search omits q=; C10 stale status is discarded."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import tests.test_incremental_u3 as u3


class U3C01ControlTests(unittest.TestCase):
    """Additive controls for query clearing (C01) and stale status (C02)."""

    def test_c01_query_clearing_control(self):
        node = shutil.which('node')
        self.assertTrue(node, 'node executable is required to run the board client')
        root = Path(__file__).resolve().parents[1]
        app_js = root / 'app' / 'static' / 'app.js'
        index_html = root / 'app' / 'static' / 'index.html'
        self.assertTrue(app_js.is_file(), 'declared client asset must exist: %s' % app_js)
        self.assertTrue(index_html.is_file(), 'declared page asset must exist: %s' % index_html)

        body = r"""function drive() {
  const out = { executed: true, error: null };
  try {
    vm.runInContext(SOURCE, context, { filename: SOURCE_PATH });
  } catch (thrown) {
    out.executed = false;
    out.error = String((thrown && thrown.message) || thrown);
    report(out);
    return;
  }
  items.push({ id: 1, title: 'alpha one', completed: false });
  flush().then(function () {
    calls.length = 0;
    input(searchInput, 'alpha');
    const typed = getCalls();
    out.typed_urls = typed;
    const typedQ = typed.filter(function (u) { return u.indexOf('q=') !== -1; });
    out.typed_url = typedQ.length ? typedQ[typedQ.length - 1] : null;
    input(searchInput, '');
    const cleared = getCalls().slice(typed.length);
    out.cleared_urls = cleared;
    const nextBoard = cleared.filter(function (u) {
      return u === '/feedback' || u.indexOf('/feedback?') === 0;
    });
    out.next_board_url = nextBoard.length ? nextBoard[nextBoard.length - 1] : null;
    return flush().then(function () { report(out); });
  }).catch(function (thrown) {
    report({ executed: false, error: String((thrown && thrown.message) || thrown) });
  });
}
drive();"""
        program = u3.DRIVER_PREAMBLE % {
            'source_path': json.dumps(str(app_js)),
            'html_path': json.dumps(str(index_html)),
        } + body
        completed = subprocess.run(
            [node, '--input-type=commonjs', '-'],
            input=program.encode('utf-8'), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=u3.NODE_TIMEOUT_SECONDS, check=False)
        self.assertEqual(
            completed.returncode, 0,
            'Node harness exited %d: %s' % (
                completed.returncode,
                completed.stderr.decode('utf-8', 'replace')))
        raw = completed.stdout.decode('utf-8', 'replace').strip()
        self.assertTrue(raw, 'Node harness produced no report')
        report = json.loads(raw)
        self.assertTrue(report.get('executed'),
                        'the real app.js did not run to completion: %s'
                        % report.get('error'))
        self.assertTrue(report.get('typed_url'),
                        'typing must issue a board request carrying the query')
        self.assertIn('q=alpha', report['typed_url'],
                      'the typed needle must ride the board GET: %s' % report['typed_url'])
        self.assertTrue(report.get('next_board_url'),
                        'clearing the field must issue a board request: %s'
                        % report.get('cleared_urls'))
        self.assertNotIn('q=', report['next_board_url'],
                         'clearing the search must omit q= from the next board GET: %s'
                         % report['next_board_url'])

        case = u3.IncrementalU3QueryMemoryTests('test_c10_stale_query_and_status_responses_are_discarded')
        case.setUpClass()
        case.setUp()
        self.assertNotIn('STALE OPEN', case.report['rendered_after_stale_status'],
                         'a stale status response must never paint the board: %s'
                         % case.report['rendered_after_stale_status'])
