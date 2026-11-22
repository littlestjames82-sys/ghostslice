"""Secret-shape redaction for free text quoted into the pack.

Marker lines, commit subjects, and report excerpts are quoted text from
the project. They can accidentally contain a credential. Every piece of
free text that lands in HANDOFF.md or handoff.json passes through
``redact_text`` first. Shapes only, conservative, stdlib ``re`` only.

Shape alignment (Oct 14, 2026, ecosystem seam fix, SEAM_FIX_REPORT.md):
the patterns below are aligned with GhostSlice's canonical secret
guard (``ghostslice.secrets_scan``). The AWS access-key pattern is the
canonical ``AKIA|ASIA`` form, so temporary session keys are redacted
too; the GitHub, OpenAI/Anthropic, and Slack patterns are the
canonical spellings; the context-gated AWS secret shape and the
password-in-URL shape are mirrored from the guard as well. Where this
redactor deliberately differs from the guard (no placeholder
allow-list, no PEM block handling, no high-entropy heuristic), the
reason is recorded in SEAM_FIX_REPORT.md; the standing rule here is
fail closed, because the input is quoted fragments, not whole files.
"""
from __future__ import annotations

import re

# Mirrors of GhostSlice's canonical known-shape patterns
# (ghostslice.secrets_scan._KNOWN_PATTERNS).
_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_GITHUB_TOKEN = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")
_OPENAI_OR_ANTHROPIC_KEY = re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}\b")
_SLACK_TOKEN = re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")

# Handoff extras: shapes the Slice guard does not list, kept because
# a quoted fragment can carry them and redacting them costs nothing.
_GITHUB_FINE_GRAINED_PAT = re.compile(r"github_pat_[A-Za-z0-9_]{20,}")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{12,}")

_SHAPES = [
    _AWS_ACCESS_KEY,
    _GITHUB_TOKEN,
    _GITHUB_FINE_GRAINED_PAT,
    _OPENAI_OR_ANTHROPIC_KEY,
    _SLACK_TOKEN,
]

# password-in-url (canonical): only the password group is replaced,
# the rest of the URL stays readable.
_URL_PASSWORD = re.compile(r"(://[^/\s:@'\"]+:)([^/\s:@'\"]{3,})(@)")

# key = value / key: value where the key names a credential. The
# value is replaced whatever its length or shape: this is a redactor,
# not a scanner, so there is no placeholder allow-list. The name set
# follows the canonical guard's, minus the names that are too
# ambiguous in quoted prose (bare key / token / auth / private / pwd).
_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|credential|api[_-]?key|access[_-]?token|auth[_-]?token)"
    r"(\s*[:=]\s*)\S+"
)

# aws-secret-key (canonical, context-gated): a bare 40-char
# base64-shaped token is only treated as an AWS secret on a line
# that also names AWS and secret near each other.
_AWS_SECRET_CONTEXT = re.compile(r"aws.{0,20}secret|secret.{0,20}aws", re.IGNORECASE)
_BARE_40 = re.compile(r"\b[A-Za-z0-9/+=]{40}\b")

REDACTED = "[redacted-secret-shape]"


def _redact_aws_secret_lines(text: str) -> str:
    """Redact bare 40-char tokens, but only on AWS-secret context lines."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if _AWS_SECRET_CONTEXT.search(line):
            lines[i] = _BARE_40.sub(REDACTED, line)
    return "\n".join(lines)


def redact_text(text: str) -> str:
    """Return ``text`` with credential-shaped substrings replaced."""
    if not text:
        return text
    out = text
    for pat in _SHAPES:
        out = pat.sub(REDACTED, out)
    out = _URL_PASSWORD.sub(
        lambda m: m.group(1) + REDACTED + m.group(3), out)
    out = _ASSIGNMENT.sub(lambda m: m.group(1) + m.group(2) + REDACTED, out)
    out = _BEARER.sub("Bearer " + REDACTED, out)
    out = _redact_aws_secret_lines(out)
    return out


def clean_line(text: str, limit: int = 160) -> str:
    """Redact, collapse whitespace, and truncate one quoted line."""
    text = redact_text(text or "")
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text
