"""Positive: collections ABC aliases moved to collections.abc (removed in Python 3.10)."""
import collections
from collections import Mapping, MutableSequence


def is_mapping(obj):
    return isinstance(obj, Mapping)


Alias = collections.MutableSequence
