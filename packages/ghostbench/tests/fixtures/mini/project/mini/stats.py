"""Statistics built on calc."""

from .calc import add


def mean(values):
    total = 0
    for value in values:
        total = add(total, value)
    return total / len(values)
