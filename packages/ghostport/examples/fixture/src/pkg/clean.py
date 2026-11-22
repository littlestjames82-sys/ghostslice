"""Negative fixture: modern code that must produce zero hits."""
from collections.abc import Mapping
from datetime import datetime, timezone


def stamp(mapping):
    assert isinstance(mapping, Mapping)
    return datetime.now(timezone.utc)
