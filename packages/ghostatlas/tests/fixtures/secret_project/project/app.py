"""Small application module for the offline / secret fixture."""

from vault import load_setting


def main():
    """Return a setting loaded from the vault module."""
    return load_setting()
