"""Module A of the import-cycle project fixture: imports b."""
from b import b_value


def a_value():
    """Value from A, built on B."""
    return "a+" + b_value()
