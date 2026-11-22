"""Positive: distutils was removed in Python 3.12 (PEP 632)."""
import distutils
from distutils.core import setup


def main():
    return distutils, setup(name="legacy-demo")
