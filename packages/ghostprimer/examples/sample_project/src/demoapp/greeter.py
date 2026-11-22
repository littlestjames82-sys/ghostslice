"""The greeting wording. Imported by the entry point."""


def greeting(name: str) -> str:
    """Return the greeting line for one name."""
    return f"hello, {name}"


def farewell(name: str) -> str:
    """Return the sign-off line for one name."""
    return f"bye, {name}"
