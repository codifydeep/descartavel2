"""AC3, AC7 and AC8 for the Reset control, exercised in Chromium against the served app.

Each test starts its own temporary app on a free local port and its own Chromium.
Cleanup is registered for both. Element presence is asserted before interaction.
"""
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

from playwright.sync_api import sync_playwright

APP = Path(__file__).parents[1] / 'app.py'
SHA = 'c' * 40
VALIDATION = 'Please enter a display name.'


class ResetBrowser(unittest.TestCase):
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

        self.requests = []
        self.page_errors = []
        self.console_errors = []
        self.page.on('request', lambda request: self.requests.append(request.url))
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

    def submit(self, name):
        self.page.fill('#display-name', name)
        self.page.click('#greet')

    def reset(self):
        self.page.click('#reset')


class ResetClearsFieldsAC3(ResetBrowser):
    def test_reset_control_is_visible_with_reset_label(self):
        self.assert_controls_present()
        self.assertEqual(' '.join(self.page.locator('#reset').text_content().split()), 'Reset')

    def test_reset_clears_name_input_and_greeting_without_navigating(self):
        self.assert_controls_present()
        self.page.evaluate("window.__sameDocument = 'kept'")
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.assertEqual(self.wait_for_text('#greeting', ''), '')
        self.assertEqual(self.page.input_value('#display-name'), '')
        self.assertEqual(self.page.evaluate('window.__sameDocument'), 'kept')
        self.assertEqual(self.page.url, self.base + '/')

    def test_reset_clears_inline_validation_message(self):
        self.assert_controls_present()
        self.submit('   ')
        self.assertEqual(self.wait_for_text('#validation', VALIDATION), VALIDATION)
        self.reset()
        self.assertEqual(self.wait_for_text('#validation', ''), '')
        self.assertEqual(self.page.input_value('#display-name'), '')
        self.assertEqual(self.visible_text('#greeting'), '')

    def test_reset_clears_input_so_a_blank_submit_after_reset_shows_validation(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.page.click('#greet')
        self.assertEqual(self.wait_for_text('#validation', VALIDATION), VALIDATION)
        self.assertEqual(self.visible_text('#greeting'), '')

    def test_reset_on_empty_page_is_harmless(self):
        self.assert_controls_present()
        self.reset()
        self.assertEqual(self.page.input_value('#display-name'), '')
        self.assertEqual(self.visible_text('#greeting'), '')
        self.assertEqual(self.visible_text('#validation'), '')
        self.assertEqual(self.page.url, self.base + '/')


class ResetPreservesGreetingAC7(ResetBrowser):
    def test_valid_name_after_reset_shows_trimmed_greeting(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.submit('  Bo  ')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Bo!'), 'Hello, Bo!')
        self.assertEqual(self.visible_text('#validation'), '')

    def test_markup_after_reset_is_plain_text(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        payload = '<i>Bo</i>'
        self.submit(payload)
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, ' + payload + '!'),
                         'Hello, ' + payload + '!')
        self.assertEqual(self.page.locator('#greeting i').count(), 0)

    def test_blank_then_valid_after_reset_replaces_validation_with_greeting(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.submit(' \t ')
        self.assertEqual(self.wait_for_text('#validation', VALIDATION), VALIDATION)
        self.assertEqual(self.visible_text('#greeting'), '')
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.assertEqual(self.visible_text('#validation'), '')


class ResetScopeAC8(ResetBrowser):
    def test_reset_flow_makes_only_same_origin_requests_without_page_errors(self):
        self.assert_controls_present()
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.reset()
        self.submit('   ')
        self.assertEqual(self.wait_for_text('#validation', VALIDATION), VALIDATION)
        external = [url for url in self.requests if not url.startswith(self.base + '/')]
        self.assertEqual(external, [], 'reset flow must not request other origins')
        self.assertEqual(self.page_errors, [], 'page raised errors')
        self.assertEqual(self.console_errors, [], 'page logged console errors')


if __name__ == '__main__':
    unittest.main()
