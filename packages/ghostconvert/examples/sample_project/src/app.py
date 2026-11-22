"""Demo application module."""


def greet(name, punctuation="!"):
    """Build a greeting for name."""
    message = f"Hello, {name}{punctuation}"
    return message


def add(a, b):
    return a + b


class Pair:
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def swap(self):
        return Pair(self.right, self.left)
