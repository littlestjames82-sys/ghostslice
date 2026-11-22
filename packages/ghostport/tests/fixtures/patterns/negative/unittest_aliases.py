"""Look-alike negative: modern assertion names only."""
import unittest


class TestModern(unittest.TestCase):
    def test_values(self):
        self.assertTrue(True)
        self.assertEqual(1, 1)
