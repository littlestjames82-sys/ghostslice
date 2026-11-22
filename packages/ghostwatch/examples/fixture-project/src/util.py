"""Fixture utility module."""


def slugify(text):
    """Turn display text into a slug."""
    return "-".join(text.lower().split())
