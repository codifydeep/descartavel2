"""Test-first regression for KEYBOARD-1: Escape dismisses the form status.

Phase 1 is tests only. These tests load the *real* ``app/static/app.js`` into a
Node ``vm`` context whose global object is a faithful ``Window`` and prove the
board client's Escape-dismissal contract by observed state, never by matching
source text.

Why the frozen base is Red, behaviourally. The approved contract is: a
``keydown`` event with ``key === 'Escape'`` that bubbles to ``#feedback-form``
while no submission is pending dismisses the current ``#form-status`` message
and removes its ``is-error`` class, while preserving the typed title and
description, the board, the summary, focus, ``aria-busy='false'`` and the
enabled button -- without submitting, reloading or clearing the form. Escape
while a valid POST is unresolved must NOT dismiss ``Submitting...``, cancel the
POST, unlock the button or clear ``aria-busy='true'``. Other keys must not
dismiss. Repeated Escape with an empty status is harmless, and after an error a
later valid submission must still succeed. The frozen client binds only a
``submit`` listener and has no Escape handling, so the status persists after a
dismissal keydown and every Escape assertion below fails.

The harness runs the real application logic and does not reimplement the client.
It imports ``NODE_HARNESS_TEMPLATE`` from ``tests/test_feedback_pending_submit``
and extends it *additively*: the baseline DOM/fetch/Window definitions are reused
verbatim and a ``keydown`` dispatcher plus extra observations are appended. The
POST mock returns a promise the test controls, so "pending" is a real unresolved
promise rather than a sleep. The Node program is piped to ``node`` over stdin
(no temporary files), bounded by a subprocess timeout, and every run flushes
promises deterministically with no sleeps, skips or swallowed exceptions.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_feedback_pending_submit import (  # noqa: E402
    APP_JS_PATH,
    NODE_HARNESS_TEMPLATE,
)


NODE_TIMEOUT_SECONDS = 30


# The baseline template's driver is replaced by this extended driver. The base
# template is split at its driver marker so every DOM/fetch/Window definition --
# the reusable harness -- is retained byte-for-byte, while the driver gains a
# keydown dispatcher and the KEYBOARD-1 observations.
DRIVER_MARKER = '(async function drive() {'

# Additive extension of the reused mock: the baseline always defers under the
# name 'post'. KEYBOARD-1 also needs a named, dedicated deferred so the pending
# window is real and controllable. The base template is split here (before its
# driver) so every DOM/fetch/Window definition is retained byte-for-byte.
MOCK_ANCHOR = 'let postMode = \'defer\';    // \'defer\' | \'ok\' | \'http-error\' | \'reject\'\n'
MOCK_EXTENSION = """let postMode = 'defer';    // 'defer' | 'ok' | 'http-error' | 'reject'
// Name of the deferred a deferred POST waits on. The baseline uses 'post';
// KEYBOARD-1 sets a dedicated name so a held POST is distinct and controllable.
let postDeferredName = 'post';
"""

# The baseline's deferred POST call site, re-pointed at ``postDeferredName``.
DEFER_CALL_ANCHOR = "    return makeDeferred('post').promise;"
DEFER_CALL_EXTENSION = "    return makeDeferred(postDeferredName).promise;"

EXTENDED_SUFFIX = r"""

// Dispatch a keydown through the form's own event target, exactly as a browser
// would route a real keystroke, rather than calling a listener directly.
function dispatchKeydown(key, targetElement) {
  const target = targetElement || byId['feedback-form'];
  const recorded = { key: key, prevented: false, threw: null };
  try {
    target.dispatchEvent({
      type: 'keydown',
      key: key,
      bubbles: true,
      target: target,
      preventDefault: function () { recorded.prevented = true; }
    });
  } catch (thrown) {
    recorded.threw = String((thrown && thrown.message) || thrown);
  }
  return recorded;
}

// Every observable the dismissal contract constrains, read in one place.
function formState() {
  return {
    status: byId['form-status'].textContent,
    is_error: byId['form-status'].classList.contains('is-error'),
    title: byId['title'].value,
    description: byId['description'].value,
    board_count: byId['feedback-list'].children.length,
    total: byId['summary-total'].textContent,
    open: byId['summary-open'].textContent,
    completed: byId['summary-completed'].textContent,
    button_disabled: button.disabled === true,
    aria_busy: byId['feedback-form'].getAttribute('aria-busy')
  };
}

function postCount() { return posts.length; }

(async function drive() {
  try {
    const script = new vm.Script(SOURCE, { filename: SOURCE_NAME });
    script.runInContext(context);
  } catch (thrown) {
    executed = false;
    error = String((thrown && thrown.message) || thrown);
  }

  if (!executed) { report({ executed: false, error: error }); return; }

  await flush();
  const load_calls = calls.length;

  // Stage 1: idle empty-title validation error. Distinct observation: the error
  // message is present and carries is-error while the button stays enabled.
  postMode = 'ok';
  fillForm('', 'missing title');
  const idle_validation_dispatch = dispatchSubmit();
  await flush();
  const idle_error = formState();
  const idle_error_posts = postCount();

  // Stage 2: Escape from the form's event target dismisses the validation error.
  const idle_error_escape = dispatchKeydown('Escape');
  await flush();
  const after_idle_escape = formState();
  const idle_escape_posts = postCount();

  // Stage 3: a filled draft plus a real HTTP error message.
  postMode = 'http-error';
  fillForm('Draft idea', 'draft details');
  const http_error_dispatch = dispatchSubmit();
  await flush();
  const http_error_state = formState();
  const http_error_posts = postCount();

  // Stage 4: unrelated keys must not dismiss the message.
  const enter_escape = dispatchKeydown('Enter');
  const space_escape = dispatchKeydown(' ');
  const esc_escape = dispatchKeydown('Esc');
  const escape_down_escape = dispatchKeydown('EscapeDown');
  await flush();
  const after_other_keys = formState();
  const other_keys_posts = postCount();

  // Stage 5: Escape then dismisses the HTTP error, preserving the typed draft.
  const http_error_escape = dispatchKeydown('Escape');
  await flush();
  const after_http_escape = formState();
  const http_escape_posts = postCount();

  // Stage 6: repeated Escape with an already-empty status is harmless.
  const repeat_escape = dispatchKeydown('Escape');
  const repeat_escape_two = dispatchKeydown('Escape');
  await flush();
  const after_repeat_escape = formState();
  const repeat_posts = postCount();

  // Stage 7: a transport failure, then Escape dismisses it.
  postMode = 'reject';
  fillForm('Reject idea', 'network');
  const reject_dispatch = dispatchSubmit();
  await flush();
  const reject_state = formState();
  // Distinct observation: the POST count immediately BEFORE the dismiss
  // keydown. The reject POST has already settled here, so this is the value a
  // post-dismiss comparison must anchor to -- the pre-submit count is stale.
  const reject_pre_escape_posts = postCount();
  const reject_escape = dispatchKeydown('Escape');
  await flush();
  const after_reject_escape = formState();
  const reject_posts = postCount();

  // Stage 8: after an error was dismissed, a later valid submission still
  // works. This POST settles synchronously via the 'ok' mock, so the client is
  // back at idle before the pending stage begins.
  postMode = 'ok';
  fillForm('Retry idea', 'after dismissal');
  const retry_dispatch = dispatchSubmit();
  await flush();
  const after_retry = formState();
  const retry_posts = postCount();
  const retry_board_count = byId['feedback-list'].children.length;

  // Stage 9: a held pending POST, with a dedicated deferred so the window is
  // real. While unresolved, Escape must not dismiss Submitting... nor unlock
  // the button or clear aria-busy.
  postMode = 'defer';
  postDeferredName = 'keyboard-pending';
  fillForm('Pending idea', 'still in flight');
  const pending_dispatch = dispatchSubmit();
  await flush();
  const pending_state = formState();
  const pending_posts = postCount();
  const pending_escape = dispatchKeydown('Escape');
  const pending_escape_two = dispatchKeydown('Escape');
  await flush();
  const after_pending_escape = formState();
  const pending_escape_posts = postCount();

  // Resolve the held POST so the run completes deterministically, then confirm
  // the client returns to idle once the held request settles.
  if (deferreds['keyboard-pending'] && deferreds['keyboard-pending'].resolve) {
    deferreds['keyboard-pending'].resolve(jsonResponse(
      { id: nextId, title: 'Pending idea', completed: false }, true));
    nextId += 1;
  }
  await flush();
  await flush();
  const after_pending_settle = formState();

  report({
    executed: true, error: null, filename: SOURCE_NAME,
    load_calls: load_calls,
    idle_validation_dispatch: idle_validation_dispatch,
    idle_error: idle_error, idle_error_posts: idle_error_posts,
    idle_error_escape: idle_error_escape, after_idle_escape: after_idle_escape,
    idle_escape_posts: idle_escape_posts,
    http_error_dispatch: http_error_dispatch,
    http_error_state: http_error_state,
    http_error_posts: http_error_posts,
    enter_escape: enter_escape, space_escape: space_escape,
    esc_escape: esc_escape, escape_down_escape: escape_down_escape,
    after_other_keys: after_other_keys, other_keys_posts: other_keys_posts,
    http_error_escape: http_error_escape, after_http_escape: after_http_escape,
    http_escape_posts: http_escape_posts,
    repeat_escape: repeat_escape, repeat_escape_two: repeat_escape_two,
    after_repeat_escape: after_repeat_escape, repeat_posts: repeat_posts,
    reject_dispatch: reject_dispatch, reject_state: reject_state,
    reject_pre_escape_posts: reject_pre_escape_posts,
    reject_escape: reject_escape, after_reject_escape: after_reject_escape,
    reject_posts: reject_posts,
    retry_dispatch: retry_dispatch, after_retry: after_retry,
    retry_posts: retry_posts, retry_board_count: retry_board_count,
    pending_dispatch: pending_dispatch, pending_state: pending_state,
    pending_posts: pending_posts, pending_escape: pending_escape,
    pending_escape_two: pending_escape_two,
    after_pending_escape: after_pending_escape,
    pending_escape_posts: pending_escape_posts,
    after_pending_settle: after_pending_settle
  });
})().catch(function (thrown) {
  report({ executed: false, error: String((thrown && thrown.message) || thrown) });
});
"""


def _extended_template():
    """Return the baseline Node template with additive mock and driver changes."""
    if DRIVER_MARKER not in NODE_HARNESS_TEMPLATE:
        raise AssertionError('baseline harness driver marker not found')
    if MOCK_ANCHOR not in NODE_HARNESS_TEMPLATE:
        raise AssertionError('baseline harness mock anchor not found')
    if NODE_HARNESS_TEMPLATE.count(DEFER_CALL_ANCHOR) != 1:
        raise AssertionError('baseline deferred call site not unique')
    base = NODE_HARNESS_TEMPLATE.replace(MOCK_ANCHOR, MOCK_EXTENSION, 1)
    base = base.replace(DEFER_CALL_ANCHOR, DEFER_CALL_EXTENSION, 1)
    base = base.split(DRIVER_MARKER, 1)[0]
    return base + EXTENDED_SUFFIX.lstrip('\n')


EXTENDED_TEMPLATE = _extended_template()


class KeyboardDismissHarnessCase(unittest.TestCase):
    """Run the real ``app.js`` once under the extended harness."""

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
        program = EXTENDED_TEMPLATE % {
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


class ArtifactTests(KeyboardDismissHarnessCase):
    """The real client must execute under the Window and keep its baseline flow."""

    def test_executes_the_real_app_js_in_a_node_vm(self):
        self.assertTrue(self.source_bytes.strip(),
                        'the real app.js must be non-empty')
        self.assertEqual(self.source_filename, str(APP_JS_PATH))
        self.assertRegex(self.source_sha256, r'^[0-9a-f]{64}$')
        self.assertEqual(self.report['load_calls'], 2,
                         'the initial load must issue exactly two GETs')

    def test_keydown_dispatches_do_not_throw(self):
        self.assertEqual(self.report['idle_error_escape']['key'], 'Escape')
        for record in ('idle_error_escape', 'http_error_escape',
                       'reject_escape', 'pending_escape',
                       'repeat_escape', 'repeat_escape_two'):
            self.assertIsNone(self.report[record]['threw'],
                              '%s must not throw' % record)


class IdleValidationDismissTests(KeyboardDismissHarnessCase):
    """Escape dismisses an idle validation error without side effects."""

    def test_idle_validation_error_is_visible_first(self):
        # Distinct observation: before Escape the error message is present and
        # carries the is-error class, so the dismissal assertion is meaningful.
        self.assertTrue(self.report['idle_error']['status'],
                        'validation must surface a message before dismissal')
        self.assertIn('title', self.report['idle_error']['status'])
        self.assertTrue(self.report['idle_error']['is_error'],
                        'a validation error must carry the is-error class')
        self.assertFalse(self.report['idle_error']['button_disabled'],
                         'validation must not lock the form')
        self.assertEqual(self.report['idle_error']['title'], '')

    def test_escape_clears_the_validation_message_and_error_class(self):
        after = self.report['after_idle_escape']
        self.assertEqual(after['status'], '',
                         'Escape must dismiss the validation message; got %r'
                         % after['status'])
        self.assertFalse(after['is_error'],
                         'Escape must remove the is-error class')
        self.assertNotEqual(self.report['idle_error']['status'], after['status'],
                            'the dismissed state must differ from the error state')

    def test_escape_does_not_submit_or_change_the_button(self):
        self.assertEqual(self.report['idle_escape_posts'],
                         self.report['idle_error_posts'],
                         'Escape must not issue a POST')
        self.assertFalse(self.report['after_idle_escape']['button_disabled'],
                         'Escape must leave the button available')
        self.assertEqual(self.report['after_idle_escape']['aria_busy'], 'false',
                         'Escape at rest must leave aria-busy false')
        self.assertIsNone(self.report['idle_validation_dispatch']['threw'])


class HttpErrorDismissTests(KeyboardDismissHarnessCase):
    """Escape dismisses an HTTP error message and preserves the draft."""

    def test_http_error_message_is_visible_first(self):
        self.assertTrue(self.report['http_error_state']['status'],
                        'an HTTP failure must surface a message')
        self.assertTrue(self.report['http_error_state']['is_error'],
                        'an HTTP failure message must carry is-error')

    def test_unrelated_keys_do_not_dismiss_the_message(self):
        # Enter, space, 'Esc' and 'EscapeDown' are dispatched and must leave the
        # message and its is-error class untouched.
        self.assertTrue(self.report['after_other_keys']['status'],
                        'unrelated keys must not dismiss the message')
        self.assertEqual(self.report['after_other_keys']['status'],
                         self.report['http_error_state']['status'])
        self.assertTrue(self.report['after_other_keys']['is_error'],
                        'unrelated keys must not remove is-error')
        self.assertEqual(self.report['other_keys_posts'],
                         self.report['http_error_posts'],
                         'unrelated keys must not submit')
        expected = {'enter_escape': 'Enter', 'space_escape': ' ',
                    'esc_escape': 'Esc', 'escape_down_escape': 'EscapeDown'}
        for record, key in expected.items():
            self.assertEqual(self.report[record]['key'], key)
            self.assertIsNone(self.report[record]['threw'])

    def test_escape_dismisses_the_http_error(self):
        after = self.report['after_http_escape']
        self.assertEqual(after['status'], '',
                         'Escape must dismiss the HTTP error message')
        self.assertFalse(after['is_error'],
                         'Escape must remove is-error from the HTTP error')
        self.assertEqual(self.report['http_escape_posts'],
                         self.report['other_keys_posts'],
                         'dismissing must not submit')

    def test_escape_preserves_title_description_board_and_summary(self):
        before = self.report['http_error_state']
        after = self.report['after_http_escape']
        self.assertEqual(before['title'], 'Draft idea')
        self.assertEqual(after['title'], 'Draft idea',
                         'Escape must preserve the typed title')
        self.assertEqual(after['description'], 'draft details',
                         'Escape must preserve the typed description')
        self.assertEqual(after['board_count'], before['board_count'],
                         'Escape must not touch the board')
        self.assertEqual(after['total'], before['total'])
        self.assertEqual(after['open'], before['open'])
        self.assertEqual(after['completed'], before['completed'])
        self.assertFalse(after['button_disabled'],
                         'Escape must leave the button available')
        self.assertEqual(after['aria_busy'], 'false')

    def test_repeated_escape_with_empty_status_is_harmless(self):
        after = self.report['after_repeat_escape']
        self.assertEqual(after['status'], '')
        self.assertFalse(after['is_error'])
        self.assertEqual(after['title'], 'Draft idea',
                         'repeated Escape must not clear the draft')
        self.assertEqual(after['description'], 'draft details')
        self.assertEqual(self.report['repeat_posts'],
                         self.report['http_escape_posts'],
                         'repeated Escape must not submit')
        self.assertIsNone(self.report['repeat_escape']['threw'])
        self.assertIsNone(self.report['repeat_escape_two']['threw'])


class TransportErrorDismissTests(KeyboardDismissHarnessCase):
    """Escape dismisses a transport error and allows a later valid submission."""

    def test_transport_error_is_dismissed_by_escape(self):
        self.assertTrue(self.report['reject_state']['status'],
                        'a transport failure must surface a message')
        self.assertTrue(self.report['reject_state']['is_error'])
        after = self.report['after_reject_escape']
        self.assertEqual(after['status'], '',
                         'Escape must dismiss the transport error')
        self.assertFalse(after['is_error'])
        # The reject POST has already settled by the time Escape is dispatched,
        # so the immediate post-dismiss comparison anchors to the count taken
        # right before the dismiss keydown -- not the stale pre-submit value.
        self.assertEqual(self.report['reject_posts'],
                         self.report['reject_pre_escape_posts'],
                         'dismissing must not submit')

    def test_later_valid_submission_succeeds_after_dismissal(self):
        after = self.report['after_retry']
        self.assertEqual(self.report['retry_posts'],
                         self.report['reject_posts'] + 1,
                         'a valid retry after dismissal must POST once')
        self.assertTrue(after['status'],
                        'a successful retry must report success')
        self.assertIn('Thanks', after['status'])
        self.assertFalse(after['is_error'],
                         'a successful retry must not carry is-error')
        self.assertFalse(after['button_disabled'],
                         'a successful retry must re-enable the button')
        self.assertEqual(after['aria_busy'], 'false')
        self.assertEqual(self.report['retry_board_count'],
                         self.report['after_reject_escape']['board_count'] + 1,
                         'the successful retry must record exactly one item')
        self.assertIsNone(self.report['retry_dispatch']['threw'])


class PendingSubmitDismissTests(KeyboardDismissHarnessCase):
    """Escape must not dismiss or cancel a held, unresolved POST."""

    def test_pending_state_shows_submitting_and_busy(self):
        pending = self.report['pending_state']
        self.assertEqual(pending['status'], 'Submitting...',
                         'the pending window must show Submitting...; got %r'
                         % pending['status'])
        self.assertTrue(pending['button_disabled'],
                        'the button must be disabled while pending')
        self.assertEqual(pending['aria_busy'], 'true',
                         'aria-busy must be true while pending')
        self.assertEqual(self.report['pending_posts'],
                         self.report['retry_posts'] + 1,
                         'the pending attempt must have issued one POST')

    def test_escape_does_not_dismiss_the_pending_message(self):
        after = self.report['after_pending_escape']
        self.assertEqual(after['status'], 'Submitting...',
                         'Escape must not dismiss Submitting...')
        self.assertEqual(self.report['pending_escape_posts'],
                         self.report['pending_posts'],
                         'Escape must not cancel or duplicate the POST')

    def test_escape_does_not_unlock_or_clear_busy_while_pending(self):
        after = self.report['after_pending_escape']
        self.assertTrue(after['button_disabled'],
                        'Escape must not unlock the button while pending')
        self.assertEqual(after['aria_busy'], 'true',
                         'Escape must not clear aria-busy while pending')
        self.assertEqual(after['title'], 'Pending idea',
                         'Escape must not clear the held draft')
        self.assertIsNone(self.report['pending_escape']['threw'])
        self.assertIsNone(self.report['pending_escape_two']['threw'])

    def test_pending_post_settles_when_the_held_request_resolves(self):
        after = self.report['after_pending_settle']
        self.assertFalse(after['button_disabled'],
                         'settling the held POST must re-enable the button')
        self.assertEqual(after['aria_busy'], 'false')
        self.assertNotEqual(after['status'], 'Submitting...',
                            'settling must replace the pending message')


if __name__ == '__main__':
    unittest.main()
