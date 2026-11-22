# Optimized agent context bundle (GhostSlice)

Estimated tokens: 211 (was 287, saved 76). Token counts are estimates, see manifest.json for the method.


---

# File: src/app.py (mode: full)

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


---

# File: .ghostslice.json (mode: full)

{
  "modes": {
    "src/app.py": "full",
    "src/util.py": "signatures",
    "vendor/**": "exclude"
  }
}


---

# File: src/util.py (mode: signatures)

"""Utility helpers."""

def clamp(value, low, high): ...


---

# File: docs/guide.md (mode: full)

# Guide

## Install

Run the installer script.

## Usage

Call greet from the app module.


---

# File: README.md (mode: full)

# Demo Project

A tiny fixture project for conversion tests.
