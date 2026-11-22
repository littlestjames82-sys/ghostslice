"""Mini app used as a GhostReview fixture project."""

from pricing import compute_total


def checkout(items):
    """Return the checkout total for a list of prices."""
    return compute_total(items)
