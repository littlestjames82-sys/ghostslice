"""Resume fixture leaf (imp, PYUP004)."""
import imp


def load_leaf(path):
    return imp.load_source("leaf_mod", path)
