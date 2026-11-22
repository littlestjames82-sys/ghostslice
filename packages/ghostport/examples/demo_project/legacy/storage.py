"""Demo leaf: config loading with a removed API (PYUP006)."""
import configparser


def load_settings(path):
    parser = configparser.SafeConfigParser()
    parser.read(path)
    return parser
