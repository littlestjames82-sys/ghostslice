"""Fixture application module for the GhostWatch walkthrough."""


def compute_total(items):
    """Sum the priced items."""
    total = 0
    for item in items:
        total += item["price"] * item.get("count", 1)
    return total


def render_total(total):
    """Format a total for display."""
    return "Total: %.2f" % total
