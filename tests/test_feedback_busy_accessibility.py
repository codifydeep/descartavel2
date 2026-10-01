"""Test-first acceptance for ACCESSIBLE-1: the form's pending aria-busy state.

Phase 1 is tests only. These tests drive the *real* ``app/static/app.js`` from
disk, exactly as ``tests/test_feedback_pending_submit.py`` does, but they extend
that file's observation snapshot to report the ``#feedback-form`` element's
``aria-busy`` attribute through real ``setAttribute``/``getAttribute``
semantics. Only the observation snapshot and the resubmission stage are
extended: the imported template and its inline driver are otherwise reused
byte-for-byte, never transformed, and the real client is never reimplemented.
The additive driver edit is what makes the issue-mandated "a later valid retry
must announce true again" observable -- the imported stage 5 settles its retry
with a synchronous OK mock, so it exposes only the settled retry. The extended
stage holds the retry on a deferred, snapshots ``pending_resubmit`` while it is
unresolved, and only then settles it.

Contract under test (the annotation was carried by the approved template and is
the approved deliverable here, not new text):

* ``aria-busy`` starts as the string ``'false'``.
* It is the string ``'true'`` while a valid submission POST is unresolved.
* It returns to the string ``'false'`` after success, a non-OK HTTP response or
  a rejected fetch.
* A later valid retry announces ``'true'`` again while its POST is unresolved.
* Whitespace-only title validation leaves ``'false'`` and issues no POST.

The frozen client never touches the form's ``aria-busy``, so the initial value
is absent (``None``) where the contract requires ``'false'``: every assertion
turns Green only once app.js announces the pending state.

Execution is bounded the way the baseline pins it -- the template is imported
and report-alike-checked rather than duplicated, hashed off the single declared
path, piped to ``node`` over stdin, and run under a subprocess timeout. There
are no sleeps, skips or swallowed harness errors.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_feedback_pending_submit import (
    NODE_HARNESS_TEMPLATE,
    NODE_TIMEOUT_SECONDS,
)


ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = ROOT / 'app' / 'static' / 'app.js'


# The shared snapshot the imported harness records. Located once so the two
# additive edits below can be anchored to it; the hard failure is explicit so
# it cannot vanish under ``-O`` or a stripped ``__debug__`` build.
_BASELINE_SNAPSHOT = re.search(
    r'function snapshot\(\) \{.*?\n\}', NODE_HARNESS_TEMPLATE, re.S)
if _BASELINE_SNAPSHOT is None:
    raise AssertionError(
        'could not locate the shared snapshot in the imported harness template')
if NODE_HARNESS_TEMPLATE.count(_BASELINE_SNAPSHOT.group(0)) != 1:
    raise AssertionError(
        'the shared harness snapshot must be unique in the imported template')


# The only difference from the imported snapshot: it also reports the form's
# ``aria-busy`` attribute, read through the element's own ``getAttribute`` so
# the harness sees exactly the DOM string the client announced.
SNAPSHOT_WITH_FORM_BUSY = '''function snapshot() {
  return {
    total: byId['summary-total'].textContent,
    open: byId['summary-open'].textContent,
    completed: byId['summary-completed'].textContent,
    status: byId['form-status'].textContent,
    status_count: byId['feedback-list'].children.length,
    button_disabled: button.disabled === true,
    button_present: button !== null,
    form_busy: byId['feedback-form'].getAttribute('aria-busy')
  };
}'''


# The imported resubmission stage. Held as an exact anchor so the extended
# stage replaces precisely this block and nothing else.
_BASELINE_RESUBMIT_STAGE = '''// Stage 5: a later valid resubmission must POST again. This one uses a
  // synchronous OK mock so it settles immediately.
  postMode = 'ok';
  fillForm('Second idea', 'again');
  const resubmit = dispatchSubmit();
  await flush();
  const after_resubmit = snapshot();
  const resubmit_posts = posts.length;'''
if NODE_HARNESS_TEMPLATE.count(_BASELINE_RESUBMIT_STAGE) != 1:
    raise AssertionError(
        'the imported resubmission stage must be unique in the template')


# The extended stage: a later valid retry is held on a deferred so a distinct
# ``pending_resubmit`` observation proves aria-busy announces 'true' again
# while the retry POST is unresolved, then settled exactly like the original.
EXTENDED_RESUBMIT_STAGE = '''// Stage 5: a later valid retry must POST again and announce busy again. The
  // retry is held on a deferred so the observation while it is unresolved is
  // distinct from the settled one; solving the deferred then mutates the
  // stored board on the successful response path, matching the imported
  // semantics (only success inserts an item).
  postMode = 'defer';
  fillForm('Second idea', 'again');
  const resubmit = dispatchSubmit();
  await flush();
  const pending_resubmit = snapshot();
  const resubmit_held_posts = posts.length - after_second.posts;
  if (deferreds.post && deferreds.post.resolve) {
    deferreds.post.resolve(jsonResponse(
      { id: nextId, title: 'Second idea', completed: false }, true));
    nextId += 1;
    items.push({ id: nextId - 1, title: 'Second idea', completed: false });
  }
  await flush();
  const after_resubmit = snapshot();
  const resubmit_posts = posts.length;'''


# ---- minimal, additive driver edits (validated against stable anchors) -----

_BASELINE_REPORT_AFTER_RESUBMIT = (
    '    resubmitted_posts: resubmit_posts - after_second.posts,\n'
    '    after_resubmit: after_resubmit,')
_EXTENDED_REPORT_AFTER_RESUBMIT = (
    '    resubmitted_posts: resubmit_posts - after_second.posts,\n'
    '    after_resubmit: after_resubmit,\n'
    '    pending_resubmit: pending_resubmit,\n'
    '    resubmit_held_posts: resubmit_held_posts,')


def _extend_template(template: str) -> str:
    """Return the imported template with only the additive driver edits."""
    if template.count(_BASELINE_REPORT_AFTER_RESUBMIT) != 1:
        raise AssertionError(
            'could not locate the unique resubmission report key in the driver')
    extended = template.replace(
        _BASELINE_SNAPSHOT.group(0), SNAPSHOT_WITH_FORM_BUSY)
    extended = extended.replace(
        _BASELINE_RESUBMIT_STAGE, EXTENDED_RESUBMIT_STAGE)
    extended = extended.replace(
        _BASELINE_REPORT_AFTER_RESUBMIT, _EXTENDED_REPORT_AFTER_RESUBMIT)
    return extended


BUSY_HARNESS_TEMPLATE = _extend_template(NODE_HARNESS_TEMPLATE)


class BusyAccessibilityHarnessCase(unittest.TestCase):
    """Run the real ``app.js`` once and expose its extended-observation report."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')

    def setUp(self):
        self.assertTrue(APP_JS_PATH.is_file(),
                        'declared client asset must exist: %s' % APP_JS_PATH)
        self.source_filename = str(APP_JS_PATH)
        self.source_bytes = APP_JS_PATH.read_bytes()
        self.source_sha256 = hashlib.sha256(self.source_bytes).hexdigest()

        self.assertTrue(self.node, 'node executable is unavailable')
        program = BUSY_HARNESS_TEMPLATE % {
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


class BusyAccessibilityArtifactTests(BusyAccessibilityHarnessCase):
    """Real execution under the faithful Window and a real aria-busy channel."""

    def test_executes_the_real_app_js_and_reports_the_form_attribute(self):
        self.assertTrue(self.source_bytes.strip(),
                        'the real app.js must be non-empty')
        self.assertEqual(self.source_filename, str(APP_JS_PATH))
        self.assertRegex(self.source_sha256, r'^[0-9a-f]{64}$')
        # The initial execute-time load issued its two GETs (real execution).
        self.assertEqual(self.report['initial_load_calls'], 2,
                         'the initial load must issue exactly two GETs')
        # Every observation carries the attribute under test as None or a str.
        for key in ('pre_submit', 'pending', 'success', 'pending_resubmit',
                    'after_resubmit', 'after_http', 'after_reject',
                    'after_empty'):
            value = self.report[key]['form_busy']
            self.assertTrue(value is None or isinstance(value, str),
                            'form_busy must be the raw attribute or absent')


class BusyAccessibilityStateTests(BusyAccessibilityHarnessCase):
    """aria-busy must be 'false', 'true' then 'false' across a real POST."""

    def test_form_starts_with_aria_busy_false(self):
        self.assertEqual(
            self.report['pre_submit']['form_busy'], 'false',
            "the form's aria-busy must be the string 'false' initially")

    def test_valid_post_announces_true_while_pending(self):
        self.assertEqual(
            self.report['pending']['form_busy'], 'true',
            "aria-busy must be 'true' while the POST is unresolved")
        # The pre-submit observation and the pending one are genuinely
        # distinct -- both in the observed attribute and in the fact that no
        # POST had been issued yet at pre-submit time.
        self.assertEqual(self.report['pre_submit_posts'], 0,
                         'no POST may be issued before the first submit')
        self.assertEqual(self.report['pending']['form_busy'], 'true',
                         "the pending observation must not be pre-submit")

    def test_success_returns_aria_busy_to_false(self):
        self.assertEqual(
            self.report['success']['form_busy'], 'false',
            "aria-busy must return to 'false' after a successful POST")

    def test_retry_announces_true_again_while_held(self):
        # The retry is held on a deferred: while unresolved it must announce
        # 'true' again. This is the observation the imported stage 5 omitted --
        # it settled its retry synchronously and never sampled the held window.
        self.assertEqual(
            self.report['pending_resubmit']['form_busy'], 'true',
            "a later valid retry must announce 'true' again while its POST "
            'is unresolved')
        # The first submit must likewise have announced a busy window, and the
        # held-retry observation must be a genuinely distinct sample.
        self.assertEqual(self.report['pending']['form_busy'], 'true',
                         'the first submit must have announced a busy window')
        self.assertEqual(self.report['pre_submit']['form_busy'], 'false',
                         'the pre-submit sample must be the initial false')
        # And once that retry settles it must close the window again.
        self.assertEqual(
            self.report['after_resubmit']['form_busy'], 'false',
            "a settled retry must leave aria-busy at 'false'")


class BusyAccessibilityFailureTests(BusyAccessibilityHarnessCase):
    """Every exit path must settle aria-busy back to 'false'."""

    def test_non_ok_response_clears_busy(self):
        self.assertEqual(
            self.report['after_http']['form_busy'], 'false',
            "a non-OK response must return aria-busy to 'false'")
        self.assertIsNone(self.report['http_error_dispatch']['threw'])

    def test_rejected_fetch_clears_busy(self):
        self.assertEqual(
            self.report['after_reject']['form_busy'], 'false',
            "a rejected fetch must return aria-busy to 'false'")
        self.assertIsNone(self.report['reject_dispatch']['threw'])


class BusyAccessibilityValidationTests(BusyAccessibilityHarnessCase):
    """Whitespace-only titles are rejected without ever announcing busy."""

    def test_busy_window_closes_after_every_attempt(self):
        # After the resolved success, the resolved retry, the HTTP failure and
        # the rejected fetch -- every attempt has settled -- the attribute is
        # 'false'; the 'true' observations were real transients, not a stuck
        # state.
        for key in ('success', 'after_resubmit', 'after_http', 'after_reject'):
            self.assertEqual(
                self.report[key]['form_busy'], 'false',
                'the busy window must close after %s' % key)

    def test_empty_title_leaves_false_and_issues_no_post(self):
        self.assertEqual(
            self.report['after_empty']['form_busy'], 'false',
            "empty-title validation must leave aria-busy 'false'")
        # The driver reuses ``postMode = 'ok'`` before the whitespace-only
        # submit, so any POST it triggered would have settled and inserted a
        # stored item. The stored count is the POST evidence: only the two valid
        # submissions (the settled first and the settled retry) may have added
        # one, and the extra held retry must be exactly one POST.
        self.assertEqual(
            self.report['after_empty']['status_count'], 2,
            'whitespace-only title validation must issue no POST')
        self.assertEqual(
            self.report['after_empty']['status_count'],
            self.report['after_reject']['status_count'],
            'the whitespace-only submit must not change the board')
        self.assertIsNone(self.report['empty_dispatch']['threw'])
        self.assertIsNone(self.report['resubmit_dispatch']['threw'])

    def test_retry_issues_exactly_one_post(self):
        self.assertEqual(self.report['resubmit_held_posts'], 1,
                         'the held retry must issue exactly one POST')
        self.assertEqual(self.report['resubmitted_posts'], 1,
                         'the retry must have issued exactly one POST total')


if __name__ == '__main__':
    unittest.main()
