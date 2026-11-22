"""Hot path: the file the planted-waste sessions keep re-reading."""

_cache: dict = {}


def cached_lookup(key: str) -> str:
    if key not in _cache:
        _cache[key] = _load(key)
    return _cache[key]


def _load(key: str) -> str:
    return f"value-for-{key}"
