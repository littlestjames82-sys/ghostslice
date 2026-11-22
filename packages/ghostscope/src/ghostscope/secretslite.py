"""Secret-shaped line detection for *added* diff lines.

GhostScope raises risk when a change introduces a secret shape.
Findings carry line number + type only; the value is never stored
or printed, mirroring GhostSlice's secrets guard discipline. This
is a deliberately small pattern set for risk signalling, not a
replacement for `ghostslice secrets`.

Alignment contract (audited Oct 14, 2026, see SEAM_FIX_REPORT.md):
the SET stays lite by design - canonical classes that need line
context, a full assignment parser, or entropy scoring (the bare-40
aws-secret-key shape, high-entropy-assignment, parser-grade
sensitive-assignment) are absent or approximated on purpose. But every shape this set
does carry tracks GhostSlice's canonical pattern for that shape
(PLAN.md: "using Slice rules, not new ones"); a kept shape must
never be a narrowed copy of the canonical one.
"""
from __future__ import annotations

import re

_PATTERNS = [
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai-or-anthropic-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("password-in-url", re.compile(r"[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s/@]{4,}@")),
    ("sensitive-assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|passwd|password|access[_-]?token)\b"
        r"\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
]


def scan_added_lines(path: str, added: list[tuple[int, str]]) -> list[dict]:
    findings: list[dict] = []
    for lineno, text in added:
        for kind, pat in _PATTERNS:
            if pat.search(text):
                findings.append({"path": path, "line": lineno, "type": kind})
                break
    return findings
