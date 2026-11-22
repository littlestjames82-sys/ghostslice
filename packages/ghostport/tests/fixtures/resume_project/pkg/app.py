"""Resume fixture app (getargspec, PYUP003), imports leaf."""
import inspect

from pkg.leaf import load_leaf


def describe(fn):
    return inspect.getargspec(fn)
