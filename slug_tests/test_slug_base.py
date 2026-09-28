import unittest

from slugapp import slugify


class SlugBaseTests(unittest.TestCase):
    def test_spaces(self):
        self.assertEqual(slugify('Hello World'), 'hello-world')

    def test_punctuation(self):
        self.assertEqual(slugify('  Hello, World!  '), 'hello-world')
