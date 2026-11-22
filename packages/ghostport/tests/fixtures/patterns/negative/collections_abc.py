"""Look-alike negative: already uses collections.abc, the modern location."""
from collections.abc import Mapping, MutableSequence


class Bag(MutableSequence):
    pass


def is_mapping(obj):
    mapping = Mapping
    return isinstance(obj, mapping)
