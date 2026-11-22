"""Demo application module."""


def compute_total(items):
    """Sum the priced items."""
    total = 0
    for item in items:
        total += item_price(item) * item_count(item)
    return total


def item_price(item):
    """Return the price field of one item."""
    return item["price"]


def item_count(item):
    """Return the count field of one item."""
    return item.get("count", 1)


def render_total(total):
    """Format a total for display."""
    return "Total: %.2f" % total
