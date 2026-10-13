"""Secret guard: scan files that would be exported for likely secrets.

Zero-dependency, regex + entropy based, deliberately conservative:
known provider token shapes are flagged on sight, generic assignments
only when the variable name looks sensitive AND the value is long,
varied, and not an obvious placeholder.

Findings NEVER carry the secret value. Each finding records the path,
1-based line number, a pattern type, and a redacted preview of at most
the first 4 characters followed by an ellipsis marker.

Redaction (v0.17): `redact_text` replaces the flagged VALUES in a text
with typed placeholders so a file can ship in a bundle without its
secrets — see its docstring for the token format and the fingerprint
rule. It is built on `_scan_rich`, the same detection core `scan_text`
reports from, so the guard and the redactor can never disagree about
what counts as a secret.

False-positive care: empty values, placeholders (``example``,
``xxx``, ``your-key-here``, ``changeme``, ``dummy``, ``sample``,
``fixture``, ``redacted``, angle-bracket / env-var references, values
full of ``*``) are not flagged.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

PLACEHOLDER_MARKERS = (
    "example", "xxx", "your-", "your_", "yourkey", "placeholder",
    "changeme", "change-me", "change_me", "dummy", "sample", "fixture",
    "redacted", "insert-", "insert_", "todo", "fake", "test-key",
    "test_key", "not-a-real", "not_real", "mock",
)

_KNOWN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai-or-anthropic-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("aws-secret-key", re.compile(r"\b[A-Za-z0-9/+=]{40}\b(?=.*)")),  # handled specially below
]

# The bare 40-char base64-ish shape is too noisy on its own; it is only
# used when the line also names something AWS-secret-like.
_AWS_SECRET_CONTEXT = re.compile(r"aws.{0,20}secret|secret.{0,20}aws", re.IGNORECASE)
_BARE_40 = re.compile(r"\b[A-Za-z0-9/+=]{40}\b")

_URL_PASSWORD_RE = re.compile(r"://[^/\s:@'\"]+:([^/\s:@'\"]{3,})@")
_SENSITIVE_NAME_RE = re.compile(
    r"(key|token|secret|password|passwd|pwd|credential|auth|private)", re.IGNORECASE)
# NAME = value  /  NAME: value  /  "NAME": "value"  (env, code, yaml, json-ish)
# Groups: 1=name, 2=opening quote ("" if bare), 3=value.
_ASSIGN_RE = re.compile(
    r"""^\s*(?:export\s+)?["']?([A-Za-z_][A-Za-z0-9_.\-]*)["']?\s*[:=]\s*(["']?)([^\s"'#,;]+)""")
_GENERIC_ASSIGN_RE = re.compile(
    r"""^\s*(?:export\s+|const\s+|let\s+|var\s+)?["']?([A-Za-z_][A-Za-z0-9_.\-]*)["']?\s*[:=]\s*["']([^\s"']{16,})["']""")

# In code files an unquoted right-hand side is an expression/reference,
# never a literal secret; in config/env/yaml files bare values are
# literals, so they are still checked.
CODE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
             ".go", ".rs", ".java", ".cs", ".rb", ".php", ".sh", ".swift", ".kt"}


def redact(value: str) -> str:
    """At most the first 4 characters; never the full value."""
    v = (value or "").strip()
    if len(v) <= 4:
        return "***"
    return v[:4] + "…"


def _is_placeholder(value: str) -> bool:
    v = value.strip().strip("\"'").strip()
    if not v:
        return True
    low = v.lower()
    if any(m in low for m in PLACEHOLDER_MARKERS):
        return True
    if low in {"none", "null", "true", "false", "undefined", "env", "secret"}:
        return True
    if v.startswith(("<", "${", "{{", "{", "$")) or "://" in v and "@" not in v:
        return True
    if low.startswith(("choose-", "choose_", "pick-", "pick_")):
        return True  # instructional placeholder: "choose-a-long-secret"
    # A dotted reference to another variable (opts.requireTokens,
    # config.token) is code, not a literal secret. Purely alphabetic
    # short segments only, so JWT-shaped literals still flag.
    if re.fullmatch(r"[A-Za-z_$][A-Za-z_$]*(\.[A-Za-z_$][A-Za-z_$]*)+", v) and len(v) < 40:
        return True
    if v[0] in "!([" or "(" in v:
        return True  # expression / function call, not a literal
    if set(v) <= {"*", "x", "X", ".", "-", "_"}:
        return True
    if "process.env" in v or "os.environ" in v or "getenv" in v:
        return True
    # repeated short pattern, e.g. abcabcabcabc or 11111111
    if len(v) >= 6 and len(set(v)) <= 2:
        return True
    return False


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


_PEM_END_RE = re.compile(
    r"-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")
_PEM_BODY_RE = re.compile(r"[A-Za-z0-9+/=]{16,}")


def _pem_block(lines: list[str], start: int) -> tuple[int, int]:
    """(first, last) 0-based inclusive line range of the PEM block
    whose BEGIN header is on `lines[start]`: through the matching END
    line when present, else over the following bare-base64 body lines
    (a slice can cut a block before its END line; the body is the
    secret material either way)."""
    for j in range(start + 1, len(lines)):
        if _PEM_END_RE.search(lines[j]):
            return start, j
    last = start
    for j in range(start + 1, len(lines)):
        if _PEM_BODY_RE.fullmatch(lines[j].strip()):
            last = j
        else:
            break
    return start, last


def _scan_rich(path: str, text: str, comments: bool = False) -> list[dict]:
    """Detection core: like `scan_text`, but each finding also carries
    the literal `value` and where it sits — `span` = (start, end)
    character offsets within its line, or `block` = (first, last)
    1-based inclusive line range for a private-key block (span None).

    The value/span fields are for the redactor only; `scan_text`
    strips them, so reported findings never carry a secret.

    `comments` is the one knob between the two call contexts. The
    REPORTING scan (default) skips full-line comments: they are
    documentation/examples far more often than live secrets, and a
    noisy guard gets ignored. The REDACTION scan (comments=True)
    judges comment lines like any other line: a bundle is a
    publication artifact, a Markdown heading is `#`-prefixed
    CONTENT, and a real key in a comment must not ship behind a
    "redacted" claim. Redaction is therefore a strict superset of
    the guard — same core, never weaker.
    """
    findings: list[dict] = []
    seen: set[tuple[int, str]] = set()
    lines = text.splitlines()

    def add(line_no: int, ptype: str, value: str,
            span: tuple[int, int] | None = None,
            block: tuple[int, int] | None = None):
        key = (line_no, ptype)
        if key in seen:
            return
        seen.add(key)
        findings.append({
            "path": path,
            "line": line_no,
            "type": ptype,
            "redacted": redact(value),
            "value": value,
            "span": span,
            "block": block,
        })

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Full-line comments are skipped by the reporting scan (see
        # the docstring); the redaction scan judges them as content.
        is_comment = stripped.startswith(("#", "//", "*", "/*"))
        comment_line = is_comment and not comments

        known_before = len(findings)
        for ptype, pat in _KNOWN_PATTERNS:
            if ptype == "aws-secret-key":
                continue  # context-gated below
            m = pat.search(line)
            if m and not _is_placeholder(m.group(0)):
                if ptype == "private-key":
                    first, last = _pem_block(lines, line_no - 1)
                    add(line_no, ptype,
                        "\n".join(lines[first:last + 1]),
                        block=(first + 1, last + 1))
                elif not comment_line:
                    add(line_no, ptype, m.group(0), span=m.span())
        known_hit = len(findings) > known_before
        if _AWS_SECRET_CONTEXT.search(line):
            m = _BARE_40.search(line)
            if m and not _is_placeholder(m.group(0)):
                add(line_no, "aws-secret-key", m.group(0), span=m.span())

        m = _URL_PASSWORD_RE.search(line)
        if m and not _is_placeholder(m.group(1)):
            add(line_no, "password-in-url", m.group(1), span=m.span(1))

        if comment_line or known_hit:
            continue  # a known-shape hit on this line is the finding; don't double-report it

        is_code = Path(path).suffix.lower() in CODE_EXTS
        m = _ASSIGN_RE.match(line)
        if m and _SENSITIVE_NAME_RE.search(m.group(1)):
            quoted = bool(m.group(2))
            value = m.group(3)
            if quoted and line[m.end(3):m.end(3) + 1] not in ("", '"', "'"):
                pass  # quoted string continues past a space: prose, not a secret
            elif is_code and not quoted:
                pass  # bare RHS in code is a reference/expression
            elif len(value) >= 8 and not _is_placeholder(value):
                add(line_no, "sensitive-assignment", value, span=m.span(3))
                continue

        m = _GENERIC_ASSIGN_RE.match(line)
        if m:
            value = m.group(2)
            if not _is_placeholder(value) and _entropy(value) >= 4.0 \
                    and any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
                add(line_no, "high-entropy-assignment", value, span=m.span(2))

    findings.sort(key=lambda f: (f["line"], f["type"]))
    return findings


def scan_text(path: str, text: str, comments: bool = False) -> list[dict]:
    """Return findings for one file's text. Values are redacted.

    `comments=True` is the redaction context (see _scan_rich): every
    caller that reports to a human uses the default.
    """
    return [{k: f[k] for k in ("path", "line", "type", "redacted")}
            for f in _scan_rich(path, text, comments=comments)]


# ---------------------------------------------------------------------------
# Redaction (v0.17): replace flagged values in place
# ---------------------------------------------------------------------------

# Every kind the scanner can emit. scan_text's placeholder/entropy/name
# gates ARE the severity filter — anything it reports is something
# `ghostslice secrets` shows the user and --exclude-secrets would nuke
# a whole file for — so --redact judges exactly the same universe and
# differs only in remedy (replace the value, keep the file). A future
# scanner kind that is not added here is NOT silently shipped: it
# surfaces as a "left in place" finding in redact_text's return and in
# the export summary.
REDACTED_KINDS = frozenset({
    "private-key", "aws-access-key", "aws-secret-key", "github-token",
    "openai-or-anthropic-key", "slack-token", "password-in-url",
    "sensitive-assignment", "high-entropy-assignment",
})

# A sha256 prefix is a safe cross-reference only for a value with
# enough entropy to resist a dictionary attack. The guard flags short
# literals (an 8-character password, a 5-character URL password), and
# an 8-hex fingerprint of one of those is a brute-force oracle, so
# values shorter than this get a fingerprintless token.
MIN_FINGERPRINT_LEN = 12


class RedactionError(ValueError):
    """A redacted text still contains a reportable secret. Raised
    instead of ever letting the caller ship it."""


def fingerprint(value: str) -> str:
    """First 8 hex chars of the value's sha256: a stable, one-way
    cross-reference for high-enough-entropy literals."""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:8]


def redaction_token(ptype: str, value: str) -> str:
    """The placeholder for one flagged value: `[REDACTED:<kind>:<fp>]`,
    or `[REDACTED:<kind>]` for a short (low-entropy) value. The token
    contains the scanner's own "redacted" placeholder marker, so a
    re-scan of redacted output is clean by construction."""
    if len(value) >= MIN_FINGERPRINT_LEN:
        return f"[REDACTED:{ptype}:{fingerprint(value)}]"
    return f"[REDACTED:{ptype}]"


def redact_text(path: str, text: str,
                kinds: frozenset | set = REDACTED_KINDS
                ) -> tuple[str, list[dict], list[dict]]:
    """Replace every flagged secret VALUE in `text` with its token.

    Returns (new_text, applied, leftovers):
      applied:   [{"line", "type", "token"}] — one per finding whose
                 value was removed; line numbers are relative to
                 `text` as given (for exports: the SLICE, not the
                 source file — the scan runs on the final slice text,
                 never on pre-slice findings, because slicing can
                 split or merge lines).
      leftovers: [{"line", "type"}] — findings whose kind is not in
                 `kinds`; their values stay, and callers must surface
                 them (the export summary does), never ship silently.

    Mechanics: block findings (private-key) replace their whole line
    range with the single token; line findings replace the literal's
    span, plus any further occurrences of the same literal on the
    same line (the scanner reports only the first match per pattern
    per line). Identical literals map to identical tokens, so
    cross-references between files/runs stay visible. A text with no
    reportable findings is returned byte-identical. When any rewrite
    happens, line endings normalise to "\\n" (exports already rewrite
    every file they ship).

    Safety gate: the result is re-scanned; if a `kinds` finding
    remains, RedactionError is raised — a redaction bug must fail
    loudly, never ship a bundle that claims to be clean.

    The scan is the guard's own core in its redaction context
    (comments=True — see _scan_rich): comment lines, Markdown
    headings, and block-comment bodies are content for a bundle,
    so a flagged shape there is replaced too. Placeholder-shaped
    examples in comments are still filtered by the scanner's
    placeholder rules and stay untouched.
    """
    rich = _scan_rich(path, text, comments=True)
    targets = [f for f in rich if f["type"] in kinds]
    leftovers = [{"line": f["line"], "type": f["type"]}
                 for f in rich if f["type"] not in kinds]
    if not targets:
        return text, [], leftovers

    lines = text.splitlines()
    applied: list[dict] = []
    consumed: set[int] = set()  # 0-based line indexes swallowed by a block

    # Blocks first: they consume whole line ranges.
    for f in targets:
        if f["block"] is None:
            continue
        first, last = f["block"][0] - 1, f["block"][1] - 1
        token = redaction_token(f["type"], f["value"])
        lines[first] = token
        for j in range(first + 1, last + 1):
            lines[j] = None  # dropped in the rebuild below
            consumed.add(j)
        consumed.add(first)
        applied.append({"line": f["line"], "type": f["type"], "token": token})

    # Line spans, rightmost first per line so offsets stay valid.
    by_line: dict[int, list[dict]] = {}
    for f in targets:
        if f["block"] is None:
            by_line.setdefault(f["line"], []).append(f)
    for line_no, group in by_line.items():
        idx = line_no - 1
        if idx in consumed or not (0 <= idx < len(lines)) or lines[idx] is None:
            # Inside a replaced block: the value is already gone.
            for f in group:
                applied.append({"line": f["line"], "type": f["type"],
                                "token": redaction_token(f["type"], f["value"])})
            continue
        line = lines[idx]
        done_spans: list[tuple[int, int]] = []
        for f in sorted(group, key=lambda g: g["span"][0], reverse=True):
            start, end = f["span"]
            if any(start < e and s < end for s, e in done_spans):
                # Overlapping finding (e.g. an aws-secret span inside
                # a sensitive-assignment value): the literal is
                # removed by the wider replacement already applied.
                applied.append({"line": f["line"], "type": f["type"],
                                "token": redaction_token(f["type"], f["value"])})
                continue
            token = redaction_token(f["type"], f["value"])
            line = line[:start] + token + line[end:]
            done_spans.append((start, end))
            applied.append({"line": f["line"], "type": f["type"], "token": token})
        # The scanner reports only the first match per pattern per
        # line; a repeated literal on the same line is the same
        # secret and collapses to the same token.
        for f in group:
            token = redaction_token(f["type"], f["value"])
            if f["value"] and f["value"] in line:
                line = line.replace(f["value"], token)
        lines[idx] = line

    out = "\n".join(l for l in lines if l is not None)
    if text.endswith("\n"):
        out += "\n"
    applied.sort(key=lambda a: (a["line"], a["type"]))

    remaining = [f for f in _scan_rich(path, out, comments=True)
                 if f["type"] in kinds]
    if remaining:
        first = remaining[0]
        raise RedactionError(
            f"redaction of {path} left a {first['type']} finding at "
            f"slice line {first['line']}; refusing to ship it")
    return out, applied, leftovers


def scan_scan_result(scan_result) -> list[dict]:
    """Scan every file in a scanner ScanResult; returns all findings."""
    out: list[dict] = []
    for entry in scan_result.files:
        try:
            text = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.extend(scan_text(entry.path, text))
    out.sort(key=lambda f: (f["path"], f["line"]))
    return out


def scan_path(root) -> list[dict]:
    """Convenience: scan a project directory (or single file)."""
    from .scanner import scan
    return scan_scan_result(scan(root))
