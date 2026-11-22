"""Streaming readers for CSV, TSV, JSON arrays, JSONL, and top-level
JSON objects.

Every reader is re-openable (two passes: stats, then sample) and never
holds the file whole. Rows are yielded aligned to a fixed column list.
Malformed rows are yielded as Malformed records with line numbers,
counted by the caller, never silently skipped.

The one exception to "never holds the file whole" is a top-level JSON
object: there is no way to know its keys without parsing it, so
JsonObjectReader parses it whole under an explicit size guard
(MAX_OBJECT_BYTES). Config-shaped JSON is small by nature; the guard
keeps the exception bounded and stated rather than silent.
"""
from __future__ import annotations

import csv
import io
import json
import os

CHUNK = 65536

# Top-level JSON objects are parsed whole (see module docstring). This
# is the stated guard: 16 MiB is far above any real config file and
# bounds the parsed structure a single object can make us hold.
MAX_OBJECT_BYTES = 16 * 1024 * 1024


class DataError(Exception):
    """A data file cannot be read as a dataset: missing, empty,
    in an unsupported format, a top-level JSON scalar, or a JSON
    object over the MAX_OBJECT_BYTES guard. The CLI reports the
    message on stderr and exits 2."""


class Malformed:
    """One row that could not be parsed, yielded in place of a row.

    Carries the 1-based ``line`` number and a plain-language
    ``reason`` ("blank" for blank lines). Malformed rows are counted
    and reported by the caller, never silently skipped.
    """

    def __init__(self, line, reason):
        self.line = line
        self.reason = reason

    def __repr__(self):
        return "Malformed(line=%r, reason=%r)" % (self.line, self.reason)


def detect_format(path: str) -> str:
    """Detect a file's format name: csv, tsv, json, or jsonl.

    The extension decides when it is recognised (.csv, .tsv/.tab,
    .json, .jsonl/.ndjson). Otherwise the first bytes are sniffed: a
    leading [ or { means JSON, and anything else is delimited text
    whose delimiter is guessed from the first line.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return "csv"
    if ext in (".tsv", ".tab"):
        return "tsv"
    if ext in (".jsonl", ".ndjson"):
        return "jsonl"
    if ext == ".json":
        return "json"
    # Sniff: first non-whitespace character decides JSON shape,
    # otherwise guess the delimiter from the first line.
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        head = fh.read(4096)
    stripped = head.lstrip()
    if stripped.startswith("["):
        return "json"
    if stripped.startswith("{"):
        return "jsonl"
    first_line = head.splitlines()[0] if head.splitlines() else ""
    return "tsv" if first_line.count("\t") > first_line.count(",") else "csv"


class DelimitedReader:
    """Streaming reader for CSV and TSV files.

    The first row is the header; duplicate or empty header names are
    made unique by columns(). Rows with the wrong field count are
    yielded as Malformed with their line number.
    """

    def __init__(self, path, fmt, token_sink=None):
        self.path = path
        self.format = fmt
        self.delimiter = "\t" if fmt == "tsv" else ","
        self.token_sink = token_sink
        self._columns = None

    def _tap(self, fh):
        sink = self.token_sink
        for line in fh:
            if sink is not None:
                sink.feed(line)
            yield line

    def columns(self):
        if self._columns is not None:
            return self._columns
        with open(self.path, "r", encoding="utf-8-sig", errors="replace",
                  newline="") as fh:
            reader = csv.reader(fh, delimiter=self.delimiter)
            try:
                for row in reader:
                    if row:
                        self._columns = _dedupe_names(
                            [c.strip() or "col_%d" % (i + 1)
                             for i, c in enumerate(row)])
                        return self._columns
            except csv.Error as exc:
                raise DataError(
                    "could not parse delimited file: %s" % exc) from exc
        raise DataError("empty file: no header row")

    def rows(self):
        """Yield (values list) or Malformed, one per data row."""
        cols = self.columns()
        with open(self.path, "r", encoding="utf-8-sig", errors="replace",
                  newline="") as fh:
            reader = csv.reader(self._tap(fh), delimiter=self.delimiter)
            header_seen = False
            try:
                for row in reader:
                    if not header_seen:
                        # The header is the first NON-EMPTY row,
                        # exactly as columns() finds it. Skipping
                        # the first physical row unconditionally
                        # used to consume a leading blank line as the
                        # header and then count the real header as a
                        # data row, corrupting the true row counts.
                        if not row:
                            continue
                        header_seen = True
                        continue
                    if not row:
                        yield Malformed(reader.line_num, "blank")
                        continue
                    if len(row) != len(cols):
                        yield Malformed(
                            reader.line_num,
                            "expected %d fields, found %d"
                            % (len(cols), len(row)))
                        continue
                    yield row
            except csv.Error as exc:
                # e.g. a field over the csv module's size limit:
                # a clean, stated error, not a traceback crash.
                raise DataError(
                    "could not parse delimited file: %s" % exc) from exc


class JsonlReader:
    """Streaming reader for JSONL: one JSON value per line.

    Object lines contribute their keys to the column list, in first
    seen order. A file whose lines are all bare values instead gets
    a single "value" column; mixing the two makes the non-object
    lines Malformed.
    """

    format = "jsonl"

    def __init__(self, path, token_sink=None):
        self.path = path
        self.token_sink = token_sink
        self._columns = None
        self.value_mode = False

    def _scan(self, collect_columns):
        fields = []
        seen = set()
        with open(self.path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                if self.token_sink is not None:
                    self.token_sink.feed(line)
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    for key in item:
                        if key not in seen:
                            seen.add(key)
                            fields.append(key)
                else:
                    self.value_mode = True
        return fields

    def columns(self):
        if self._columns is None:
            fields = self._scan(collect_columns=True)
            if self.value_mode and not fields:
                self._columns = ["value"]
            elif self.value_mode:
                self._columns = fields  # mixed: non-dicts are malformed
            else:
                self._columns = fields
            if not self._columns:
                raise DataError("no records found")
        return self._columns

    def rows(self):
        cols = self.columns()
        with open(self.path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for line_no, line in enumerate(fh, 1):
                if self.token_sink is not None:
                    self.token_sink.feed(line)
                if not line.strip():
                    yield Malformed(line_no, "blank")
                    continue
                try:
                    item = json.loads(line)
                except Exception as exc:
                    yield Malformed(line_no, "invalid json: %s" % exc)
                    continue
                if isinstance(item, dict):
                    yield [item.get(c) for c in cols]
                elif self.value_mode and len(cols) == 1 and cols[0] == "value":
                    yield [item]
                else:
                    yield Malformed(line_no, "record is not a json object")


class JsonArrayReader:
    """Incremental reader for a JSON file whose top level is an array.

    Elements are decoded one at a time from a chunked buffer, so the
    file is never held whole. An element that cannot be parsed ends
    the parse: the reader flags itself truncated with a note, and
    rows() yields one final Malformed rather than guessing at the
    rest of the file.
    """

    format = "json"

    def __init__(self, path, token_sink=None):
        self.path = path
        self.token_sink = token_sink
        self._columns = None
        self.value_mode = False
        self.truncated = False
        self.truncation_note = None

    def _items(self):
        """Yield parsed array elements; set self.truncated on a bad one.

        The separator structure is enforced: elements must be divided
        by single commas and the array must close. An earlier version
        skipped commas and whitespace indiscriminately, so files such
        as [1 2], [1,,2], and [1,2,] parsed as clean two-row datasets
        with zero malformed rows, and anything after the closing
        bracket was ignored without a word.
        """
        self.truncated = False
        self.truncation_note = None
        decoder = json.JSONDecoder()
        with open(self.path, "r", encoding="utf-8-sig", errors="replace") as fh:
            buf = ""
            pos = 0
            eof = False

            def fill():
                nonlocal buf, pos, eof
                if eof:
                    return False
                chunk = fh.read(CHUNK)
                if not chunk:
                    eof = True
                    return False
                if self.token_sink is not None:
                    self.token_sink.feed(chunk)
                if pos > CHUNK:
                    buf = buf[pos:]
                    pos = 0
                buf += chunk
                return True

            def fail(note):
                self.truncated = True
                self.truncation_note = note

            fill()
            while pos < len(buf) and buf[pos] in " \t\r\n":
                pos += 1
            if pos >= len(buf) or buf[pos] != "[":
                raise DataError("top level is not a json array")
            pos += 1
            index = 0
            # state "value": an element (or the closing bracket) is
            # expected. state "comma": a comma or the closing bracket
            # is expected. after_comma distinguishes "[1,]" (a trailing
            # comma, malformed) from "[]" and "[1]" (clean closes).
            state = "value"
            after_comma = False
            while True:
                while True:
                    while pos < len(buf) and buf[pos] in " \t\r\n":
                        pos += 1
                    if pos < len(buf):
                        break
                    if not fill():
                        break
                if pos >= len(buf):
                    fail("array ended without closing bracket after "
                         "%d elements" % index)
                    return
                ch = buf[pos]
                if ch == "]":
                    if after_comma:
                        fail("element %d could not be parsed (trailing "
                             "comma before ']'); rest of file uncounted"
                             % (index + 1))
                        return
                    pos += 1
                    # Anything but whitespace after the closing
                    # bracket is uncounted data and is stated, not
                    # silently dropped.
                    trailing = False
                    while True:
                        while pos < len(buf) and buf[pos] in " \t\r\n":
                            pos += 1
                        if pos < len(buf):
                            trailing = True
                            break
                        if not fill():
                            break
                    if trailing:
                        fail("data found after the closing bracket; "
                             "rest of file uncounted")
                    return
                if ch == ",":
                    if state != "comma":
                        fail("element %d could not be parsed "
                             "(unexpected ','); rest of file uncounted"
                             % (index + 1))
                        return
                    pos += 1
                    state = "value"
                    after_comma = True
                    continue
                if state == "comma":
                    fail("element %d could not be parsed (missing ',' "
                         "between elements); rest of file uncounted"
                         % (index + 1))
                    return
                try:
                    item, end = decoder.raw_decode(buf, pos)
                except Exception as exc:
                    if fill():
                        continue
                    fail("element %d could not be parsed (%s); "
                         "rest of file uncounted" % (index + 1, exc))
                    return
                if (isinstance(item, (int, float))
                        and not isinstance(item, bool)
                        and end == len(buf) and not eof):
                    # A JSON number has valid proper prefixes: "7"
                    # decodes cleanly even when the real token is a
                    # 100-digit number continuing into the next chunk.
                    # Refill and re-decode from the same start rather
                    # than splitting one number into two elements.
                    if fill():
                        continue
                pos = end
                index += 1
                state = "comma"
                after_comma = False
                yield item

    def columns(self):
        if self._columns is None:
            fields = []
            seen = set()
            for item in self._items():
                if isinstance(item, dict):
                    for key in item:
                        if key not in seen:
                            seen.add(key)
                            fields.append(key)
                else:
                    self.value_mode = True
            if self.value_mode and not fields:
                self._columns = ["value"]
            else:
                self._columns = fields
            if not self._columns:
                raise DataError("no records found in json array")
        return self._columns

    def rows(self):
        cols = self.columns()
        idx = 0
        for item in self._items():
            idx += 1
            if isinstance(item, dict):
                yield [item.get(c) for c in cols]
            elif self.value_mode and cols == ["value"]:
                yield [item]
            else:
                yield Malformed(idx, "element is not a json object")
        if self.truncated:
            yield Malformed(idx + 1, self.truncation_note or "truncated array")


def _depth(value) -> int:
    """Container depth: a scalar is 0, an empty container is 1, and a
    container is 1 plus the deepest child depth.

    Iterative: the recursive version raised RecursionError on deeply
    nested objects the JSON parser itself accepts (around 800 levels
    once caller frames are counted), crashing schema analysis of a
    valid file instead of describing it.
    """
    results = []
    stack = [(value, False)]
    while stack:
        node, expanded = stack.pop()
        if not isinstance(node, (dict, list)):
            results.append(0)
            continue
        children = (list(node.values()) if isinstance(node, dict)
                    else node)
        if not expanded:
            stack.append((node, True))
            for child in children:
                stack.append((child, False))
            continue
        if not children:
            results.append(1)
        else:
            child_depths = results[-len(children):]
            del results[-len(children):]
            results.append(1 + max(child_depths))
    return results[0]


def _count_keys(value) -> int:
    total = 0
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            total += len(node)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return total


class JsonObjectReader:
    """A JSON file whose top level is an object (config-shaped JSON).

    The object is a single record: its keys are the column list and its
    one row is the values. Nested values stay nested (typed object or
    array by the inference pass, never flattened), exactly as nested
    values inside array records are treated.

    Unlike the streaming readers this parses the file whole, under the
    MAX_OBJECT_BYTES guard, because an object's key set cannot be known
    incrementally. The parse is cached, so the stats and sample passes
    share it.
    """

    format = "json-object"
    top_level = "object"
    object_mode = True

    def __init__(self, path, token_sink=None):
        self.path = path
        self.token_sink = token_sink
        self.truncated = False
        self.truncation_note = None
        self._data = None
        self._columns = None
        self.structure = None

    def _load(self):
        if self._data is not None:
            return self._data
        size = os.path.getsize(self.path)
        if size > MAX_OBJECT_BYTES:
            raise DataError(
                "json object file is %d bytes; top-level objects are "
                "parsed whole under a %d byte (16 MiB) guard, so this "
                "file is refused. Array-shaped JSON streams and has no "
                "such limit" % (size, MAX_OBJECT_BYTES))
        parts = []
        with open(self.path, "r", encoding="utf-8-sig", errors="replace") as fh:
            while True:
                chunk = fh.read(CHUNK)
                if not chunk:
                    break
                if self.token_sink is not None:
                    self.token_sink.feed(chunk)
                parts.append(chunk)
        text = "".join(parts)
        if not text.strip():
            raise DataError("empty file: no json value found")
        try:
            data = json.loads(text)
        except Exception as exc:
            raise DataError("invalid json: %s" % exc)
        if not isinstance(data, dict):
            raise DataError("top level is not a json object")
        self._data = data
        self._columns = list(data.keys())
        self.structure = {
            "top_level_keys": len(self._columns),
            "total_keys": _count_keys(data),
            "max_depth": _depth(data),
        }
        return data

    def columns(self):
        self._load()
        if not self._columns:
            raise DataError("json object has no keys: nothing to describe")
        return self._columns

    def rows(self):
        cols = self.columns()
        data = self._load()
        yield [data.get(c) for c in cols]


def peek_json_shape(path: str) -> str:
    """Return the first non-whitespace character of a JSON file, or
    an empty string for an empty or whitespace-only file."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        while True:
            chunk = fh.read(4096)
            if not chunk:
                return ""
            for ch in chunk:
                if ch not in " \t\r\n":
                    return ch


def open_reader(path, fmt=None, token_sink=None):
    """Open the reader for a file, detecting the format when ``fmt``
    is None.

    ``fmt`` may be csv, tsv, jsonl, json-object, or json. Plain json
    dispatches on the top-level shape: an array streams through
    JsonArrayReader, an object goes to JsonObjectReader under its
    size guard, and a bare scalar raises DataError. An unknown format
    name also raises DataError.
    """
    fmt = fmt or detect_format(path)
    if fmt in ("csv", "tsv"):
        return DelimitedReader(path, fmt, token_sink=token_sink)
    if fmt == "jsonl":
        return JsonlReader(path, token_sink=token_sink)
    if fmt == "json-object":
        return JsonObjectReader(path, token_sink=token_sink)
    if fmt == "json":
        # "json" names the family; the top-level shape picks the
        # reader. Arrays stream; objects parse whole under a guard;
        # a bare scalar is not a dataset and is refused by name.
        shape = peek_json_shape(path)
        if shape == "[":
            return JsonArrayReader(path, token_sink=token_sink)
        if shape == "{":
            return JsonObjectReader(path, token_sink=token_sink)
        if shape == "":
            raise DataError("empty file: no json value found")
        raise DataError(
            "top level is a json scalar, not an array or object: a "
            "lone number, string, boolean, or null has no fields to "
            "describe and no rows to sample")
    raise DataError("unsupported format: %s" % fmt)


def _dedupe_names(names):
    """Make header names unique: the second "id" becomes "id#2", the
    third "id#3", and so on, keeping first occurrences untouched."""
    # Generated suffixes must not collide with a name that is already
    # in the header: ["a", "a#2", "a"] used to produce two columns
    # both named "a#2", leaving the schema (and every dict built by
    # zipping names to values) ambiguous.
    seen = {}
    used = set()
    originals = set(names)
    out = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        if seen[name] == 1 and name not in used:
            out.append(name)
            used.add(name)
            continue
        n = max(seen[name], 2)
        candidate = "%s#%d" % (name, n)
        while candidate in used or candidate in originals:
            n += 1
            candidate = "%s#%d" % (name, n)
        out.append(candidate)
        used.add(candidate)
    return out
