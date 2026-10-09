import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")


class MatchCountPendingStateTest(unittest.TestCase):
    def test_load_match_count_writes_pending_text_before_fetch(self):
        start = APP_JS.index("function loadMatchCount()")
        end = APP_JS.index("\n}\n", start)
        body = APP_JS[start:end]
        fetch_at = body.index("fetch(matchCountUrl()")
        pending_write = body.find("'Matching: \\u2026'")
        self.assertNotEqual(pending_write, -1,
                            "loadMatchCount must write the pending text")
        self.assertLess(pending_write, fetch_at,
                        "pending text must be written before the fetch")
        self.assertIn("fetch(matchCountUrl(), { headers: { Accept: 'application/json' } })",
                      body)


if __name__ == "__main__":
    unittest.main()
