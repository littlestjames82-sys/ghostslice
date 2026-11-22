"""Sensitive-data guard: findings are path + line + type only, never values.

Flagged documents are HELD OUT of exports by default (PLAN: this is a gate,
not a report)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit-card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("us-phone", re.compile(r"\b(?:\+1[ -]?)?\(?\d{3}\)?[ -]\d{3}-\d{4}\b")),
    ("api-key-shape", re.compile(r"\b(?:sk|ghp|gho|xox[baprs])[-_][A-Za-z0-9\-_]{10,}\b")),
    ("password-assignment", re.compile(r"(?i)\bpassword\s*[:=]\s*\S+")),
]

# email/phone appear in ordinary business docs as contact info; only strong
# personal/secret shapes hold a document out by default.
HOLD_TYPES = {"ssn", "credit-card", "api-key-shape", "password-assignment"}


@dataclass
class Finding:
    """One sensitive-shape match: where it was found, never what it was.

    Deliberately carries only the document path, the line number, and
    the finding type (for example ``credit-card``). The matched value
    is never stored, printed, or exported.
    """

    path: str
    line: int
    type: str

    def to_dict(self):
        return {"path": self.path, "line": self.line, "type": self.type}


def _luhn_ok(digits: str) -> bool:
    """Return True when *digits* passes the Luhn checksum.

    Used to reduce false positives: a long digit string is only
    treated as a card-number shape when it also checksums like one.
    """
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def scan_text(path: str, text: str) -> list[Finding]:
    """Scan *text* for sensitive shapes, at most one finding per type per line.

    ``path`` is only copied into the findings for reporting; the
    matched values themselves are discarded.
    """
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for kind, pat in _PATTERNS:
            for m in pat.finditer(line):
                if kind == "credit-card":
                    digits = re.sub(r"\D", "", m.group(0))
                    if not (13 <= len(digits) <= 19 and _luhn_ok(digits)):
                        continue
                findings.append(Finding(path=path, line=lineno, type=kind))
                break  # one finding per type per line is enough
    return findings


def hold_findings(findings: list[Finding]) -> list[Finding]:
    """Return only the findings strong enough to hold a document out.

    Ordinary contact details (email, phone) are reported but do not
    hold a document out; see ``HOLD_TYPES``.
    """
    return [f for f in findings if f.type in HOLD_TYPES]
