"""Positive: unittest fail* / assertEquals aliases were removed in Python 3.12."""
import unittest


class TestLegacy(unittest.TestCase):
    def test_values(self):
        self.failUnless(True)
        self.assertEquals(1, 1)
