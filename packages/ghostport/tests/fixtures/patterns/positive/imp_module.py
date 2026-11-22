"""Positive: the imp module was removed in Python 3.12 (use importlib)."""
import imp


def load(path):
    return imp.load_source("mod", path)
