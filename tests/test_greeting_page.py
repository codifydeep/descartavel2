"""Acceptance tests for the greeting page (AC1, AC2).

The page is served by app.py on an ephemeral port and driven through Chromium
via playwright.sync_api. Test-only dependency: product code never imports it.

Frozen UI contract used by these tests:
  #display-name  text input for the name (exactly one)
  #greet-button  greeting button (exactly one, inside the single form)
  #name-error    inline validation message next to the input
  #greeting      greeting output; may be absent or hidden when there is none
"""
import http.client
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[1]
NAME = '#display-name'
BUTTON = '#greet-button'
MESSAGE = '#name-error'
GREETING = '#greeting'
SHA = 'b' * 40
MAX_GAP_PX = 150


def start_app():
    process = subprocess.Popen(
        [sys.executable, '-B', str(ROOT / 'app.py'), '0'],
        env={**os.environ, 'FABRIQUINHA_SOURCE_SHA': SHA},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = process.stdout.readline()
    if not line:
        raise RuntimeError(f'app.py did not start: {process.stderr.read()}')
    return process, int(line)


def stop_app(process):
    process.terminate()
    process.communicate(timeout=3)


def visible_text(page, selector):
    locator = page.locator(selector)
    if locator.count() == 0 or not locator.first.is_visible():
        return ''
    return locator.first.inner_text().strip()


def wait_for_text(page, selector, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    text = visible_text(page, selector)
    while not predicate(text) and time.monotonic() < deadline:
        page.wait_for_timeout(50)
        text = visible_text(page, selector)
    return text


class GreetingPageCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.process, cls.port = start_app()
        cls.addClassCleanup(stop_app, cls.process)
        cls.base = f'http://127.0.0.1:{cls.port}'
        playwright = sync_playwright().start()
        cls.addClassCleanup(playwright.stop)
        cls.browser = playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def open_page(self):
        self.problems = []
        self.requests = []
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.on('console', lambda m: self.problems.append(m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: self.problems.append(str(e)))
        page.on('request', lambda r: self.requests.append(r.url))
        page.goto(self.base + '/')
        return page

    def assert_initial_state(self, page):
        self.assertEqual(page.locator('form').count(), 1, 'page must contain exactly one form')
        self.assertEqual(page.locator(NAME).count(), 1, 'name input missing')
        self.assertEqual(page.locator(BUTTON).count(), 1, 'greeting button missing')
        self.assertTrue(page.locator(NAME).first.is_visible(), 'name input must be visible')
        self.assertTrue(page.locator(BUTTON).first.is_visible(), 'greeting button must be visible')
        self.assertEqual(visible_text(page, GREETING), '', 'no greeting before submit')
        self.assertEqual(visible_text(page, MESSAGE), '', 'no validation message before submit')

    def mark_same_document(self, page):
        page.evaluate("window.__sameDocument = 'kept'")

    def assert_same_document(self, page):
        self.assertEqual(page.evaluate('window.__sameDocument'), 'kept', 'page navigated or reloaded')
        self.assertEqual(page.url, self.base + '/', 'URL changed on submit')

    def test_root_is_served_as_html(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        self.addCleanup(connection.close)
        connection.request('GET', '/')
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 200)
        self.assertTrue(response.getheader('Content-Type', '').startswith('text/html'))

    def test_valid_name_shows_trimmed_greeting_on_same_page(self):
        page = self.open_page()
        self.assert_initial_state(page)
        self.mark_same_document(page)
        page.fill(NAME, '  Ana  ')
        page.click(BUTTON)
        greeting = wait_for_text(page, GREETING, lambda t: 'Ana' in t)
        self.assertIn('Ana', greeting)
        self.assertNotIn('  Ana', greeting)
        self.assertNotIn('Ana  ', greeting)
        self.assert_same_document(page)
        self.assertEqual(visible_text(page, MESSAGE), '')

    def test_markup_in_name_is_shown_as_literal_text(self):
        page = self.open_page()
        self.assert_initial_state(page)
        page.fill(NAME, '<b>x</b>')
        page.click(BUTTON)
        greeting = wait_for_text(page, GREETING, lambda t: '<b>x</b>' in t)
        self.assertIn('<b>x</b>', greeting)
        self.assertEqual(page.locator(f'{GREETING} *').count(), 0, 'markup was rendered as HTML')
        self.assertEqual(page.locator('b').count(), 0, 'markup was rendered as HTML')

    def test_blank_or_whitespace_name_shows_inline_validation_and_no_greeting(self):
        for value in ['', '   ', '\t  ']:
            with self.subTest(value=value):
                page = self.open_page()
                self.assert_initial_state(page)
                self.mark_same_document(page)
                page.fill(NAME, value)
                page.click(BUTTON)
                message = wait_for_text(page, MESSAGE, lambda t: t != '')
                self.assertNotEqual(message, '', 'no validation message shown')
                self.assertIn('Please enter a name', message)
                self.assertEqual(visible_text(page, GREETING), '', 'greeting shown for blank name')
                inp = page.locator(NAME).first.bounding_box()
                msg = page.locator(MESSAGE).first.bounding_box()
                gap = max(msg['y'] - (inp['y'] + inp['height']), inp['y'] - (msg['y'] + msg['height']))
                self.assertLessEqual(gap, MAX_GAP_PX, 'validation message is not next to the field')
                self.assert_same_document(page)

    def test_valid_submission_after_blank_replaces_message_with_greeting(self):
        page = self.open_page()
        self.assert_initial_state(page)
        page.fill(NAME, '   ')
        page.click(BUTTON)
        self.assertNotEqual(wait_for_text(page, MESSAGE, lambda t: t != ''), '', 'no validation message shown')
        page.fill(NAME, 'Ana')
        page.click(BUTTON)
        greeting = wait_for_text(page, GREETING, lambda t: 'Ana' in t)
        self.assertIn('Ana', greeting)
        self.assertEqual(visible_text(page, MESSAGE), '', 'validation message not replaced')

    def test_only_same_origin_requests_and_no_browser_errors(self):
        page = self.open_page()
        self.assert_initial_state(page)
        page.fill(NAME, 'Ana')
        page.click(BUTTON)
        self.assertIn('Ana', wait_for_text(page, GREETING, lambda t: 'Ana' in t))
        for url in self.requests:
            self.assertTrue(url.startswith(self.base) or url.startswith('data:'), f'external request: {url}')
        self.assertEqual(self.problems, [], 'browser reported page or console errors')
