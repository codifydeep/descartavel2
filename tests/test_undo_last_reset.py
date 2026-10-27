"""AC4, AC5 and AC6 for Undo last Reset, exercised in Chromium against the served app.

Each test starts its own temporary app on a free local port and its own Chromium.
Cleanup is registered for both. Element presence is asserted before interaction.
Undo availability is checked mechanism-neutrally: a usable Undo is present, visible
and enabled. Unavailable Undo may be absent or disabled, so tests that must prove
inertness dispatch a click only when the control exists.
"""
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

from playwright.sync_api import sync_playwright

APP = Path(__file__).parents[1] / 'app.py'
SHA = 'd' * 40
VALIDATION = 'Please enter a display name.'


class UndoBrowser(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen(
            [sys.executable, '-B', str(APP), '0'],
            env={**os.environ, 'FABRIQUINHA_SOURCE_SHA': SHA},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_app)
        line = self.process.stdout.readline()
        self.assertTrue(line.strip(), 'app did not report a port')
        self.base = f'http://127.0.0.1:{int(line)}'

        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch()
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

        self.page_errors = []
        self.console_errors = []
        self.page.on('pageerror', lambda error: self.page_errors.append(str(error)))
        self.page.on('console', lambda message: self.console_errors.append(message.text)
                     if message.type == 'error' else None)
        self.page.goto(self.base + '/')

    def stop_app(self):
        self.process.terminate()
        self.process.communicate(timeout=3)

    def assert_controls_present(self):
        for selector in ('#display-name', '#greet', '#reset', '#greeting', '#validation'):
            locator = self.page.locator(selector)
            self.assertEqual(locator.count(), 1, f'{selector} must exist exactly once')
        self.assertTrue(self.page.locator('#display-name').is_visible(), '#display-name not visible')
        self.assertTrue(self.page.locator('#greet').is_visible(), '#greet not visible')
        self.assertTrue(self.page.locator('#reset').is_visible(), '#reset not visible')

    def undo_actionable(self):
        locator = self.page.locator('#undo')
        return locator.count() == 1 and locator.is_visible() and locator.is_enabled()

    def assert_undo_actionable(self):
        locator = self.page.locator('#undo')
        self.assertEqual(locator.count(), 1, '#undo must exist exactly once after Reset')
        self.assertTrue(locator.is_visible(), '#undo not visible after Reset')
        self.assertTrue(locator.is_enabled(), '#undo disabled after Reset')

    def assert_undo_unavailable(self):
        self.assertFalse(self.undo_actionable(), 'Undo must be unavailable here')

    def attempt_inert_undo(self):
        # Unavailable Undo must not change anything. Dispatch is used so a disabled
        # control cannot stall the test; an absent control is simply skipped.
        if self.page.locator('#undo').count() == 1:
            self.page.locator('#undo').dispatch_event('click')

    def visible_text(self, selector):
        locator = self.page.locator(selector)
        if locator.count() == 0 or not locator.first.is_visible():
            return ''
        return ' '.join((locator.first.text_content() or '').split())

    def wait_for_text(self, selector, expected, timeout=3.0):
        deadline = time.monotonic() + timeout
        text = self.visible_text(selector)
        while text != expected and time.monotonic() < deadline:
            time.sleep(0.05)
            text = self.visible_text(selector)
        return text

    def wait_for_value(self, selector, expected, timeout=3.0):
        deadline = time.monotonic() + timeout
        value = self.page.input_value(selector)
        while value != expected and time.monotonic() < deadline:
            time.sleep(0.05)
            value = self.page.input_value(selector)
        return value

    def submit(self, name):
        self.page.fill('#display-name', name)
        self.page.click('#greet')

    def reset(self):
        self.page.click('#reset')

    def undo(self):
        self.assert_undo_actionable()
        self.page.click('#undo')


class UndoUnavailableBeforeFirstResetAC4(UndoBrowser):
    def test_undo_is_unavailable_before_any_reset_after_submit(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.assert_undo_unavailable()
        self.attempt_inert_undo()
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.assertEqual(self.page.input_value('#display-name'), 'Ana')

    def test_undo_is_unavailable_on_fresh_page(self):
        self.assert_controls_present()
        self.assert_undo_unavailable()
        self.attempt_inert_undo()
        self.assertEqual(self.visible_text('#greeting'), '')
        self.assertEqual(self.visible_text('#validation'), '')
        self.assertEqual(self.page.input_value('#display-name'), '')


class UndoRestoresExactStateAC4(UndoBrowser):
    def test_undo_after_reset_restores_greeting_and_input_without_navigating(self):
        self.assert_controls_present()
        self.page.evaluate("window.__sameDocument = 'kept'")
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.assertEqual(self.wait_for_text('#greeting', ''), '')
        self.assertEqual(self.page.input_value('#display-name'), '')
        self.undo()
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.assertEqual(self.wait_for_value('#display-name', 'Ana'), 'Ana')
        self.assertEqual(self.visible_text('#validation'), '')
        self.assertEqual(self.page.evaluate('window.__sameDocument'), 'kept')
        self.assertEqual(self.page.url, self.base + '/')

    def test_undo_after_reset_restores_inline_validation_and_input(self):
        self.assert_controls_present()
        self.submit('   ')
        self.assertEqual(self.wait_for_text('#validation', VALIDATION), VALIDATION)
        self.reset()
        self.assertEqual(self.wait_for_text('#validation', ''), '')
        self.assertEqual(self.page.input_value('#display-name'), '')
        self.undo()
        self.assertEqual(self.wait_for_text('#validation', VALIDATION), VALIDATION)
        self.assertEqual(self.wait_for_value('#display-name', '   '), '   ')
        self.assertEqual(self.visible_text('#greeting'), '')

    def test_undo_after_reset_on_empty_page_restores_empty_state(self):
        self.assert_controls_present()
        self.reset()
        self.undo()
        self.assertEqual(self.wait_for_value('#display-name', ''), '')
        self.assertEqual(self.visible_text('#greeting'), '')
        self.assertEqual(self.visible_text('#validation'), '')
        self.assertEqual(self.page.url, self.base + '/')


class UndoWorksOnceAC5(UndoBrowser):
    def test_second_undo_after_one_undo_is_not_available(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.undo()
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.assert_undo_unavailable()
        self.page.fill('#display-name', 'Bo')
        self.attempt_inert_undo()
        self.assertEqual(self.wait_for_value('#display-name', 'Bo'), 'Bo')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.assertEqual(self.page.url, self.base + '/')


class UndoConsumedBySubmitAC6(UndoBrowser):
    def test_valid_submit_after_reset_consumes_undo(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.submit('Bo')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Bo!'), 'Hello, Bo!')
        self.assert_undo_unavailable()
        self.attempt_inert_undo()
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Bo!'), 'Hello, Bo!')
        self.assertEqual(self.page.input_value('#display-name'), 'Bo')

    def test_blank_submit_after_reset_consumes_undo(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.submit('   ')
        self.assertEqual(self.wait_for_text('#validation', VALIDATION), VALIDATION)
        self.assert_undo_unavailable()
        self.attempt_inert_undo()
        self.assertEqual(self.wait_for_text('#validation', VALIDATION), VALIDATION)
        self.assertEqual(self.visible_text('#greeting'), '')
        self.assertEqual(self.page.input_value('#display-name'), '   ')

    def test_later_reset_replaces_snapshot_with_state_before_that_reset(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.submit('Bo')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Bo!'), 'Hello, Bo!')
        self.reset()
        self.assertEqual(self.wait_for_text('#greeting', ''), '')
        self.undo()
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Bo!'), 'Hello, Bo!')
        self.assertEqual(self.wait_for_value('#display-name', 'Bo'), 'Bo')

    def test_reset_on_empty_page_replaces_earlier_snapshot(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.reset()
        self.undo()
        self.assertEqual(self.wait_for_text('#greeting', ''), '')
        self.assertEqual(self.wait_for_value('#display-name', ''), '')
        self.assertEqual(self.visible_text('#validation'), '')


class UndoMemoryOnlyAC4(UndoBrowser):
    def test_undo_snapshot_is_not_retained_across_reload(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.assertEqual(self.wait_for_text('#greeting', ''), '')
        self.assert_undo_actionable()
        self.page.reload()
        self.assert_controls_present()
        self.assert_undo_unavailable()
        self.attempt_inert_undo()
        self.assertEqual(self.visible_text('#greeting'), '')
        self.assertEqual(self.visible_text('#validation'), '')
        self.assertEqual(self.page.input_value('#display-name'), '')
        self.assertEqual(self.page.url, self.base + '/')


if __name__ == '__main__':
    unittest.main()
