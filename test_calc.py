import unittest

from calc import add, multiply


class CalcTests(unittest.TestCase):
    def test_add_positive(self):
        self.assertEqual(add(2, 3), 5)

    def test_add_negative(self):
        self.assertEqual(add(-2, 3), 1)


class MultiplyTests(unittest.TestCase):
    def test_multiply_positive(self):
        self.assertEqual(multiply(2, 3), 6)

    def test_multiply_by_zero(self):
        self.assertEqual(multiply(5, 0), 0)

    def test_multiply_negative(self):
        self.assertEqual(multiply(-2, 4), -8)

    def test_multiply_commutative(self):
        self.assertEqual(multiply(7, 3), multiply(3, 7))
