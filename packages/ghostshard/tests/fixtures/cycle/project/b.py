"""Module B of the import-cycle project fixture: imports a."""
from a import a_value


def b_value():
    """Value from B, built on A (completing the import cycle)."""
    return "b"
