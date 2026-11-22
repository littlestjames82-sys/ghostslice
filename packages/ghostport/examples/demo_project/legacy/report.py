"""Demo entry point: imports the leaves, one removed API (PYUP003)."""
import inspect

from legacy.plugin_loader import load_plugin
from legacy.storage import load_settings


def describe(fn):
    return inspect.getargspec(fn)


def main(settings_path, plugin_path):
    return load_settings, load_plugin, describe
