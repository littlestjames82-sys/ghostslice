"""Regression tests for slice_adapter's Slice-absent secret fallback.

Seam found by the Oct 14, 2026 ecosystem pass: the fallback pattern list
in slice_adapter (used only when GhostSlice itself is not importable)
carried an AKIA-only AWS pattern while GhostSlice's canonical guard
(ghostslice/secrets_scan.py) covers AKIA and ASIA, so a temporary
session key in a proxied file slipped the secret guard entirely on the
fallback path and the file was forwarded instead of dropped. The audit
that came with the fix (SEAM_FIX_REPORT.md) found the same class of
drift in several more shapes; these tests pin the parity.

The canaries below are fake, labelled values in secret shapes, in the
same spirit as conftest's canaries. They are not real credentials.
"""

from __future__ import annotations

import sys

import pytest

from conftest import SRC, requires_ghostslice

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ghostproxy import slice_adapter  # noqa: E402

ASIA_CANARY = "ASIA1234567890ABCDEF"   # ASIA + 16, temporary-session shape
AKIA_CANARY = "AKIA1234567890ABCDEF"   # AKIA + 16, long-lived shape
BARE_40 = "Ab3dEf6hIjKlMnOpQrStUvWxYz0123456789ABCD"  # exactly 40 chars
AWS_DOCS_EXAMPLE = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # AWS docs example


@pytest.fixture()
def fallback_only(monkeypatch):
    """Force scan_secrets down the fallback path (GhostSlice absent)."""
    monkeypatch.setattr(slice_adapter, "available", lambda: False)
    return slice_adapter


def _types(findings):
    return [f["type"] for f in findings]


def test_asia_key_caught_by_fallback(fallback_only):
    """The seam itself: an ASIA temporary key must trip the fallback."""
    text = f"first line\nsecond line\naws_key = {ASIA_CANARY}\n"
    findings = fallback_only.scan_secrets("config.py", text)
    assert findings == [{"path": "config.py", "line": 3, "type": "aws-access-key"}]
    assert ASIA_CANARY not in repr(findings)


def test_akia_key_still_caught_by_fallback(fallback_only):
    findings = fallback_only.scan_secrets("config.py", f"aws_key = {AKIA_CANARY}")
    assert _types(findings) == ["aws-access-key"]
    assert AKIA_CANARY not in repr(findings)


def test_asia_key_caught_by_adapter_whatever_path_runs():
    """With Slice present the delegated path catches ASIA; without it the
    fallback now does. Either way the adapter path transform.py calls
    must not let the canary through."""
    findings = slice_adapter.scan_secrets("config.py", f"aws_key = {ASIA_CANARY}")
    assert "aws-access-key" in _types(findings)
    assert ASIA_CANARY not in repr(findings)


# (line, canonical type) pairs from the parity audit. Each line is one
# the canonical guard flags and the fallback previously missed or only
# caught by accident.
PARITY_CASES = [
    ("-----BEGIN DSA PRIVATE KEY-----", "private-key"),
    ("-----BEGIN PGP PRIVATE KEY-----", "private-key"),
    ("-----BEGIN RSA PRIVATE KEY-----", "private-key"),
    ("k = sk-proj-AbCdEfGhIjKlMnOpQrStUvWx", "openai-or-anthropic-key"),
    ("k = sk-ant-AbCdEfGhIjKlMnOpQrStUvWx", "openai-or-anthropic-key"),
    ("t = ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123_4567", "github-token"),
    ("t = xoxb-1234567890ab", "slack-token"),
    ("db = postgres://user:Str0ngPass@db.internal:5432/app", "password-in-url"),
    ('password: "hunter2hunter2"', "sensitive-assignment"),
    (f"the aws secret is {BARE_40} ok", "aws-secret-key"),
]


@pytest.mark.parametrize("line,expected", PARITY_CASES)
def test_fallback_parity_shapes(fallback_only, line, expected):
    findings = fallback_only.scan_secrets("probe.txt", line)
    assert expected in _types(findings), (line, findings)


@requires_ghostslice
@pytest.mark.parametrize("line,expected", PARITY_CASES)
def test_fallback_agrees_with_canonical_guard(fallback_only, line, expected):
    """Every type the real GhostSlice guard reports on these lines must
    also be reported by the fallback: drift in either direction fails."""
    from ghostslice.secrets_scan import scan_text

    canonical = {f["type"] for f in scan_text("probe.txt", line)}
    assert expected in canonical  # the fixture line means what we think
    fallback = set(_types(fallback_only.scan_secrets("probe.txt", line)))
    assert canonical <= fallback, (line, canonical, fallback)


def test_fallback_negative_controls(fallback_only):
    """Lines the canonical guard does not flag must stay unflagged on
    the fallback too: the AWS documentation example key (placeholder)
    and a bare 40-char value with no AWS-secret context."""
    assert fallback_only.scan_secrets(
        "probe.txt", f"aws_secret_access_key = {AWS_DOCS_EXAMPLE}") == []
    assert fallback_only.scan_secrets("probe.txt", f"commit = {BARE_40}") == []
    assert fallback_only.scan_secrets("probe.txt", "def main(): return 42") == []


def test_fallback_findings_never_carry_values(fallback_only):
    text = "\n".join([
        f"aws_key = {ASIA_CANARY}",
        "-----BEGIN RSA PRIVATE KEY-----",
        "t = xoxb-1234567890ab",
        "db = postgres://user:Str0ngPass@db.internal:5432/app",
    ])
    findings = fallback_only.scan_secrets("mixed.txt", text)
    assert findings, "expected the canary lines to be flagged"
    blob = repr(findings)
    for canary in (ASIA_CANARY, "xoxb-1234567890ab", "Str0ngPass"):
        assert canary not in blob
    assert all(set(f) == {"path", "line", "type"} for f in findings)
