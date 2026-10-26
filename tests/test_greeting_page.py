"""Browser tests for the greeting page (AC1, AC2).

Each test starts the app in a subprocess on a free port and drives Chromium
through playwright.sync_api. Locators are asserted before interaction, so a
missing element fails as an assertion, not as an unhandled selector error.
Selectors are pinned via data-testid; greeting wording is deliberately not
pinned (only the trimmed name is checked).
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest

from playwright.sync_api import sync_playwright, expect

APP = Path(__file__).parents[1] / 'app.py'
EXPECT_TIMEOUT = 3000
SOURCE_SHA = 'b' * 40

NAME_INPUT = '[data-testid="name-input"]'
SUBMIT = '[data-testid="submit"]'
VALIDATION = '[data-testid="validation"]'
GREETING = '[data-testid="greeting"]'
GREETING_TEXT = 'Hello, {name}!'
VALIDATION_TEXT = 'Please enter a display name.'


class GreetingPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, 'FABRIQUINHA_SOURCE_SHA': SOURCE_SHA}
        cls.server = subprocess.Popen(
            [sys.executable, '-B', str(APP), '0'], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        cls.addClassCleanup(cls.stop_server)
        cls.port = int(cls.server.stdout.readline())
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        cls.server.communicate(timeout=3)

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.errors = []
        self.page.on('pageerror', lambda exc: self.errors.append(str(exc)))
        self.page.on('console', lambda msg: self.errors.append(msg.text)
                     if msg.type == 'error' else None)
        self.page.goto(f'http://127.0.0.1:{self.port}/')

    def mark_page(self):
        # A JS marker disappears on any full page navigation or reload.
        self.page.evaluate('window.__greetingMarker = 1')

    def assert_same_page(self):
        self.assertEqual(self.page.evaluate('window.__greetingMarker'), 1,
                         'page was reloaded or navigated')
        self.assertEqual(self.page.url, f'http://127.0.0.1:{self.port}/')

    def submit(self, value):
        self.page.locator(NAME_INPUT).fill(value)
        self.page.locator(SUBMIT).click()

    def test_valid_name_is_greeted_on_same_page_with_trimmed_name(self):
        expect(self.page.locator(NAME_INPUT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(SUBMIT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(GREETING)).to_have_count(0, timeout=EXPECT_TIMEOUT)
        self.mark_page()
        self.submit('  Ana  ')
        greeting = self.page.locator(GREETING)
        expect(greeting).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(greeting).to_have_text(GREETING_TEXT.format(name='Ana'), timeout=EXPECT_TIMEOUT)
        self.assert_same_page()
        self.assertEqual(self.errors, [])

    def test_blank_submission_shows_inline_validation_and_no_greeting(self):
        expect(self.page.locator(NAME_INPUT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(SUBMIT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        self.mark_page()
        self.submit('')
        message = self.page.locator(VALIDATION)
        expect(message).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(message).to_have_text(VALIDATION_TEXT, timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(GREETING)).to_have_count(0, timeout=EXPECT_TIMEOUT)
        self.assert_same_page()

    def test_whitespace_only_submission_shows_validation_and_no_greeting(self):
        expect(self.page.locator(NAME_INPUT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(SUBMIT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        self.mark_page()
        self.submit('   \t  ')
        expect(self.page.locator(VALIDATION)).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(GREETING)).to_have_count(0, timeout=EXPECT_TIMEOUT)
        self.assert_same_page()

    def test_blank_after_valid_greeting_removes_greeting(self):
        expect(self.page.locator(NAME_INPUT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(SUBMIT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        self.submit('Ana')
        expect(self.page.locator(GREETING)).to_be_visible(timeout=EXPECT_TIMEOUT)
        self.submit('   ')
        expect(self.page.locator(VALIDATION)).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(GREETING)).to_have_count(0, timeout=EXPECT_TIMEOUT)

    def test_typed_markup_is_shown_as_plain_text(self):
        expect(self.page.locator(NAME_INPUT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(SUBMIT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        payload = '<b>Bob</b>'
        self.mark_page()
        self.submit(payload)
        greeting = self.page.locator(GREETING)
        expect(greeting).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(greeting).to_contain_text(payload, timeout=EXPECT_TIMEOUT)
        self.assertEqual(greeting.locator('b').count(), 0, 'markup was rendered as HTML')
        self.assert_same_page()

    def test_valid_submission_replaces_validation_message(self):
        expect(self.page.locator(NAME_INPUT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(SUBMIT)).to_be_visible(timeout=EXPECT_TIMEOUT)
        self.submit('')
        expect(self.page.locator(VALIDATION)).to_be_visible(timeout=EXPECT_TIMEOUT)
        self.mark_page()
        self.submit('Ana')
        expect(self.page.locator(GREETING)).to_be_visible(timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(GREETING)).to_contain_text('Ana', timeout=EXPECT_TIMEOUT)
        expect(self.page.locator(VALIDATION)).to_have_count(0, timeout=EXPECT_TIMEOUT)
        self.assert_same_page()


if __name__ == '__main__':
    unittest.main()
