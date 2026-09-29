import unittest

from slugapp import slugify


class LigatureSlugTests(unittest.TestCase):
    def test_capital_ae_ligature_transliterates_to_ae(self):
        self.assertEqual(slugify('Æther'), 'aether')

    def test_lowercase_ae_ligature_transliterates_to_ae(self):
        self.assertEqual(slugify('æther'), 'aether')


if __name__ == '__main__':
    unittest.main()
