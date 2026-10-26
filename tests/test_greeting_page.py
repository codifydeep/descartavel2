"""AC1 and AC2 for the greeting page, exercised over HTTP and in Chromium.

Pinned contract for the page (approved brief, team-chosen wording frozen here):
  input#display-name  text field for the display name
  button#greet        greeting button (no form navigation)
  #validation         inline validation message next to the field
  #greeting           greeting output
  greeting text       "Hello, <trimmed name>!"
  validation text     contains "Please enter a display name"
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

APP = Path(__file__).parents[1] / 'app.py'
SOURCE_SHA = 'b' * 40
VALIDATION_TEXT = 'Please enter a display name'


class GreetingPageTest(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen(
            [sys.executable, '-B', str(APP), '0'],
            env={**os.environ, 'FABRIQUINHA_SOURCE_SHA': SOURCE_SHA},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_server)
        self.port = int(self.process.stdout.readline())
        self.base = f'http://127.0.0.1:{self.port}'

        playwright = sync_playwright().start()
        self.addCleanup(playwright.stop)
        browser = playwright.chromium.launch()
        self.addCleanup(browser.close)
        self.page = browser.new_page()
        self.addCleanup(self.page.close)
        self.errors = []
        self.page.on('pageerror', lambda exc: self.errors.append(str(exc)))
        self.page.on('console', lambda msg: self.errors.append(msg.text)
                     if msg.type == 'error' else None)

    def stop_server(self):
        self.process.terminate()
        self.process.communicate(timeout=3)

    def open_page(self):
        self.page.goto(self.base + '/')
        self.assertEqual(self.page.locator('input#display-name').count(), 1)
        self.assertEqual(self.page.locator('button#greet').count(), 1)
        self.assertEqual(self.page.locator('#validation').count(), 1)
        self.assertEqual(self.page.locator('#greeting').count(), 1)
        self.assertTrue(self.page.locator('input#display-name').is_visible())
        self.assertTrue(self.page.locator('button#greet').is_visible())
        # Marker survives only if the page is not reloaded or navigated.
        self.page.evaluate('window.__marker = 42')

    def submit(self, name):
        self.page.fill('input#display-name', name)
        self.page.click('button#greet')

    def assert_same_page_no_navigation(self):
        self.assertEqual(self.page.url, self.base + '/')
        self.assertEqual(self.page.evaluate('window.__marker'), 42)

    def greeting_shown(self):
        locator = self.page.locator('#greeting')
        return locator.is_visible() and locator.text_content().strip() != ''

    def validation_shown(self):
        locator = self.page.locator('#validation')
        return locator.is_visible() and VALIDATION_TEXT in locator.text_content()

    # AC1: HTTP

    def test_root_serves_html_page_over_http(self):
        request = Request(self.base + '/')
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers['Content-Type'].startswith('text/html'))
            body = response.read().decode()
        self.assertNotIn('http://', body)
        self.assertNotIn('https://', body)

    # AC1: browser

    def test_valid_name_shows_trimmed_greeting_on_same_page(self):
        self.open_page()
        self.submit('  Ana  ')
        self.assertTrue(self.page.locator('#greeting').is_visible())
        self.assertEqual(self.page.locator('#greeting').text_content().strip(), 'Hello, Ana!')
        self.assert_same_page_no_navigation()
        self.assertEqual(self.errors, [])

    def test_markup_in_name_is_shown_as_plain_text(self):
        self.open_page()
        payload = '<b>Ana</b><img src=x onerror="window.__xss=1">'
        self.submit(payload)
        self.assertTrue(self.page.locator('#greeting').is_visible())
        self.assertEqual(self.page.locator('#greeting').text_content(),
                         f'Hello, {payload}!')
        self.assertEqual(self.page.locator('#greeting b').count(), 0)
        self.assertEqual(self.page.locator('#greeting img').count(), 0)
        self.assertIsNone(self.page.evaluate('window.__xss'))
        self.assert_same_page_no_navigation()

    # AC2: browser

    def test_blank_field_shows_inline_validation_without_greeting(self):
        self.open_page()
        self.assertFalse(self.validation_shown())
        self.submit('')
        self.assertTrue(self.page.locator('#validation').is_visible())
        self.assertIn(VALIDATION_TEXT, self.page.locator('#validation').text_content())
        self.assertFalse(self.greeting_shown())
        self.assert_same_page_no_navigation()

    def test_whitespace_only_field_shows_inline_validation_without_greeting(self):
        self.open_page()
        self.submit(' \t   ')
        self.assertTrue(self.page.locator('#validation').is_visible())
        self.assertIn(VALIDATION_TEXT, self.page.locator('#validation').text_content())
        self.assertFalse(self.greeting_shown())
        self.assert_same_page_no_navigation()

    def test_validation_message_is_next_to_the_field(self):
        self.open_page()
        self.submit('   ')
        field = self.page.locator('input#display-name').bounding_box()
        message = self.page.locator('#validation').bounding_box()
        self.assertIsNotNone(message)
        self.assertLessEqual(abs(message['y'] - (field['y'] + field['height'])), 120)

    def test_blank_submission_clears_previous_greeting(self):
        self.open_page()
        self.submit('Ana')
        self.assertTrue(self.greeting_shown())
        self.submit('   ')
        self.assertTrue(self.validation_shown())
        self.assertFalse(self.greeting_shown())
        self.assert_same_page_no_navigation()

    def test_valid_submission_after_validation_replaces_message(self):
        self.open_page()
        self.submit('')
        self.assertTrue(self.validation_shown())
        self.submit('Ana')
        self.assertFalse(self.validation_shown())
        self.assertEqual(self.page.locator('#greeting').text_content().strip(), 'Hello, Ana!')
        self.assert_same_page_no_navigation()
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
