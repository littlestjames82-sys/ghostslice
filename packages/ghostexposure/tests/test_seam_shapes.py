"""Seam-fix regression tests (Oct 14, 2026): GhostExposure's secret
shape list vs GhostSlice's canonical guard list.

The ecosystem pass found that Exposure's aws_access_key pattern was
AKIA-only, so ASIA temporary session keys shipped unredacted while
GhostSlice (and GhostLogs/GhostFixture) catch both prefixes. The fix
aligned every canonical Slice shape Exposure detects, added the
canonical shapes Exposure was missing, and made private-key redaction
cover the whole key block. Per-shape record: SEAM_FIX_REPORT.md.

All literals below are FAKE, test-only strings in secret shapes. None
is, or has ever been, a real credential.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ghostexposure.secrets import find_literals, redact_text  # noqa: E402

from helpers import find_exposure_json, load_json, read_all_text  # noqa: E402

ASIA_CANARY = "ASIA1234567890ABCDEF"  # ASIA + 16: temporary session key shape
AKIA_CANARY = "AKIA1234567890ABCDEF"  # AKIA + 16: long-lived key shape


def _only_finding(text):
    findings = find_literals(text)
    assert len(findings) == 1, f"expected exactly 1 finding, got {findings}"
    return findings[0]


def _span_text(text, finding):
    return text[finding["start"]:finding["end"]]


# --- unit level: the aligned canonical shapes -------------------------


def test_asia_temp_key_matches_aws_access_key():
    line = f'SESSION_KEY = "{ASIA_CANARY}"'
    f = _only_finding(line)
    assert f["type"] == "aws_access_key"
    assert _span_text(line, f) == ASIA_CANARY


def test_akia_long_lived_key_still_matches():
    line = f'SESSION_KEY = "{AKIA_CANARY}"'
    f = _only_finding(line)
    assert f["type"] == "aws_access_key"
    assert _span_text(line, f) == AKIA_CANARY


def test_github_token_with_underscore_matches_in_full():
    # Slice's body class includes "_"; without it this token matched
    # nothing (first body segment is 10 chars) and shipped whole.
    token = "ghp_ABCDEFGHIJ_1234567890abcdefghij"
    line = f'tok = "{token}"'
    f = _only_finding(line)
    assert f["type"] == "github_token"
    assert _span_text(line, f) == token


def test_slack_token_matches():
    token = "xoxb-1234567890-abcdefghij"
    line = f'hook = "{token}"'
    f = _only_finding(line)
    assert f["type"] == "slack_token"
    assert _span_text(line, f) == token


def test_openai_key_at_slice_threshold_matches():
    # Slice flags sk- bodies of 16+; Exposure required 20+.
    token = "sk-1234567890abcdefgh"  # 18-char body
    line = f'k = "{token}"'
    f = _only_finding(line)
    assert f["type"] == "openai_style_key"
    assert _span_text(line, f) == token


def test_password_in_url_redacts_password_only():
    line = 'db = "postgres://svc_user:UrlPass123@db.internal:5432/app"'
    f = _only_finding(line)
    assert f["type"] == "password_in_url"
    assert _span_text(line, f) == "UrlPass123"
    out = redact_text(line, [f])
    assert "UrlPass123" not in out
    assert "postgres://svc_user:" in out and "@db.internal" in out


def test_aws_secret_key_is_context_gated():
    value = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYZQ9KLMNOPQ"  # exactly 40 chars
    assert len(value) == 40
    line = f"aws_secret_access_key = {value}"
    f = _only_finding(line)
    assert f["type"] == "aws_secret_key"
    assert _span_text(line, f) == value
    # Same value with no AWS-secret context on the line: not a finding,
    # exactly as Slice's context gate behaves.
    assert find_literals(f"checksum = {value}") == []


def test_private_key_block_is_redacted_whole():
    body1 = "MIIEowIBAAKCAQEA12345678"
    body2 = "abcdEFGH12345678ijklMNOP"
    text = ("-----BEGIN RSA PRIVATE KEY-----\n"
            f"{body1}\n{body2}\n"
            "-----END RSA PRIVATE KEY-----\n"
            "after = 1\n")
    f = _only_finding(text)
    assert f["type"] == "private_key_header"
    out = redact_text(text, [f])
    assert body1 not in out and body2 not in out
    assert "END RSA PRIVATE KEY" not in out
    assert "after = 1" in out


# --- end to end: ASIA canary on every Exposure output surface ---------


def _write_asia_project(tmp_path: Path) -> Path:
    project = tmp_path / "asia_project"
    (project / "config").mkdir(parents=True)
    (project / "config" / "aws_config.py").write_text(
        '"""Fixture with a planted FAKE ASIA temporary key."""\n'
        f'SESSION_KEY = "{ASIA_CANARY}"\n',
        encoding="utf-8")
    (project / "README.md").write_text("# asia fixture\n", encoding="utf-8")
    return project


def test_asia_canary_caught_on_every_output_surface(cli, surface_pack, tmp_path):
    project = _write_asia_project(tmp_path)
    bundle = tmp_path / "bundle"
    result = cli(["export", project, "--surface", surface_pack, "-o", bundle])
    assert result.returncode == 0, f"export failed:\n{result.stdout}\n{result.stderr}"

    # CLI stdout surface: the canary is never echoed; the redaction is
    # reported as path + line + type.
    assert ASIA_CANARY not in result.stdout
    assert ASIA_CANARY not in result.stderr
    assert "config/aws_config.py" in result.stdout
    assert "aws_access_key" in result.stdout

    # Every file in the bundle (payload copies, PROMPT.md, EXPOSURE.md,
    # exposure.json, manifest.json): zero occurrences of the canary.
    texts = read_all_text(bundle)
    offenders = [rel for rel, text in texts.items() if ASIA_CANARY in text]
    assert offenders == [], f"ASIA canary shipped in: {offenders}"

    # The exported copy carries the redaction marker instead.
    exported = texts["files/config/aws_config.py"]
    assert "***REDACTED***" in exported

    # The redaction record names file + type, never the value.
    exposure = load_json(find_exposure_json(bundle))
    hits = [r for r in exposure["redactions"]
            if r["path"] == "config/aws_config.py"]
    assert hits and all(r["type"] == "aws_access_key" for r in hits), hits

    # The bundle still verifies clean after redaction.
    v = cli(["verify", bundle])
    assert v.returncode == 0, f"verify failed:\n{v.stdout}\n{v.stderr}"
    assert ASIA_CANARY not in v.stdout

    # The source project is never altered.
    source = (project / "config" / "aws_config.py").read_text(encoding="utf-8")
    assert ASIA_CANARY in source
