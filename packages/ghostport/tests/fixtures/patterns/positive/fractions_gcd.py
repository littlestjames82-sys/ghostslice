"""Positive: fractions.gcd was removed in Python 3.9 (use math.gcd)."""
import fractions
from fractions import gcd


def common(a, b):
    return gcd(a, b) + fractions.gcd(a, b)
