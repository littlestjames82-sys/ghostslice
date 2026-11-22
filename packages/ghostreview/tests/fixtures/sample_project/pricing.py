"""Pricing rules for the GhostReview fixture project."""

TAX_RATE = 0.08


def compute_total(items):
    """Sum item prices and apply the tax rate."""
    subtotal = sum(items)
    return subtotal * (1 + TAX_RATE)
