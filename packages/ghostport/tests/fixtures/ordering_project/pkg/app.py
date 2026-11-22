"""App unit (entry point): imports mid, one pattern hit (getargspec, PYUP003)."""
import inspect

from pkg.mid import load_config


def describe(fn):
    return inspect.getargspec(fn)


def main():
    return load_config
