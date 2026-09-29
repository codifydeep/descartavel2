import unittest

from slugapp import slugify


class UnicodeSlugTests(unittest.TestCase):
    def test_transliterates_accented_word(self):
        self.assertEqual(slugify('Olá Mundo'), 'ola-mundo')

    def test_transliterates_cedilla_word(self):
        self.assertEqual(slugify('Ação'), 'acao')


if __name__ == '__main__':
    unittest.main()