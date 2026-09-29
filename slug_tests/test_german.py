import unittest

from slugapp import slugify


class GermanSlugTests(unittest.TestCase):
    def test_sharp_s_transliterates_to_ss(self):
        self.assertEqual(slugify('Straße'), 'strasse')

    def test_sharp_s_in_compound_word(self):
        self.assertEqual(slugify('Fußball'), 'fussball')

    def test_umlaut_keeps_existing_transliteration_with_sharp_s(self):
        # Umlauts keep their pre-existing behavior (stripped to the base vowel);
        # only the sharp s transliterates to ss.
        self.assertEqual(slugify('Grüße'), 'grusse')

    def test_capital_sharp_s_transliterates_to_ss(self):
        self.assertEqual(slugify('STRAẞE'), 'strasse')

    def test_sharp_s_within_phrase(self):
        self.assertEqual(slugify('Die Straße ist frei'), 'die-strasse-ist-frei')


if __name__ == '__main__':
    unittest.main()
