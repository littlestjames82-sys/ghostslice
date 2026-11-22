"""Look-alike negative: math.gcd is the supported location."""
from math import gcd
import math


def common(a, b):
    return gcd(a, b) + math.gcd(a, b)
