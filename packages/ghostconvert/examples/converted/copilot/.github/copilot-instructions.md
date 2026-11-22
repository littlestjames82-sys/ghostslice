# Copilot instructions (GhostSlice context, converted)
Converted by GhostConvert 0.1.0 from a GhostSlice bundle (target: copilot). Do not edit the source bundle; regenerate from it instead.
Project: sample_project
Estimated tokens: 211 sliced (was 287, saved 76). Token counts are estimates from the source manifest (method: estimates (BPE-like split v2, per-language calibrated, not exact tokenizer counts)).
Each file keeps its GhostSlice slice mode in its header. A file marked signatures, symbols, interfaces, or strip-tests is NOT the full source. See LOSSES.md in this output for what this format could not carry from the manifest.

## File: src/app.py (mode: full)

```python
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
```


## File: .ghostslice.json (mode: full)

```json
{
  "modes": {
    "src/app.py": "full",
    "src/util.py": "signatures",
    "vendor/**": "exclude"
  }
}
```


## File: src/util.py (mode: signatures)

```python
"""Utility helpers."""

def clamp(value, low, high): ...
```


## File: docs/guide.md (mode: full)

```markdown
# Guide

## Install

Run the installer script.

## Usage

Call greet from the app module.
```


## File: README.md (mode: full)

```markdown
# Demo Project

A tiny fixture project for conversion tests.
```

