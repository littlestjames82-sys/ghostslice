"""Utilities for the fixture project."""


def parse_config(path: str) -> dict:
    """Parse a tiny key=value config file into a dict."""
    out = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def format_row(name: str, value: str) -> str:
    return f"{name}: {value}"
