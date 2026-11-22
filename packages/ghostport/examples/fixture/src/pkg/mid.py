"""Fixture mid module: depends on base, has hits."""
from collections import Mapping
from datetime import datetime

from pkg import base


def stamp(mapping):
    assert isinstance(mapping, Mapping)
    return datetime.utcnow(), base.load("x")
