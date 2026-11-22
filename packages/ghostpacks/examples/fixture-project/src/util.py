"""Demo utility module."""


def slugify(text):
    """Turn display text into a slug."""
    return "-".join(text.lower().split())


def clamp(value, low, high):
    """Clamp a value into a range."""
    return max(low, min(high, value))
