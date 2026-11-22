"""Redaction hard rules (PLAN.md MVP 3 and verification bar).

- Sensitive columns are redacted by default, by name and by value
  shape.
- No planted sensitive value appears in ANY output file or in command
  output (every file in the pack tree is scanned, plus stdout).
- Redacted columns show [REDACTED] in the sample, are named in the
  manifest with the reason only, and have min/max suppressed.
"""
from __future__ import annotations

from pathlib import Path

from conftest import (assert_no_canaries_in_text,
                      assert_no_canaries_in_tree, column, requires_core,
                      run_cli, run_pack, run_schema)

EXPECTED_REDACTED = {
    # column: substring expected in its recorded reason
    "email": "email",          # name match
    "password_hash": "password",  # name match
    "contact": "email",        # shape match (values are emails)
    "payment": "card",         # shape match (Luhn-valid values)
    "ref": "ssn",              # shape match (SSN-shaped values)
}


@requires_core
def test_people_pack_contains_no_planted_values(people_csv, tmp_path):
    proc, manifest = run_pack(people_csv, tmp_path / "pack")
    assert_no_canaries_in_tree(
        tmp_path / "pack", extra_texts=[proc.stdout, proc.stderr])


@requires_core
def test_people_schema_output_contains_no_planted_values(people_csv):
    proc = run_cli(["schema", people_csv])
    assert proc.returncode == 0, proc.stderr
    assert_no_canaries_in_text(proc.stdout, "schema stdout")
    assert_no_canaries_in_text(proc.stderr, "schema stderr")


@requires_core
def test_events_pack_contains_no_planted_token(events_jsonl, tmp_path):
    proc, manifest = run_pack(events_jsonl, tmp_path / "pack")
    assert_no_canaries_in_tree(
        tmp_path / "pack", extra_texts=[proc.stdout, proc.stderr])
    names = {c["name"] for c in manifest["redaction"]["columns"]}
    assert "api_token" in names


@requires_core
def test_redaction_record_names_columns_with_reasons(
        people_csv, tmp_path):
    proc, manifest = run_pack(people_csv, tmp_path / "pack")
    assert manifest["redaction"]["enabled"] is True
    recorded = {c["name"]: c["reason"]
                for c in manifest["redaction"]["columns"]}
    assert set(recorded) == set(EXPECTED_REDACTED)
    for name, needle in EXPECTED_REDACTED.items():
        assert needle in recorded[name].lower(), (name, recorded[name])
        col = column(manifest, name)
        assert col["redacted"] is True
        # min and max are suppressed for redacted columns
        assert col["min"] is None and col["max"] is None
    # an ordinary column is not redacted
    assert column(manifest, "name")["redacted"] is False


@requires_core
def test_sample_shows_redacted_marker_not_values(people_csv, tmp_path):
    proc, manifest = run_pack(people_csv, tmp_path / "pack")
    sample_text = (tmp_path / "pack" / manifest["sample"]["file"]).read_text(
        encoding="utf-8")
    assert "[REDACTED]" in sample_text
    # the non-sensitive rows are still there and readable
    assert "Alice" in sample_text and "Eve" in sample_text
    prompt_text = (tmp_path / "pack" / "PROMPT.md").read_text(
        encoding="utf-8")
    assert "[REDACTED]" in prompt_text


@requires_core
def test_schema_marks_redacted_columns(people_csv):
    out = run_schema(people_csv)
    for name in EXPECTED_REDACTED:
        col = column(out, name)
        assert col["redacted"] is True, name
        assert col["min"] is None and col["max"] is None
    recorded = {c["name"] for c in out["redacted_columns"]}
    assert recorded == set(EXPECTED_REDACTED)


@requires_core
def test_no_redact_flag_is_explicit_and_recorded(people_csv, tmp_path):
    proc, manifest = run_pack(
        people_csv, tmp_path / "pack", "--no-redact")
    assert manifest["redaction"]["enabled"] is False
    assert manifest["redaction"]["columns"] == []
    sample_text = Path(
        tmp_path / "pack" / manifest["sample"]["file"]).read_text(
        encoding="utf-8")
    # with the explicit opt-out the owner sees their own values; the
    # manifest is what records that this was a deliberate choice
    assert "alice@canary.invalid" in sample_text
    assert "[REDACTED]" not in sample_text
