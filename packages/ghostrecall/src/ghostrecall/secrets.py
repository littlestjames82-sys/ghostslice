"""Secrets carry-over guard, compatible in spirit with GhostSlice v0.4:
findings record path + line + type ONLY, never the value. An item with
any finding is blocked from export by default."""
from __future__ import annotations
import re
from dataclasses import dataclass

_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai-or-anthropic-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("generic-secret-assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-/+=]{20,}")),
]
_PLACEHOLDERS = ("example", "xxx", "your-", "changeme", "placeholder", "dummy",
                 "sample", "fixture", "redacted", "not-a-real", "fake", "test-key")

@dataclass
class Finding:
    path: str
    line: int
    type: str
    def to_dict(self): return {"path": self.path, "line": self.line, "type": self.type}

def scan_text(text: str, path: str) -> list[Finding]:
    """Scan *text* line by line and return one Finding per flagged line.

    *path* is the label recorded on each finding (a project-relative
    path or ``git:<short-hash>``). Lines mentioning a placeholder word
    (example, dummy, redacted, ...) are exempt, matching GhostSlice.
    """
    out: list[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        for name, pat in _PATTERNS:
            m = pat.search(line)
            if not m:
                continue
            # Placeholder exemption is scoped to the MATCHED secret
            # itself (e.g. a value literally containing "example" or
            # "changeme"). Checking the whole line let any real secret
            # through whenever a placeholder word appeared anywhere
            # on the line, e.g. a trailing "# example" comment or an
            # appended "fake".
            if any(p in m.group(0).lower() for p in _PLACEHOLDERS):
                continue
            out.append(Finding(path, i, name))
            break
    return out
