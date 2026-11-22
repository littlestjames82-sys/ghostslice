"""Secret-shaped literal scan (shapes only, values never reported).

Used as a gate, not a vault: callers block or exclude anything this
scan flags and record only the shape name and line number. A clean
scan is not a guarantee that a file holds no secrets, only that none
of the recognised shapes in _PATTERNS were found.
"""
from __future__ import annotations

import re

_PATTERNS = [
    # Provider shapes shared with GhostSlice's canonical scanner
    # (ghostslice.secrets_scan): keep these expressions aligned there.
    # In particular, AWS access-key ids cover both long-lived AKIA keys
    # and ASIA temporary session keys.
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    # Same shape GhostSlice's scanner uses: sk-, sk-ant- and sk-proj-
    # keys. Without it an sk- key sitting in prose (no "key =" label)
    # matched nothing and was exported verbatim.
    ("openai-or-anthropic-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}\b")),
    # Angle-bracket redaction marker standing where a credential value
    # was removed (e.g. <redacted_api_token_1>): the marker occupies the
    # credential's place in the text, so an item carrying one is blocked
    # like any other flagged item rather than copied into the pack.
    ("redacted-credential-marker", re.compile(
        r"<redacted(?:_[a-z0-9]+)*>", re.IGNORECASE)),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("generic-api-key", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}")),
    ("private-key", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("password-in-url", re.compile(r"://[^/\s:@'\"]+:[^/\s:@'\"]{3,}@")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}\b")),
]

# GhostSlice also has a context-gated AWS-secret detector: a bare
# 40-character base64-ish value is only a finding when its line names
# an AWS secret. It is deliberately not copied here as a bare shape:
# the 40-character shape alone matches ordinary hashes, and Primer's
# labelled generic-api-key guard covers the assignment form.


def scan_text(text: str) -> list[dict]:
    """Return findings as {type, line} only. Values are never included."""
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, pat in _PATTERNS:
            if pat.search(line):
                findings.append({"type": name, "line": lineno})
    return findings
