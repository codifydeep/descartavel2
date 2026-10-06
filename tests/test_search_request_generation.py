"""C10: a stale same-view board GET must never repaint a newer board.

Tests-only Phase 1 for the C10 regression correction.  The real
``app/static/app.js`` bytes run unmodified inside the faithful DOM/Node harness
that ``tests/test_incremental_u3.py`` already proves: ``DRIVER_PREAMBLE`` is
imported as its literal from that module and is never edited or duplicated here.
Every asserted value is read from the live run; no source text is inspected and
no business logic is reimplemented.

Acceptance (the freshly authorised C10 correction):

* Request-generation guard.  Two board GETs for the *identical* view -- same
  query, same status -- are issued; the newer one resolves first and the older
  one resolves afterwards.  The newer rows must remain painted; the older rows
  must never repaint.  The shipped guard only compares ``currentFilter`` and
  ``currentSearchNeedle()``, both of which are unchanged across these two
  requests, so the earlier response is painted over the newer board today: Red.
* A query/status round-trip back to the original view must not resurrect the
  generation issued before the round-trip.  One request is held before the
  round-trip, a fresher request for the *same* original view is issued after it,
  the fresher response paints, and the pre-round-trip response resolving later
  must be discarded.
* The preserved query/status identity guards still discard a response whose
  view has since changed (control), and every other proven behaviour --
  polling, create/complete refresh, summary, drafts, pending guard, Escape and
  accessibility -- is left to the existing suite, which this file does not
  touch.

Node is mandatory; its absence fails loudly, it is never a skip.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

import tests.test_incremental_u3 as u3


ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = ROOT / 'app' / 'static' / 'app.js'
INDEX_HTML_PATH = ROOT / 'app' / 'static' / 'index.html'

# A hung driver must fail loudly, never stall the suite.
NODE_TIMEOUT_SECONDS = 30

# The driver is appended after the imported literal preamble; it reads only the
# live sandbox globals the preamble defines (SOURCE, context, items, calls,
# pending, deferred, resolveNewest/resolveOldest, flush, renderedTitles,
# input/click, getCalls, feedbackList, byId, ...).
DRIVER_BODY = r"""function prelude() {
  // Seed a board and let the client's own initial load settle, so the driver
  // starts from a quiet, deterministic state.  The initial board GET resolves
  // immediately (nothing is deferred yet), so no request is left held here.
  items.push({ id: 1, title: 'alpha one', completed: false });
  items.push({ id: 2, title: 'beta two', completed: false });
  items.push({ id: 3, title: 'gamma three', completed: false });
  return flush();
}

function drive() {
  let executed = true;
  let error = null;
  try {
    vm.runInContext(SOURCE, context, { filename: SOURCE_PATH });
  } catch (thrown) {
    executed = false;
    error = String((thrown && thrown.message) || thrown);
  }
  const out = { executed: executed, error: error, source_filename: SOURCE_PATH };
  if (!executed) { report(out); return; }

  prelude().then(function () {
    // -- Part 1: identical same-view generation race -------------------------
    // Every GET is held, so the driver alone decides resolution order.
    deferred.push(true);
    calls.length = 0;
    // Issue two board GETs for the identical view: the same filter (All) and
    // the same empty needle, so both requests carry exactly '/feedback'.  The
    // first is issued by a poll tick, the second by an explicit refresh -- two
    // distinct generations of the same view.
    if (intervalCallback) { intervalCallback(); }
    const loadFeedback = target.loadFeedback;
    if (typeof loadFeedback !== 'function') {
      out.negative_control_error = 'loadFeedback is not reachable on the window';
      report(out);
      return;
    }
    loadFeedback();
    out.same_view_urls = getCalls().filter(function (u) {
      return u === '/feedback' || u.indexOf('/feedback?') === 0;
    });
    out.same_view_distinct_requests = out.same_view_urls.length === 2;
    out.same_view_query_identical =
      out.same_view_urls.length === 2 && out.same_view_urls[0] === out.same_view_urls[1];
    out.held_after_issue = pending.length;

    return flush().then(function () {
      // Resolve the newer request first: it paints the newest board.
      out.resolved_newer =
        resolveNewest({ items: [{ id: 20, title: 'NEWEST ROWS', completed: false }] });
      return flush().then(function () {
        out.rendered_after_newest = renderedTitles();
        // Resolve the older, stale request afterwards: it must be discarded.
        out.resolved_older =
          resolveOldest({ items: [{ id: 90, title: 'STALE OLDER ROWS', completed: false }] });
        return flush().then(function () {
          out.rendered_after_older = renderedTitles();
          out.pending_left_same_view = pending.length;

          // -- Part 2: round-trip back to the original view -----------------
          // Reset the held flag so the round-trip's own resolution is
          // controlled; drain anything still held first.
          deferred.length = 0;
          while (pending.length) { resolveNewest({ items: [] }); }
          return flush().then(function () {
            deferred.push(true);
            calls.length = 0;
            // One GET in the original view (All / no query) is held.
            loadFeedback();
            const rtGenAIdx = calls.length - 1;
            // Walk the view away and back: open then completed then all, with a
            // typed needle on the way out and a blank needle on the way home.
            // Each waypoint's own held GET is resolved as its successor is
            // issued, so only the two original-view generations remain held.
            click(byId['filter-open']);
            resolveOldest({ items: [] });
            click(byId['filter-completed']);
            resolveOldest({ items: [] });
            input(searchInput, 'away');
            resolveOldest({ items: [] });
            input(searchInput, '');
            resolveOldest({ items: [] });
            click(byId['filter-all']);
            resolveOldest({ items: [] });
            // A fresher GET for the *same* original view is issued after the
            // round-trip; it is the current generation for All / no query.
            loadFeedback();
            const rtGenBIdx = calls.length - 1;
            out.rt_genA_idx = rtGenAIdx;
            out.rt_genB_idx = rtGenBIdx;
            out.rt_genB_newer = rtGenBIdx > rtGenAIdx;
            out.rt_genA_urls = calls.slice(rtGenAIdx, rtGenBIdx).map(function (c) { return c.url; });
            out.rt_genB_urls = calls.slice(rtGenBIdx).map(function (c) { return c.url; });
            out.rt_genA_is_original_view =
              out.rt_genA_urls.length > 0 &&
              (out.rt_genA_urls[0] === '/feedback' || out.rt_genA_urls[0] === '/feedback?');
            out.rt_genB_is_original_view =
              out.rt_genB_urls.length > 0 &&
              (out.rt_genB_urls[0] === '/feedback' || out.rt_genB_urls[0] === '/feedback?');

            return flush().then(function () {
              // The fresher original-view response paints first.
              resolveNewest({ items: [{ id: 21, title: 'ROUNDTRIP CURRENT', completed: false }] });
              return flush().then(function () {
                out.rendered_after_rt_current = renderedTitles();
                // The pre-round-trip response resolving later must be dropped
                // even though the view is byte-identical once more.
                resolveOldest({ items: [{ id: 91, title: 'ROUNDTRIP STALE', completed: false }] });
                return flush().then(function () {
                  out.rendered_after_rt_stale = renderedTitles();
                  out.pending_left_roundtrip = pending.length;

                  // -- Part 3: preserved view-change guard (control) --------
                  // Same generation interval, but the view changes before the
                  // older response resolves; the identity guard must still drop
                  // it.  This is the pre-existing contract, exercised live so a
                  // regression that removed it would be caught.
                  deferred.push(true);
                  calls.length = 0;
                  input(searchInput, 'first');
                  const ctlGenAIdx = calls.length - 1;
                  input(searchInput, 'second');
                  const ctlGenBIdx = calls.length - 1;
                  out.ctl_genA_newer = ctlGenBIdx > ctlGenAIdx;
                  out.ctl_genA_urls = calls.slice(ctlGenAIdx, ctlGenBIdx).map(function (c) { return c.url; });
                  out.ctl_genB_urls = calls.slice(ctlGenBIdx).map(function (c) { return c.url; });
                  return flush().then(function () {
                    resolveNewest({ items: [{ id: 22, title: 'CONTROL CURRENT', completed: false }] });
                    return flush().then(function () {
                      out.rendered_after_ctl_current = renderedTitles();
                      resolveOldest({ items: [{ id: 92, title: 'CONTROL STALE', completed: false }] });
                      return flush().then(function () {
                        out.rendered_after_ctl_stale = renderedTitles();
                        out.pending_left_control = pending.length;
                        report(out);
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
  }).catch(function (thrown) {
    report({ executed: false, error: String((thrown && thrown.message) || thrown) });
  });
}
drive();"""


class SearchRequestGenerationTests(unittest.TestCase):
    """C10: stale same-view generations are discarded by a request generation guard."""

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

        program = u3.DRIVER_PREAMBLE % {
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

    def test_two_same_view_gets_then_newer_then_older_resolution(self):
        """Two GETs for the identical view resolve newer-first; newest rows stay."""
        # Preserved query/status guards must not be the thing under test here:
        # both requests carry the byte-identical original view.
        self.assertTrue(self.report.get('same_view_distinct_requests'),
                        'the harness must issue two distinct board GETs: %s'
                        % self.report.get('same_view_urls'))
        self.assertTrue(self.report.get('same_view_query_identical'),
                        'the two requests must share the identical view URL: %s'
                        % self.report.get('same_view_urls'))
        self.assertEqual(self.report.get('held_after_issue'), 2,
                         'both same-view requests must be held until the driver '
                         'resolves them: %s' % self.report.get('held_after_issue'))
        self.assertTrue(self.report.get('resolved_newer'),
                        'the newer same-view request must be resolvable')
        self.assertTrue(self.report.get('resolved_older'),
                        'the older same-view request must be resolvable')
        # The newer board painted and the older response did not overwrite it.
        self.assertIn('NEWEST ROWS', self.report['rendered_after_newest'],
                      'the newer same-view response must paint: %s'
                      % self.report['rendered_after_newest'])
        self.assertNotIn('STALE OLDER ROWS', self.report['rendered_after_older'],
                         'a stale same-view response must never repaint the board: %s'
                         % self.report['rendered_after_older'])
        self.assertIn('NEWEST ROWS', self.report['rendered_after_older'],
                      'the newest same-view rows must remain rendered after the '
                      'older response resolves: %s' % self.report['rendered_after_older'])
        self.assertEqual(self.report.get('pending_left_same_view'), 0,
                         'every same-view request must be resolved by the harness')

    def test_query_status_roundtrip_generation_is_discarded(self):
        """A pre-round-trip GET for the same view as a newer one must be dropped."""
        self.assertEqual(self.report.get('negative_control_error'), None,
                         self.report.get('negative_control_error'))
        self.assertTrue(self.report.get('rt_genB_newer'),
                        'the fresher original-view request must be issued after '
                        'the pre-round-trip request')
        self.assertTrue(self.report.get('rt_genA_is_original_view'),
                        'the pre-round-trip request must belong to the original '
                        'view: %s' % self.report.get('rt_genA_urls'))
        self.assertTrue(self.report.get('rt_genB_is_original_view'),
                        'the fresher request must belong to the original view: %s'
                        % self.report.get('rt_genB_urls'))
        self.assertIn('ROUNDTRIP CURRENT', self.report['rendered_after_rt_current'],
                      'the fresher original-view response must paint: %s'
                      % self.report['rendered_after_rt_current'])
        self.assertNotIn('ROUNDTRIP STALE', self.report['rendered_after_rt_stale'],
                         'a generation issued before the query/status round-trip '
                         'must not paint afterwards: %s'
                         % self.report['rendered_after_rt_stale'])
        self.assertIn('ROUNDTRIP CURRENT', self.report['rendered_after_rt_stale'],
                      'the fresher original-view rows must remain rendered: %s'
                      % self.report['rendered_after_rt_stale'])
        self.assertEqual(self.report.get('pending_left_roundtrip'), 0,
                         'every round-trip request must be resolved by the harness')

    def test_preserved_view_change_guard_still_discards_stale(self):
        """The preserved query/status identity guard still drops a changed view."""
        self.assertTrue(self.report.get('ctl_genA_newer'),
                        'the second-needle request must be issued after the first')
        self.assertIn('q=first', ' '.join(self.report['ctl_genA_urls']),
                      'control generation A must carry the first needle: %s'
                      % self.report['ctl_genA_urls'])
        self.assertIn('q=second', ' '.join(self.report['ctl_genB_urls']),
                      'control generation B must carry the second needle: %s'
                      % self.report['ctl_genB_urls'])
        self.assertIn('CONTROL CURRENT', self.report['rendered_after_ctl_current'],
                      'the current control response must paint: %s'
                      % self.report['rendered_after_ctl_current'])
        self.assertNotIn('CONTROL STALE', self.report['rendered_after_ctl_stale'],
                         'a response for a view that has since changed must be '
                         'discarded: %s' % self.report['rendered_after_ctl_stale'])
        self.assertIn('CONTROL CURRENT', self.report['rendered_after_ctl_stale'],
                      'the current control rows must remain rendered: %s'
                      % self.report['rendered_after_ctl_stale'])
        self.assertEqual(self.report.get('pending_left_control'), 0,
                         'every control request must be resolved by the harness')


if __name__ == '__main__':
    unittest.main()
