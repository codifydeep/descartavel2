"""U3 C02 additive control: the DOM/state assertion catches stale-status paint."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import tests.test_incremental_u3 as u3


class U3ControlTests(unittest.TestCase):
    """Independent driver plus a reused C10 fixture."""

    def test_c02_stale_status_control(self):
        # C01: independent driver, alpha then blank, next GET must omit q.
        marker = 'STALE OPEN'
        driver_body = r"""function drive() {
  const out = { executed: true, error: null };
  try {
    vm.runInContext(SOURCE, context, { filename: SOURCE_PATH });
  } catch (thrown) {
    out.executed = false; out.error = String((thrown && thrown.message) || thrown);
  }
  if (!out.executed) { report(out); return; }
  deferred.push(true);
  input(searchInput, 'alpha');
  resolveNewest({ items: [] });
  flush().then(function () {
    calls.length = 0;
    input(searchInput, '');
    resolveNewest({ items: [] });
    return flush().then(function () {
      out.next_get_urls = getCalls();
      report(out);
    });
  });
}
drive();
"""
        node = shutil.which('node')
        self.assertTrue(node, 'node executable is required to run the board client')
        self.assertTrue(u3.APP_JS_PATH.is_file())
        self.assertTrue(u3.INDEX_HTML_PATH.is_file())
        program = u3.DRIVER_PREAMBLE % {
            'source_path': json.dumps(str(u3.APP_JS_PATH)),
            'html_path': json.dumps(str(u3.INDEX_HTML_PATH)),
        } + driver_body
        completed = subprocess.run(
            [node, '--input-type=commonjs', '-'],
            input=program.encode('utf-8'), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=u3.NODE_TIMEOUT_SECONDS, check=False)
        self.assertEqual(completed.returncode, 0,
                         completed.stderr.decode('utf-8', 'replace'))
        report = json.loads(completed.stdout.decode('utf-8', 'replace').strip())
        self.assertTrue(report.get('executed'), report.get('error'))
        gets = [u for u in report['next_get_urls'] if u.startswith('/feedback')]
        self.assertTrue(gets, 'a blank needle must still issue a board GET')
        self.assertFalse(any('q=' in u for u in gets),
                         'a blank needle must omit q: %s' % gets)

        # C02: reuse the frozen C10 fixture and read its recorded paint.
        fixture = u3.IncrementalU3QueryMemoryTests('test_c10_stale_query_and_status_responses_are_discarded')
        fixture.setUpClass()
        fixture.setUp()
        recorded = fixture.report['rendered_after_stale_status']
        self.assertNotIn(marker, recorded,
                         'stale generation title must not paint: %s' % recorded)
        self.assertNotIn(marker, fixture.report['rendered_after_current_status'],
                         'stale must not paint after the current response: %s'
                         % fixture.report['rendered_after_current_status'])
