"""Error/exception patterns and timestamp recognition.

The default pattern set is deliberately plain: severity levels,
exception and traceback markers, panic and crash markers. Every
pattern has an id, a severity (3 fatal, 2 error, 1 other match), and
a kind. Custom patterns can be added from a file (one per line:
``id = regex`` or a bare regex) or repeated --pattern flags. A bad
regex fails loudly at load time; nothing is silently skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Pattern:
    id: str
    regex: re.Pattern
    severity: int
    kind: str  # level | exception | trace | panic | custom
    # Builtin patterns are gated behind the needle prefilter in
    # patterns.py: every builtin match requires one of the needle
    # substrings, so a line with no needle cannot match and the full
    # regexes are skipped. Custom patterns always run.
    builtin: bool = False


# Every builtin pattern match contains at least one of these
# substrings (checked case-insensitively). Keep in step with
# DEFAULT_PATTERNS below: a builtin regex that could match without
# any needle present would be silently skipped, which is the one
# failure mode this prefilter must never have.
NEEDLE_RE = re.compile(
    r"FATAL|CRITICAL|CRIT|ERROR|SEVERE|Traceback|Exception|Error|"
    r"Caused by|panic|Segmentation fault|core dumped|OOMKilled|"
    r"Killed process|unhandled|uncaught",
    re.IGNORECASE)

DEFAULT_PATTERNS: list[tuple[str, str, int, str, int]] = [
    # (id, regex, severity, kind, flags)
    ("fatal-level", r"\b(FATAL|CRITICAL|CRIT)\b", 3, "level", re.IGNORECASE),
    ("panic", r"panic:|Segmentation fault|core dumped|OOMKilled|Killed process",
     3, "panic", 0),
    ("error-level", r"\b(ERROR|SEVERE)\b", 2, "level", 0),
    ("traceback-start", r"Traceback \(most recent call last\):", 2, "trace", 0),
    ("exception-name",
     r"\b(?:[a-z][\w]*\.)*[A-Z][\w]*(?:Exception|Error)\b"
     r"|\b\w+(?:Exception|Error):"
     r"|\bCaused by:",
     2, "exception", 0),
    ("unhandled", r"unhandled (?:exception|rejection)|uncaught exception",
     2, "exception", re.IGNORECASE),
]


def default_patterns() -> list[Pattern]:
    return [Pattern(pid, re.compile(rx, flags), sev, kind, builtin=True)
            for pid, rx, sev, kind, flags in DEFAULT_PATTERNS]


def load_pattern_file(path) -> list[Pattern]:
    """Load custom patterns. Format per non-comment line:
    ``id = regex`` or a bare ``regex`` (id auto-assigned). Custom
    patterns are severity 2, kind custom. Raises ValueError naming
    the file and line on any bad regex."""
    from pathlib import Path
    patterns: list[Pattern] = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"{path}: cannot read pattern file: {exc}") from exc
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if " = " in line:
            pid, rx = line.split(" = ", 1)
            pid, rx = pid.strip(), rx.strip()
        else:
            pid, rx = f"custom-{len(patterns) + 1}", line
        if not pid or not rx:
            raise ValueError(f"{path}:{lineno}: empty pattern id or regex")
        try:
            compiled = re.compile(rx)
        except re.error as exc:
            raise ValueError(f"{path}:{lineno}: bad regex for {pid!r}: {exc}") from exc
        patterns.append(Pattern(pid, compiled, 2, "custom"))
    return patterns


def compile_cli_patterns(regexes) -> list[Pattern]:
    """Compile --pattern values into Patterns (ids cli-1, cli-2, ...).

    Custom patterns are severity 2, kind custom, and are not gated
    behind the builtin needle prefilter. Raises ValueError naming
    the offending value on any bad regex.
    """
    patterns: list[Pattern] = []
    for i, rx in enumerate(regexes or [], 1):
        try:
            compiled = re.compile(rx)
        except re.error as exc:
            raise ValueError(f"--pattern {rx!r}: bad regex: {exc}") from exc
        patterns.append(Pattern(f"cli-{i}", compiled, 2, "custom"))
    return patterns


# Timestamps: recognised forms for timeline anchors. The matched
# text is kept verbatim as the anchor; no timezone conversion is
# attempted or claimed.
_TIMESTAMP_RES = [
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"
               r"(?:Z|[+-]\d{2}:?\d{2})?"),
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
               r"\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\b"),
    re.compile(r"\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\]"),
]


_TIMESTAMP_COMBINED = re.compile(
    "|".join(f"(?:{rx.pattern})" for rx in _TIMESTAMP_RES))


def find_timestamp(text: str):
    """Return the first recognised timestamp string in the line, or None.

    Recognised forms are ISO 8601, syslog-style month names, and the
    bracketed form; see _TIMESTAMP_RES. The matched text is returned
    verbatim: no parsing or timezone conversion is attempted.
    """
    m = _TIMESTAMP_COMBINED.search(text)
    return m.group(0) if m else None


_ISO_BUCKET_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2})")
_SYSLOG_BUCKET_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})"
    r"\s+(\d{2})")


def hour_bucket(ts_text: str):
    """Hour-bucket label for a recognised timestamp string, derived
    from the timestamp exactly as written: no timezone conversion
    and no year invention. ISO/bracketed forms give
    ``YYYY-MM-DDTHH:00``; syslog forms (which carry no year in the
    source) give ``Mon DD HH:00 (syslog, no year in source)``.
    Returns None for a string with no recognisable hour."""
    m = _ISO_BUCKET_RE.search(ts_text)
    if m:
        return f"{m.group(1)}T{m.group(2)}:00"
    m = _SYSLOG_BUCKET_RE.search(ts_text)
    if m:
        return (f"{m.group(1)} {int(m.group(2)):02d} {m.group(3)}:00 "
                f"(syslog, no year in source)")
    return None


# Continuation lines absorbed into a stack trace: indented lines,
# Python and Java frame lines, Caused by chains, JVM elision lines.
_FRAME_RES = [
    re.compile(r"^\s+File \"[^\"]+\", line \d+"),
    re.compile(r"^\s+at\s+[\w.$]+\([^)]*\)\s*$"),
    re.compile(r"^\s*Caused by:"),
    re.compile(r"^\s*\.\.\. \d+ more"),
    re.compile(r"^\s+raise\s+\w"),
    re.compile(r"^\s+during handling of the above exception", re.IGNORECASE),
    re.compile(r"^\s*(?:During handling of the above exception|"
               r"The above exception was the direct cause)"),
]


def is_continuation(text: str) -> bool:
    """True if the line reads as a stack-trace continuation.

    Any indented (space or tab) non-blank line qualifies, as do the
    explicit frame shapes in _FRAME_RES (Python and Java frames,
    Caused by chains, JVM elision lines). Used to absorb a trace
    into the window that opened it.
    """
    if not text.strip():
        return False
    if text[0] in (" ", "\t"):
        return True
    return any(rx.match(text) for rx in _FRAME_RES)
