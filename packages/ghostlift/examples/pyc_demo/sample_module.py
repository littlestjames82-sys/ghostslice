"""Sample module used to generate a .pyc fixture at test time."""


def greet(name, punctuation="!"):
    return "Hello, " + name + punctuation


def add(a, b):
    return a + b


class Pair:
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def swap(self):
        return Pair(self.right, self.left)
