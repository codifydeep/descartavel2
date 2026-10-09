import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / 'app' / 'static' / 'index.html'
APP_JS = ROOT / 'app' / 'static' / 'app.js'


class FeedbackDetailUiTest(unittest.TestCase):
    def test_index_ships_feedback_detail_region(self):
        markup = INDEX.read_text(encoding='utf-8')
        self.assertIn('id="feedback-detail"', markup)
        self.assertIn('role="region"', markup)
        self.assertIn('aria-label="Feedback details"', markup)
        self.assertIn('Loading details…', markup)

    def test_client_wires_view_details_and_close_details(self):
        script = APP_JS.read_text(encoding='utf-8')
        self.assertIn('View details', script)
        self.assertIn('Close details', script)
        self.assertIn('Details unavailable', script)

    def test_client_renders_titles_as_text_only(self):
        script = APP_JS.read_text(encoding='utf-8')
        self.assertIn('textContent', script)
        self.assertNotIn('innerHTML = item.title', script)
        self.assertNotIn('innerHTML = data.item.title', script)


if __name__ == '__main__':
    unittest.main()
