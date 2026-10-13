"""Secret guard: scan files that would be exported for likely secrets.

Zero-dependency, regex + entropy based, deliberately conservative:
known provider token shapes are flagged on sight, generic assignments
only when the variable name looks sensitive AND the value is long,
varied, and not an obvious placeholder.

Findings NEVER carry the secret value. Each finding records the path,
1-based line number, a pattern type, and a redacted preview of at most
the first 4 characters followed by an ellipsis marker.

False-positive care: empty values, placeholders (``example``,
``xxx``, ``your-key-here``, ``changeme``, ``dummy``, ``sample``,
``fixture``, ``redacted``, angle-bracket / env-var references, values
full of ``*``) are not flagged.
"""
from __future__ import annotations

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


def scan_text(path: str, text: str) -> list[dict]:
    """Return findings for one file's text. Values are redacted."""
    findings: list[dict] = []
    seen: set[tuple[int, str]] = set()

    def add(line_no: int, ptype: str, value: str):
        key = (line_no, ptype)
        if key in seen:
            return
        seen.add(key)
        findings.append({
            "path": path,
            "line": line_no,
            "type": ptype,
            "redacted": redact(value),
        })

    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        # Full-line comments are documentation/examples far more often
        # than live secrets; skip them (except private-key blocks).
        is_comment = stripped.startswith(("#", "//", "*", "/*"))

        known_before = len(findings)
        for ptype, pat in _KNOWN_PATTERNS:
            if ptype == "aws-secret-key":
                continue  # context-gated below
            m = pat.search(line)
            if m and not _is_placeholder(m.group(0)):
                if ptype == "private-key" or not is_comment:
                    add(line_no, ptype, m.group(0))
        known_hit = len(findings) > known_before
        if _AWS_SECRET_CONTEXT.search(line):
            m = _BARE_40.search(line)
            if m and not _is_placeholder(m.group(0)):
                add(line_no, "aws-secret-key", m.group(0))

        m = _URL_PASSWORD_RE.search(line)
        if m and not _is_placeholder(m.group(1)):
            add(line_no, "password-in-url", m.group(1))

        if is_comment or known_hit:
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
                add(line_no, "sensitive-assignment", value)
                continue

        m = _GENERIC_ASSIGN_RE.match(line)
        if m:
            value = m.group(2)
            if not _is_placeholder(value) and _entropy(value) >= 4.0 \
                    and any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
                add(line_no, "high-entropy-assignment", value)

    findings.sort(key=lambda f: (f["line"], f["type"]))
    return findings


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
