"""Demo leaf: plugin loading with a removed module (PYUP004)."""
import imp


def load_plugin(path):
    return imp.load_source("plugin", path)
