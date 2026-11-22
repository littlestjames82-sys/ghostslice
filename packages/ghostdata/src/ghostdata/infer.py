"""Schema inference over streamed values.

Types are inferred, never declared, and labelled that way in output.
Distinct counting is capped: past the cap the count is a lower bound
and the column is flagged distinct_capped.

Ranges are tracked per inferred kind with O(1) extra state: min and
max for numeric columns, min and max length for string columns, and
the earliest and latest value for columns that infer as dates. A
date range compares parsed calendar values (timezone offsets are
normalised to UTC), never the raw text, so the reported earliest and
latest are chronological, not lexicographic.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from . import sensitive

DISTINCT_CAP = 10000
NULL_TOKENS = {"", "null", "none", "na", "n/a", "nil", "~"}
_INT = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_DATE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")
_OFFSET_NO_COLON = re.compile(r"([+-]\d{2})(\d{2})$")


def date_sort_key(value):
    """Return a comparable naive-UTC datetime for a date-shaped string.

    Returns None when the value matches the date shape but is not a
    real calendar date or time (for example 2024-13-45, which the
    shape regex accepts). Timezone-aware values are converted to UTC
    and made naive so they can be compared with offset-free values,
    which are taken at face value. Date-only values sort at midnight
    at the start of that day. The original string is what gets
    reported; this key only decides ordering.
    """
    text = value.strip()
    if len(text) > 10 and text[10] == " ":
        text = text[:10] + "T" + text[11:]
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    else:
        text = _OFFSET_NO_COLON.sub(r"\1:\2", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def is_null(value) -> bool:
    """True for None and for strings that spell a null (empty, "null",
    "none", "na", "n/a", "nil", "~", case-insensitive)."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in NULL_TOKENS:
        return True
    return False


def classify(value):
    """Return (type_name, numeric_value_or_None) for a non-null value."""
    if isinstance(value, bool):
        return "boolean", None
    if isinstance(value, int):
        return "integer", value
    if isinstance(value, float):
        return "float", value
    if isinstance(value, dict):
        return "object", None
    if isinstance(value, (list, tuple)):
        return "array", None
    if isinstance(value, str):
        s = value.strip()
        if s.lower() in ("true", "false"):
            return "boolean", None
        if _INT.match(s):
            digits = s.lstrip("+-")
            if len(digits) > 1 and digits.startswith("0"):
                # A leading zero makes a digit string a code, not a
                # quantity (ZIP codes, padded ids): int() would drop
                # the zeros and invent a numeric range the data never
                # had. A lone "0" still classifies as integer.
                return "string", None
            try:
                return "integer", int(s)
            except ValueError:
                pass
        if _FLOAT.match(s):
            try:
                return "float", float(s)
            except ValueError:
                pass
        if _DATE.match(s):
            return "date", None
        return "string", None
    return "string", None


class ColumnStats:
    """Running statistics for one column, fed value by value.

    Holds counters only: null and per-type counts, a capped distinct
    set, numeric and string-length ranges, and sensitive-shape hit
    counters. It never stores the values themselves beyond the capped
    distinct set, so memory stays bounded on large files.
    """

    def __init__(self, name: str):
        self.name = name
        self.non_null = 0
        self.nulls = 0
        self.types = {}
        self.distinct = set()
        self.distinct_capped = False
        self.num_min = None
        self.num_max = None
        self.date_min = None
        self.date_max = None
        self.date_min_key = None
        self.date_max_key = None
        self.date_unparseable = False
        self.len_min = None
        self.len_max = None
        self.strings_checked = 0
        self.shape_checked = 0
        self.shape_hits = {}

    def add(self, value) -> None:
        """Fold one value into the column's counters."""
        if is_null(value):
            self.nulls += 1
            return
        self.non_null += 1
        kind, numeric = classify(value)
        self.types[kind] = self.types.get(kind, 0) + 1
        key = _distinct_key(value)
        if key is not None:
            if not self.distinct_capped:
                if len(self.distinct) < DISTINCT_CAP:
                    self.distinct.add(key)
                else:
                    self.distinct_capped = True
        # The shape check runs BEFORE the numeric range update. A
        # value that matches a sensitive shape must never become the
        # printed min or max: below the column redaction threshold a
        # single card number (or a phone number written as digits)
        # in a large numeric column used to be stored verbatim as
        # the column max in the manifest. Non-finite floats (NaN,
        # +/-inf, reachable through JSON's NaN/Infinity literals and
        # through float strings such as "1e999") are likewise kept
        # out of the range: NaN poisons every comparison it touches,
        # and a non-finite bound makes the manifest invalid strict
        # JSON (a bare NaN/Infinity token).
        shape = None
        if isinstance(value, str):
            self.strings_checked += 1
            self.shape_checked += 1
            ln = len(value)
            self.len_min = ln if self.len_min is None else min(self.len_min, ln)
            self.len_max = ln if self.len_max is None else max(self.len_max, ln)
            shape = sensitive.shape_of(value)
        elif isinstance(value, int) and not isinstance(value, bool):
            # Native JSON numbers get the one shape check that can
            # apply to them (card, via sensitive.shape_of_int), so a
            # card number stored as a JSON number is not exempt from
            # redaction just because it was never a string.
            self.shape_checked += 1
            shape = sensitive.shape_of_int(value)
        if shape:
            self.shape_hits[shape] = self.shape_hits.get(shape, 0) + 1
        if (numeric is not None and shape is None
                and (not isinstance(numeric, float)
                     or math.isfinite(numeric))):
            self.num_min = numeric if self.num_min is None else min(self.num_min, numeric)
            self.num_max = numeric if self.num_max is None else max(self.num_max, numeric)
        if kind == "date" and isinstance(value, str):
            # Deepen: track the earliest/latest date values. The
            # comparison key is a parsed calendar datetime (see
            # date_sort_key), not the raw text; the raw spelling is
            # what is kept for reporting. A renamed local (date_key)
            # is used so this cannot clobber the distinct-count key
            # computed above.
            date_key = date_sort_key(value)
            if date_key is None:
                # Date-shaped but not a real calendar value: any
                # range built from the remaining values would be a
                # partial range presented as whole, so the column
                # reports no date range at all (see to_dict).
                self.date_unparseable = True
            else:
                raw = value.strip()
                if self.date_min_key is None or date_key < self.date_min_key:
                    self.date_min_key = date_key
                    self.date_min = raw
                if self.date_max_key is None or date_key > self.date_max_key:
                    self.date_max_key = date_key
                    self.date_max = raw

    @property
    def total(self) -> int:
        return self.non_null + self.nulls

    def inferred_type(self) -> str:
        """The column's single inferred type: the only type seen, float
        for an integer/float mix, mixed for any other mix, and null
        when no non-null value was seen."""
        if not self.types:
            return "null"
        kinds = set(self.types)
        if kinds == {"integer", "float"}:
            return "float"
        if len(kinds) == 1:
            return next(iter(kinds))
        return "mixed"

    def redaction(self):
        """Return the redaction reason for this column, or None."""
        reason = sensitive.name_reason(self.name)
        if reason:
            return reason
        return sensitive.shape_reason(self.shape_hits, self.shape_checked)

    def to_dict(self, redacted_reason=None) -> dict:
        """The schema entry for this column, as stored in the manifest.

        When ``redacted_reason`` is given the column is marked
        redacted and its min and max are reported as None, so no
        sensitive value leaks through a range bound.
        """
        total = self.total
        out = {
            "name": sensitive.display_name(self.name),
            "type": self.inferred_type(),
            "types_seen": dict(sorted(self.types.items())),
            "null_count": self.nulls,
            "null_rate": round(self.nulls / total, 6) if total else 0.0,
            "distinct_count": len(self.distinct),
            "distinct_capped": self.distinct_capped,
        }
        if redacted_reason:
            out["redacted"] = True
            out["redaction_reason"] = redacted_reason
            out["min"] = None
            out["max"] = None
        else:
            out["redacted"] = False
            if self.num_min is not None:
                out["min"] = self.num_min
                out["max"] = self.num_max
            if (self.inferred_type() == "date"
                    and self.date_min is not None
                    and not self.date_unparseable):
                # Earliest and latest values seen, in the source's
                # own spelling. Only a pure date column reports a
                # date range: a mixed column keeps no range claim,
                # and a column with an unparseable date-shaped value
                # suppresses it rather than reporting a partial one.
                out["min"] = self.date_min
                out["max"] = self.date_max
            if self.len_min is not None:
                out["min_length"] = self.len_min
                out["max_length"] = self.len_max
        return out


def _distinct_key(value):
    """Hashable distinct-count key for a value, or None for nested
    values, which are not distinct-counted."""
    try:
        if isinstance(value, (dict, list, tuple)):
            return None  # nested values are not distinct-counted
        if isinstance(value, float) and math.isnan(value):
            # NaN != NaN, so each NaN would mint a fresh set entry
            # and inflate the distinct count (toward a false cap).
            # All NaNs are the same observed value for counting.
            return ("float", "nan")
        return (type(value).__name__, value)
    except Exception:
        return None
