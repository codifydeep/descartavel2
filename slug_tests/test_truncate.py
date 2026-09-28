import unittest

from slugapp import truncate_slug


class TruncateSlugTests(unittest.TestCase):
    def test_truncates_to_max_length(self):
        self.assertEqual(truncate_slug('Hello World', 8), 'hello-wo')

    # --- boundary tests ---
    def test_removes_trailing_hyphen_at_cut(self):
        self.assertEqual(truncate_slug('Hello World', 6), 'hello')

    def test_max_length_exactly_slug_length(self):
        self.assertEqual(truncate_slug('Hello World', 11), 'hello-world')

    def test_max_length_larger_than_slug(self):
        self.assertEqual(truncate_slug('Hello World', 100), 'hello-world')

    def test_max_length_one(self):
        self.assertEqual(truncate_slug('Hello World', 1), 'h')

    def test_empty_slug(self):
        self.assertEqual(truncate_slug('!!!', 5), '')

    # --- invalid-limit tests ---
    def test_zero_max_length_raises(self):
        with self.assertRaises(ValueError):
            truncate_slug('Hello World', 0)

    def test_negative_max_length_raises(self):
        with self.assertRaises(ValueError):
            truncate_slug('Hello World', -1)

    def test_non_integer_max_length_raises(self):
        for bad in ('5', 3.5, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    truncate_slug('Hello World', bad)

    def test_boolean_max_length_raises(self):
        for bad in (True, False):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    truncate_slug('Hello World', bad)


if __name__ == '__main__':
    unittest.main()
