"""Analysis core: one stats pass, one sample pass, both streaming."""
from __future__ import annotations

import hashlib
import os

from . import readers, sensitive
from .infer import ColumnStats
from .readers import DataError, Malformed
from .tokens import ChunkedEstimator

DEFAULT_SAMPLE = 60
MALFORMED_EXAMPLES_CAP = 20

# Structural bounds for a top-level JSON object's sample. The object is
# a single record, so the row bound cannot bound it; these caps do,
# and every cut they make is counted and stated in the pack. The root
# object's own keys are never dropped: they are the schema. Depth
# counts containers with the root object at depth 1.
OBJECT_MAX_DEPTH = 6
OBJECT_MAX_KEYS = 50
OBJECT_MAX_ITEMS = 20
OBJECT_MAX_STRING = 1000
TRUNCATION_DETAILS_CAP = 20
TRUNCATED = "[TRUNCATED]"


def bound_object(obj: dict):
    """Return (bounded_copy, record) with the structural caps applied.

    The record counts each kind of cut and lists the first few by path,
    so the pack can state exactly what the sample left out.
    """
    record = {"keys_dropped": 0, "items_dropped": 0,
              "depth_truncations": 0, "strings_truncated": 0,
              "details": []}

    def note(text):
        if len(record["details"]) < TRUNCATION_DETAILS_CAP:
            record["details"].append(text)

    def bound(value, depth, path, is_root=False):
        if isinstance(value, dict):
            if depth > OBJECT_MAX_DEPTH:
                record["depth_truncations"] += 1
                note("value at %s replaced (max depth %d)"
                     % (path or "<root>", OBJECT_MAX_DEPTH))
                return TRUNCATED
            out = {}
            keys = list(value.keys())
            kept = keys if is_root else keys[:OBJECT_MAX_KEYS]
            if len(keys) > len(kept):
                record["keys_dropped"] += len(keys) - len(kept)
                note("%d key(s) dropped at %s (max %d per level)"
                     % (len(keys) - len(kept), path or "<root>",
                        OBJECT_MAX_KEYS))
            for key in kept:
                sub_path = "%s.%s" % (path, key) if path else str(key)
                out[key] = bound(value[key], depth + 1, sub_path)
            return out
        if isinstance(value, list):
            if depth > OBJECT_MAX_DEPTH:
                record["depth_truncations"] += 1
                note("value at %s replaced (max depth %d)"
                     % (path or "<root>", OBJECT_MAX_DEPTH))
                return TRUNCATED
            kept = value[:OBJECT_MAX_ITEMS]
            if len(value) > len(kept):
                record["items_dropped"] += len(value) - len(kept)
                note("%d item(s) dropped at %s (max %d per array)"
                     % (len(value) - len(kept), path or "<root>",
                        OBJECT_MAX_ITEMS))
            return [bound(v, depth + 1, "%s[%d]" % (path, i))
                    for i, v in enumerate(kept)]
        if isinstance(value, str) and len(value) > OBJECT_MAX_STRING:
            record["strings_truncated"] += 1
            note("string at %s truncated to %d chars"
                 % (path or "<root>", OBJECT_MAX_STRING))
            return value[:OBJECT_MAX_STRING] + TRUNCATED
        return value

    bounded = bound(obj, 1, "", is_root=True)
    record["truncated"] = any(
        record[k] for k in ("keys_dropped", "items_dropped",
                            "depth_truncations", "strings_truncated"))
    record["limits"] = {"max_depth": OBJECT_MAX_DEPTH,
                        "max_keys_per_level": OBJECT_MAX_KEYS,
                        "max_items_per_array": OBJECT_MAX_ITEMS,
                        "max_string_chars": OBJECT_MAX_STRING}
    return bounded, record


def file_sha256(path: str) -> str:
    """Return the sha256 hex digest of a file, read in chunks so the
    file is never held whole in memory."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def full_token_estimate(path: str) -> int:
    """Estimate the token count of the whole file, streamed in chunks.

    The result is an estimate (see tokens.method() for the estimator
    that produced it), not an exact tokenizer count.
    """
    est = ChunkedEstimator()
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for chunk in iter(lambda: fh.read(65536), ""):
            est.feed(chunk)
    est.flush()
    return est.total


def sample_indices(total: int, sample_size: int):
    """Head + tail + evenly spaced middle indices into [0, total).

    ``sample_size`` is a hard bound: the result never holds more
    indices than requested, including a request for 1. Returns
    (indices, strategy) where strategy counts how the indices split
    across head, tail, and spaced middle rows, and flags
    ``all_rows`` when the file is smaller than the sample size.
    """
    if total <= 0 or sample_size <= 0:
        return [], {"head": 0, "tail": 0, "spaced": 0}
    if sample_size >= total:
        return list(range(total)), {
            "head": total, "tail": 0, "spaced": 0, "all_rows": True}
    # The requested size is a hard bound: head gets the ceiling third,
    # tail the floor third, the middle gets the rest. (An earlier split
    # forced head and tail to at least 1 each, so a bound of 1 returned
    # 2 rows; Agent B's bound test caught it.)
    head_n = (sample_size + 2) // 3
    tail_n = sample_size // 3
    mid_n = sample_size - head_n - tail_n
    idx = list(range(head_n))
    tail_start = total - tail_n
    span_start, span_end = head_n, tail_start
    if mid_n > 0 and span_end > span_start:
        for i in range(mid_n):
            pos = span_start + int((i + 0.5) * (span_end - span_start) / mid_n)
            if pos not in idx and pos < span_end:
                idx.append(pos)
    idx.extend(range(tail_start, total))
    idx = sorted(set(idx))
    return idx, {"head": head_n, "tail": tail_n,
                 "spaced": len(idx) - head_n - tail_n}


def analyze(path: str, sample_size: int = DEFAULT_SAMPLE,
            redact: bool = True, fmt: str = None) -> dict:
    """Analyze one data file in two streaming passes.

    The first pass infers the schema and counts every row: parsed,
    malformed (with example line numbers), and blank. Counts are true
    counts, never estimates. The second pass collects the bounded
    sample (head, tail, and evenly spaced rows; a top-level JSON
    object is its own single-record sample, structurally bounded by
    bound_object). When ``redact`` is true, sensitive columns and
    nested values are replaced with [REDACTED] in the sample and the
    schema suppresses their ranges.

    Returns a dict with the detected format, column names, per-column
    schema, counts, the redaction record, and the sample. The sample
    rows ride under the private ``_rows`` key for pack.render_sample
    and are not part of the manifest. Raises DataError for a missing
    file or an unreadable or unsupported format. The source file is
    only read, never modified.
    """
    if not os.path.isfile(path):
        raise DataError("no such file: %s" % path)
    try:
        sample_size = int(sample_size)
    except (TypeError, ValueError):
        raise DataError(
            "sample size must be a positive integer, got %r"
            % (sample_size,))
    if sample_size < 1:
        # Zero or negative sizes used to flow into sample_indices and
        # produce a pack whose manifest carried negative strategy
        # counts (head -1, tail -2) instead of an error.
        raise DataError(
            "sample size must be at least 1, got %d" % sample_size)
    reader = readers.open_reader(path, fmt=fmt)
    columns = reader.columns()
    stats = [ColumnStats(name) for name in columns]

    parsed = 0
    malformed = 0
    blanks = 0
    malformed_examples = []
    for row in reader.rows():
        if isinstance(row, Malformed):
            if row.reason == "blank":
                blanks += 1
            else:
                malformed += 1
                if len(malformed_examples) < MALFORMED_EXAMPLES_CAP:
                    malformed_examples.append(
                        {"line": row.line, "reason": row.reason})
            continue
        parsed += 1
        for st, value in zip(stats, row):
            st.add(value)
    truncated = bool(getattr(reader, "truncated", False))
    truncation_note = getattr(reader, "truncation_note", None)

    redactions = {}
    schema = []
    for st in stats:
        reason = st.redaction() if redact else None
        if reason:
            redactions[st.name] = reason
        schema.append(st.to_dict(redacted_reason=reason))

    idx, strategy = sample_indices(parsed, sample_size)
    wanted = set(idx)
    sample_rows = []
    nested_records = []
    sample_truncation = None

    def note_nested(name, reason):
        entry = {"name": name, "reason": reason}
        if entry not in nested_records:
            nested_records.append(entry)

    def redact_cell(value, name):
        """Redact one sampled cell that is not in a redacted column.

        Containers get the nested name/shape rules. A scalar cell is
        also checked on its own shape: column-level redaction needs a
        stated share of matching values, so a lone email address or
        card number sitting in a mostly innocuous column (one email
        in a hundred free-text notes) used to be written into the
        sample verbatim. A value that matches a sensitive shape is
        never sampled, whatever its column's overall share is. Hits
        are recorded by column name in the pack's redaction record.
        """
        if isinstance(value, (dict, list)):
            new_value, hits = sensitive.redact_nested(value, path=name)
            for hit_path, reason in hits:
                note_nested(hit_path, reason)
            return new_value
        shape = None
        if isinstance(value, str):
            shape = sensitive.shape_of(value)
        elif isinstance(value, int) and not isinstance(value, bool):
            shape = sensitive.shape_of_int(value)
        if shape:
            note_nested(name, "value matches %s shape" % shape)
            return "[REDACTED]"
        return value

    if getattr(reader, "object_mode", False):
        # A top-level object is one record. The sample is the object
        # itself: redacted (whole-key redactions from the stats pass,
        # then the same name/shape rules at every nested depth), then
        # structurally bounded, with every cut counted for the pack.
        row = next(iter(reader.rows()))
        obj = {}
        for i, name in enumerate(columns):
            value = row[i]
            if redact and name in redactions:
                obj[name] = "[REDACTED]"
            elif redact:
                obj[name] = redact_cell(value, name)
            else:
                obj[name] = value
        obj, sample_truncation = bound_object(obj)
        sample_rows = [[obj[name] for name in columns]]
    elif idx:
        ordinal = -1
        for row in reader.rows():
            if isinstance(row, Malformed):
                continue
            ordinal += 1
            if ordinal in wanted:
                cells = []
                for i in range(len(row)):
                    value = row[i]
                    if stats[i].name in redactions:
                        cells.append("[REDACTED]")
                    elif redact:
                        cells.append(redact_cell(value, stats[i].name))
                    else:
                        cells.append(value)
                sample_rows.append(cells)
                if len(sample_rows) == len(idx):
                    break

    counts = {
        "rows_parsed": parsed,
        "rows_malformed": malformed,
        "rows_total": parsed + malformed,
        "blank_lines": blanks,
        "malformed_examples": malformed_examples,
        "truncated": truncated,
    }
    if truncated:
        counts["truncation_note"] = truncation_note
    return {
        "format": reader.format,
        "columns": [sensitive.display_name(c) for c in columns],
        "schema": schema,
        "counts": counts,
        "structure": getattr(reader, "structure", None),
        "redacted_columns": [
            {"name": sensitive.display_name(name),
             "reason": reason}
            for name, reason in redactions.items()],
        "redacted_nested": nested_records,
        "redaction_enabled": redact,
        "sample": {
            "size_requested": sample_size,
            "rows": len(sample_rows),
            "strategy": strategy,
            "row_indices": idx,
            "_rows": sample_rows,
            "_truncation": sample_truncation,
        },
    }
