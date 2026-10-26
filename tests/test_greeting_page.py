"""AC1 and AC2 for the greeting page, exercised against the HTTP-served app.

Each test starts its own temporary app on a free local port and, for browser
tests, its own Chromium. Cleanup is registered for both.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

APP = Path(__file__).parents[1] / 'app.py'
SHA = 'b' * 40


class AppServer(unittest.TestCase):
    def start_app(self):
        self.process = subprocess.Popen(
            [sys.executable, '-B', str(APP), '0'],
            env={**os.environ, 'FABRIQUINHA_SOURCE_SHA': SHA},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_app)
        line = self.process.stdout.readline()
        self.assertTrue(line.strip(), 'app did not report a port')
        self.base = f'http://127.0.0.1:{int(line)}'

    def stop_app(self):
        self.process.terminate()
        self.process.communicate(timeout=3)


class GreetingHttpContract(AppServer):
    def setUp(self):
        self.start_app()

    def test_page_is_served_as_html_at_root(self):
        try:
            with urlopen(self.base + '/', timeout=3) as response:
                status = response.status
                content_type = response.headers.get('Content-Type', '')
        except HTTPError as error:
            status, content_type = error.code, ''
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith('text/html'), content_type)

    def test_identity_reflects_runtime_sha(self):
        with urlopen(self.base + '/identity', timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), {'source_sha': SHA})


class GreetingBrowser(AppServer):
    def setUp(self):
        self.start_app()
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch()
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.goto(self.base + '/')

    def assert_form_present(self):
        for selector in ('#display-name', '#greet', '#greeting', '#validation'):
            locator = self.page.locator(selector)
            self.assertEqual(locator.count(), 1, f'{selector} must exist exactly once')
        self.assertTrue(self.page.locator('#display-name').is_visible(), '#display-name not visible')
        self.assertTrue(self.page.locator('#greet').is_visible(), '#greet not visible')

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


class GreetingPageAC1(GreetingBrowser):
    def test_valid_name_shows_trimmed_greeting_on_same_page(self):
        self.assert_form_present()
        self.page.evaluate("window.__sameDocument = 'kept'")
        self.submit('  Ana  ')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.assertEqual(self.page.evaluate("window.__sameDocument"), 'kept')
        self.assertEqual(self.page.url, self.base + '/')

    def test_markup_in_name_is_plain_text_not_html(self):
        self.assert_form_present()
        payload = '<b>Ana</b><img src=x onerror="window.__xss = 1">'
        self.submit(payload)
        self.assertEqual(
            self.wait_for_text('#greeting', 'Hello, ' + payload + '!'),
            'Hello, ' + payload + '!')
        self.assertEqual(self.page.locator('#greeting b').count(), 0)
        self.assertEqual(self.page.locator('#greeting img').count(), 0)
        self.assertIsNone(self.page.evaluate("window.__xss"))


class GreetingPageAC2(GreetingBrowser):
    def test_blank_submission_shows_inline_validation_and_no_greeting(self):
        self.assert_form_present()
        self.page.evaluate("window.__sameDocument = 'kept'")
        self.submit('')
        self.assertEqual(
            self.wait_for_text('#validation', 'Please enter a display name.'),
            'Please enter a display name.')
        self.assertEqual(self.visible_text('#greeting'), '')
        self.assertEqual(self.page.evaluate("window.__sameDocument"), 'kept')

    def test_whitespace_only_submission_shows_inline_validation_and_no_greeting(self):
        self.assert_form_present()
        self.submit(' \t  ')
        self.assertEqual(
            self.wait_for_text('#validation', 'Please enter a display name.'),
            'Please enter a display name.')
        self.assertEqual(self.visible_text('#greeting'), '')

    def test_valid_submission_after_validation_replaces_message_with_greeting(self):
        self.assert_form_present()
        self.submit('   ')
        self.assertEqual(
            self.wait_for_text('#validation', 'Please enter a display name.'),
            'Please enter a display name.')
        self.submit('Ana')
        self.assertEqual(self.wait_for_text('#greeting', 'Hello, Ana!'), 'Hello, Ana!')
        self.assertEqual(self.visible_text('#validation'), '')


if __name__ == '__main__':
    unittest.main()
