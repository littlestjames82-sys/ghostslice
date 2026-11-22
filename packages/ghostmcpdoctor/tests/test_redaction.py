"""Redaction - the non-negotiable of GhostMCP Doctor.

A scanner that prints the secrets it finds would be worse than no
scanner. Env values must be reported as present / absent only: the
key NAME may (and should) be named, the VALUE must never appear in
any output surface - stdout, stderr, JSON output, or a report file
the run writes.

The planted values are FAKE canaries (see fixtures): distinctive
strings that occur nowhere except the fixture env, so any appearance
in output is a leak, full stop.
"""
from conftest import (FAKE_SECRET_CANARIES, copy_fixture, out_text,
                      scan_path)


def _assert_no_canaries(text, where):
    for canary in FAKE_SECRET_CANARIES:
        assert canary not in text, \
            f"fake secret value leaked into {where}: {canary}"


def test_fake_secret_value_never_appears_in_report_output(tmp_path):
    """THE mandated test: scan the messy fixture (text mode) and
    inspect every output surface for the fake secret values."""
    cfg = copy_fixture(tmp_path, "messy")
    proc, combined = scan_path(cfg / "mcp.json", tmp_path)
    _assert_no_canaries(out_text(proc), "stdout/stderr (text mode)")
    _assert_no_canaries(combined, "combined output incl. report files")


def test_fake_secret_value_never_appears_in_json_output(tmp_path):
    cfg = copy_fixture(tmp_path, "messy")
    proc, combined = scan_path(cfg / "mcp.json", tmp_path, want_json=True)
    _assert_no_canaries(out_text(proc), "stdout/stderr (json mode)")
    _assert_no_canaries(combined, "combined output incl. report files (json)")


def test_fake_secret_value_never_appears_when_scanning_a_directory(tmp_path):
    cfg = copy_fixture(tmp_path, "messy")
    proc, combined = scan_path(cfg, tmp_path)
    _assert_no_canaries(combined, "directory scan output")


def test_secret_key_is_reported_as_present_not_shown(tmp_path):
    """Redaction is not silence: the report should still tell the user
    a secret-bearing env var EXISTS for that server - by key name
    and/or a present / redacted marker - just never its value."""
    cfg = copy_fixture(tmp_path, "messy")
    proc, combined = scan_path(cfg / "mcp.json", tmp_path)
    _assert_no_canaries(combined, "combined output")
    text = combined.lower()
    assert "secret-server" in text, "secret-bearing server not in report"
    window = text
    idx = text.find("secret-server")
    near = text[max(0, idx - 900): idx + 1400]
    assert any(tok in near for tok in (
        "fake_api_key", "fake_token", "present", "redacted",
        "set", "env")), \
        "nothing near secret-server says an env secret is present (redacted)"


def test_examples_fake_secrets_never_appear_in_output(tmp_path):
    """Same rule for the shipped example config with FAKE values."""
    from conftest import EXAMPLES
    proc, combined = scan_path(EXAMPLES / "messy.mcp.json", tmp_path)
    assert "FAKE-EXAMPLE-KEY-not-a-real-secret" not in combined
    assert "FAKE-EXAMPLE-TOKEN-not-a-real-secret" not in combined
