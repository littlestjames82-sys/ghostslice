"""Secret shape scan, applied before any file is copied.

Deliberately conservative, same family as GhostSlice's secret guard:
known provider token shapes are flagged on sight, generic assignments
only when the name looks sensitive AND the value is long, varied, and
not an obvious placeholder.

Findings NEVER carry the secret value. A finding is a pattern type
string only; the fixture manifest records path + types, nothing else.
A file with no flagged shapes is "not flagged", never "secret-free":
the shapes are a known net, not a proof.
"""
from __future__ import annotations

import math
import re

_KNOWN_PATTERNS: list = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("openai-or-anthropic-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("stripe-key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{10,}\b")),
    ("url-password", re.compile(r"://[^\s/@:'\"]+:[^\s/@'\"]{3,}@")),
]

_PLACEHOLDER_MARKERS = (
    "example", "xxx", "your-", "your_", "yourkey", "placeholder",
    "changeme", "change-me", "change_me", "dummy", "sample", "fixture",
    "redacted", "insert-", "insert_", "todo", "fake", "test-key",
    "test_key", "not-a-real", "not_real", "mock",
)

_SENSITIVE_NAME_RE = re.compile(
    r"(key|token|secret|password|passwd|pwd|credential|auth|private)", re.IGNORECASE)
_ASSIGN_RE = re.compile(
    r"""^\s*(?:export\s+|const\s+|let\s+|var\s+)?["']?([A-Za-z_][A-Za-z0-9_.\-]*)["']?\s*[:=]\s*["']([^\s"']{16,})["']""")

# Unquoted assignment, env-file style: NAME=value with NO spaces
# around the '='. This is how .env files and shell exports carry
# literal secrets, and the quoted-assignment net above never sees
# them. The no-spaces shape plus the value gates in
# _env_value_is_literal keep ordinary code (``token = some_name``,
# spaced or a bare identifier reference) out of this net.
_ENV_ASSIGN_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=([^\s\"'/#;]{16,})\s*(?:#.*)?$")
_BARE_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _env_value_is_literal(value: str) -> bool:
    """Extra gates for an unquoted value: not a bare snake_case
    identifier (a variable reference in code, not a literal), and
    carrying a digit or mixed case, as real key material does."""
    if _BARE_IDENT_RE.match(value):
        return False
    has_digit = any(c.isdigit() for c in value)
    mixed_case = any(c.islower() for c in value) and any(c.isupper() for c in value)
    return has_digit or mixed_case

# Byte-level shapes catchable without decoding (binary files, undecodable text).
_BYTES_PATTERNS: list = [
    ("private-key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
]


def _is_placeholder(value: str) -> bool:
    """True when a value reads as a placeholder, not a live secret."""
    v = value.strip().strip("\"'").strip().lower()
    if not v:
        return True
    if any(m in v for m in _PLACEHOLDER_MARKERS):
        return True
    if v.startswith("${") or v.startswith("<") or set(v) <= {"*"}:
        return True
    return False


def _varied(value: str) -> bool:
    """Rough entropy gate so 'aaaa...' or a single repeated token is not flagged."""
    if len(set(value)) < 8:
        return False
    counts: dict = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(value)
    entropy = -sum((c / n) * math.log2(c / n) for c in counts.values())
    return entropy >= 3.0


def _scan_text(text: str) -> set:
    """The full pattern family over decoded text."""
    found: set = set()
    for name, pat in _KNOWN_PATTERNS:
        if pat.search(text):
            found.add(name)
    for line in text.splitlines():
        m = _ASSIGN_RE.match(line)
        if m:
            name, value = m.group(1), m.group(2)
        else:
            m = _ENV_ASSIGN_RE.match(line)
            if not m or not _env_value_is_literal(m.group(2)):
                continue
            name, value = m.group(1), m.group(2)
        if not _SENSITIVE_NAME_RE.search(name):
            continue
        if _is_placeholder(value) or not _varied(value):
            continue
        found.add("sensitive-assignment")
    return found


def _scan_utf16(data: bytes) -> set:
    """Full text scan of UTF-16 content, or nothing if it is not."""
    try:
        return _scan_text(data.decode("utf-16"))
    except (UnicodeDecodeError, ValueError):
        return set()


def scan_bytes(data: bytes) -> list:
    """Return the sorted list of pattern types found in raw bytes.

    Decodable text gets the full pattern family; undecodable data gets
    the byte-level shapes only. UTF-16 content (with a BOM it fails
    UTF-8 decoding; without one it decodes as NUL-interleaved text)
    gets the full family too: a token does not stop being a secret
    because the file was saved from a Windows editor. Never returns
    any part of a value.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        found = {name for name, pat in _BYTES_PATTERNS if pat.search(data)}
        found |= _scan_utf16(data)
        return sorted(found)
    found = _scan_text(text)
    if "\x00" in text:
        found |= _scan_utf16(data)
    return sorted(found)
