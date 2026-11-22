"""Positive: inspect.getargspec was removed in Python 3.11."""
import inspect


def describe(fn):
    return inspect.getargspec(fn)
