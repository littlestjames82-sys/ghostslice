"""Secret-shaped string discipline, mirroring GhostSlice's guard.

GhostReplay outputs (REPLAY.md, replay-report.json, PROPOSAL.md,
proposal JSON, the ledger, console) must NEVER contain a
secret-shaped string from a transcript. Two defences:

1. Reports never quote transcript text at all, except file paths,
   symbol names, counts, and fingerprints (sha256 prefixes).
2. Every string a report does emit passes through `sanitize()`,
   which replaces secret-shaped spans with [REDACTED:<kind>].

`scan_text` returns findings as {line, type} only - the matched
value is never returned, stored, or printed, matching GhostSlice
v0.4 behaviour (path + line + type only).
"""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private-key", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai-or-anthropic-key", re.compile(
        r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("generic-assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|pwd)"
        r"\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
    ("generic-assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|pwd)"
        r"\s*[:=]\s*[^\s'\"]{12,}")),
    ("url-password", re.compile(r"://[^\s/@:]+:[^\s/@]{3,}@")),
    ("bearer-token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_\-\.]{16,}")),
]


def scan_lines(lines: list[str], source: str) -> list[dict]:
    """Findings for a list of raw lines: {source, line, type} only."""
    findings: list[dict] = []
    for i, line in enumerate(lines, start=1):
        for kind, pat in _PATTERNS:
            if pat.search(line):
                findings.append({"source": source, "line": i, "type": kind})
                break
    return findings


def scan_text(text: str, source: str) -> list[dict]:
    """Scan a whole text blob; see :func:`scan_lines` for the contract."""
    return scan_lines(text.splitlines(), source)


def sanitize(text: str) -> str:
    """Replace any secret-shaped span with [REDACTED:<kind>]."""
    if not text:
        return text
    out = text
    for kind, pat in _PATTERNS:
        out = pat.sub(f"[REDACTED:{kind}]", out)
    return out


def sanitize_obj(obj):
    """Recursively sanitize every string in a JSON-able structure."""
    if isinstance(obj, str):
        return sanitize(obj)
    if isinstance(obj, list):
        return [sanitize_obj(v) for v in obj]
    if isinstance(obj, dict):
        # Keys are strings too and can carry a secret (e.g. a bundle
        # path or a session-supplied name used as a mapping key);
        # sanitizing only values would leak those verbatim.
        return {(sanitize(k) if isinstance(k, str) else k):
                sanitize_obj(v) for k, v in obj.items()}
    return obj
