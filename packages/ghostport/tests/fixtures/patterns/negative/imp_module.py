"""Look-alike negative: importlib is current; the letters imp appear only inside other words."""
import importlib
import importlib.util


IMPLIES = "implementation detail: an imp is not imported here"


def load(name):
    return importlib.import_module(name)
