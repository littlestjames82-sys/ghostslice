"""Secret-shaped literal detection and redaction.

Findings are recorded as path + line + type only. The literal value is
never written to any manifest, report, or log by this module.

Shape parity with GhostSlice's guard (ghostslice/secrets_scan.py) was
audited in the Oct 14, 2026 seam-fix round; see SEAM_FIX_REPORT.md for
the per-shape record. Known-shape patterns below mirror Slice's
canonical regexes for the shapes both tools detect. Exposure-only
shapes (bearer_token, long_hex_assignment) are extra coverage, and the
heuristic assignment layer (generic_assignment) deliberately stays
stricter than Slice's sensitive-assignment rule: this module REWRITES
exported evidence text, so it requires a quoted value of 12+ chars
under a sensitive name, where Slice's reporting scan can afford to
flag looser candidates without destroying anything.
"""
import re

# (type_id, regex with one capture group for the literal value)
_PATTERNS = [
    # Canonical Slice form: AKIA (long-lived) and ASIA (temporary
    # session) prefixes. Was AKIA-only before the seam fix, which let
    # ASIA temporary keys ship unredacted.
    ("aws_access_key", re.compile(r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b")),
    # Canonical Slice form: the token body class includes "_"; without
    # it a token containing an underscore matched only partially (or not
    # at all), leaving the tail unredacted.
    ("github_token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{20,})\b")),
    # Canonical Slice form: optional ant-/proj- prefix, 16+ body chars
    # (was a flat 20+ with no prefix handling).
    ("openai_style_key", re.compile(
        r"\b(sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,})\b")),
    # Canonical Slice shape, missing from Exposure before the seam fix.
    ("slack_token", re.compile(r"\b(xox[baprs]-[A-Za-z0-9\-]{10,})\b")),
    # Canonical Slice shape, missing before the seam fix. Group 1 is
    # the password only, so redaction keeps the URL's shape visible.
    ("password_in_url", re.compile(r"://[^/\s:@'\"]+:([^/\s:@'\"]{3,})@")),
    # Exposure-only extra shape (Slice has no bearer pattern).
    ("bearer_token", re.compile(r"(?i)bearer\s+([A-Za-z0-9_\-\.]{20,})")),
    ("generic_assignment", re.compile(
        r"(?i)(?:api[_-]?key|secret|token|password|passwd|private[_-]?key)"
        r"\s*[=:]\s*[\"']([^\"'\s]{12,})[\"']")),
    ("private_key_header", re.compile(r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)")),
    ("long_hex_assignment", re.compile(
        r"(?i)(?:key|secret|token)\s*[=:]\s*[\"']([0-9a-f]{32,})[\"']")),
]

# Canonical Slice aws-secret-key rule: a bare 40-char base64-ish value
# is only treated as a secret when its line also names something
# AWS-secret-like. Handled as a special case in find_literals, exactly
# as Slice handles it outside its pattern list.
_AWS_SECRET_CONTEXT = re.compile(r"aws.{0,20}secret|secret.{0,20}aws",
                                 re.IGNORECASE)
_BARE_40 = re.compile(r"\b[A-Za-z0-9/+=]{40}\b")

_PEM_END_RE = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
_PEM_BODY_RE = re.compile(r"[A-Za-z0-9+/=]{16,}")

REDACTED = "***REDACTED***"


def _is_pem_body_line(line):
    """True for lines that can appear inside a PEM block between the
    BEGIN and END lines: blank lines, bare base64, and old-style PEM
    header lines (``Name: value``). Ordinary code lines are not."""
    s = line.strip()
    return (not s or _PEM_BODY_RE.fullmatch(s) is not None
            or (":" in s and not s.startswith("-----")))


def _pem_block_last_line(lines, start):
    """0-based index of the last line of the PEM block whose BEGIN
    header is on lines[start]: through the END line when present, else
    over the following bare-base64 body lines (a file can be cut before
    its END line; the body is the secret material either way). Mirrors
    GhostSlice's _pem_block, with one hardening difference: an END line
    only closes the block when every line in between is PEM-shaped. A
    truncated block followed by ordinary code and an unrelated END line
    later in the file must not swallow the code in between."""
    for j in range(start + 1, len(lines)):
        if _PEM_END_RE.search(lines[j]):
            return j
        if not _is_pem_body_line(lines[j]):
            break
    last = start
    for j in range(start + 1, len(lines)):
        if _PEM_BODY_RE.fullmatch(lines[j].strip()):
            last = j
        else:
            break
    return last


def find_literals(text):
    """Find secret-shaped literal spans in ``text``.

    Returns a list of dicts with ``line`` (1-based), ``type`` (the
    shape id), ``start``, and ``end`` (character offsets into
    ``text``), sorted by ``start`` and de-duplicated by span. A
    private-key header finding spans its whole key block, and findings
    inside an already-recorded block are not repeated. The literal
    values themselves are only ever addressed by span here; callers
    record path, line, and type, never the value.
    """
    found = []
    seen = set()
    # Split keeping the terminators so line start offsets are exact for
    # CRLF (and CR / LF) files. Assuming a 1-char terminator drifts the
    # offset by one per preceding CRLF line, which shifted redaction
    # spans off the literal and left its tail in the exported copy.
    lines = []
    line_starts = []
    offset = 0
    for segment in text.splitlines(keepends=True):
        line_starts.append(offset)
        offset += len(segment)
        if segment.endswith("\r\n"):
            lines.append(segment[:-2])
        elif segment and segment[-1] in "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029":
            lines.append(segment[:-1])
        else:
            lines.append(segment)
    block_spans = []

    def add(lineno, type_id, span):
        if span in seen:
            return
        if any(s <= span[0] and span[1] <= e for s, e in block_spans):
            return  # already inside a redacted private-key block
        seen.add(span)
        found.append({"line": lineno, "type": type_id,
                      "start": span[0], "end": span[1]})

    for lineno, line in enumerate(lines, 1):
        base = line_starts[lineno - 1]
        for type_id, rx in _PATTERNS:
            for m in rx.finditer(line):
                span = (base + m.start(1), base + m.end(1))
                if type_id == "private_key_header":
                    # Slice redacts the whole key block, not just the
                    # header line: extend the span to the block's last
                    # line so the base64 body cannot ship behind a
                    # redacted header. Any finding already recorded
                    # inside the block is subsumed by it.
                    last = _pem_block_last_line(lines, lineno - 1)
                    span = (span[0],
                            line_starts[last] + len(lines[last]))
                    found[:] = [f for f in found
                                if not (span[0] <= f["start"]
                                        and f["end"] <= span[1])]
                    add(lineno, type_id, span)
                    block_spans.append(span)
                    continue
                add(lineno, type_id, span)
        if _AWS_SECRET_CONTEXT.search(line):
            for m in _BARE_40.finditer(line):
                add(lineno, "aws_secret_key",
                    (base + m.start(), base + m.end()))
    # Drop findings fully contained in a wider finding (for example a
    # password-in-URL span inside a generic-assignment span covering the
    # whole value): the wider span already covers the literal, and
    # recording or redacting both corrupts the offsets (see redact_text).
    kept = []
    for f in sorted(found, key=lambda x: (x["start"],
                                          -(x["end"] - x["start"]))):
        if any(k["start"] <= f["start"] and f["end"] <= k["end"]
               for k in kept):
            continue
        kept.append(f)
    return sorted(kept, key=lambda f: f["start"])


def redact_text(text, findings):
    """Return ``text`` with each finding span replaced by ``REDACTED``.

    ``findings`` is a list as returned by :func:`find_literals`.
    Overlapping spans are merged first: replacing a nested or partially
    overlapping span changes the text length, which invalidates the
    other span's offsets and can leave part of a literal behind. The
    merged spans are applied from the end of the text backwards so
    earlier offsets stay valid. Only the copy passed in is affected;
    the caller decides where (or whether) the result is written.
    """
    spans = sorted((f["start"], f["end"]) for f in findings)
    merged = []
    for s, e in spans:
        if merged and s < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out = text
    for s, e in reversed(merged):
        out = out[:s] + REDACTED + out[e:]
    return out
