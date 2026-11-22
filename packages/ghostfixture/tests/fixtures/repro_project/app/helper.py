"""Local dependency of main.py.

Deliberately NOT referenced by the fixture bundle. A correct
GhostFixture run includes this file anyway, because main.py
imports it: that is the import-closure rule. This module itself
imports app.util_math, a second closure level, which the plan's
verification bar also requires in the fixture.
"""
from app.util_math import add_all


def compute_total(prices):
    return add_all(prices)
