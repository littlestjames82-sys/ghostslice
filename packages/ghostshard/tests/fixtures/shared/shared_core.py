"""Shared core: the one symbol both report.py and export.py need."""


def normalize_record(record):
    """Return a cleaned copy of a record dict."""
    cleaned = {}
    for key, value in record.items():
        cleaned[str(key).strip().lower()] = str(value).strip()
    cleaned.setdefault("name", "unnamed")
    return cleaned


def normalize_records(records):
    """Normalize a list of records."""
    return [normalize_record(r) for r in records]
