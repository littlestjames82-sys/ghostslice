"""Look-alike negative: getfullargspec is the supported replacement."""
import inspect


def describe(fn):
    return inspect.getfullargspec(fn)
