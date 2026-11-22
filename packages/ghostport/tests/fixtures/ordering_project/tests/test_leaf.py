"""Covering test for the leaf unit (fixture data, not a suite test).

It imports the leaf unit, which is how GhostPort's import-graph method
finds covering tests.
"""
import unittest

from pkg.leaf import load_leaf


class TestLeafFixture(unittest.TestCase):
    def test_placeholder(self):
        self.assertTrue(callable(load_leaf))
