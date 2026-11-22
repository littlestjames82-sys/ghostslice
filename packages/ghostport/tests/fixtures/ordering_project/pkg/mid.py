"""Mid unit: imports leaf, one pattern hit (SafeConfigParser, PYUP006)."""
import configparser

from pkg.leaf import load_leaf


def load_config(path):
    parser = configparser.SafeConfigParser()
    parser.read(path)
    return load_leaf, parser
