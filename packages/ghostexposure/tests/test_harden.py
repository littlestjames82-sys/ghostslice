"""Hardening regression tests (Oct 18, 2026 improvement wave, lane: harden).

Each test proves one fix for a real bug found by probing edge cases:
CRLF redaction drift, overlapping redaction spans, truncated-PEM
over-redaction, inventory symlink / special-file handling, surface
pack validation, profile pin normalisation, verify robustness against
corrupt bundles, export output-path handling, and signatures fidelity.

All secret-shaped literals below are FAKE, test-only strings.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ghostexposure.exporter import ExportError, export_bundle, signatures_source, verify_bundle  # noqa: E402
from ghostexposure.inventory import build_inventory  # noqa: E402
from ghostexposure.partition import load_profile_pins  # noqa: E402
from ghostexposure.secrets import find_literals, redact_text  # noqa: E402
from ghostexposure.surface import SurfaceError, load_pack  # noqa: E402

FAKE_VALUE = "supersecretvalue123"


# --- secrets: CRLF offsets --------------------------------------------


def test_redaction_span_is_exact_on_crlf_file():
    text = f'x = 1\r\npassword = "{FAKE_VALUE}"\r\ny = 2\r\n'
    findings = find_literals(text)
    assert len(findings) == 1
    f = findings[0]
    assert text[f["start"]:f["end"]] == FAKE_VALUE
    out = redact_text(text, findings)
    assert FAKE_VALUE not in out
    # No tail of the literal and no collateral damage to the line.
    assert out == 'x = 1\r\npassword = "***REDACTED***"\r\ny = 2\r\n'


def test_redaction_does_not_drift_after_many_crlf_lines():
    text = "\r\n".join(["# comment"] * 5) + "\r\n" \
        + f'password = "{FAKE_VALUE}"' + "\r\n"
    findings = find_literals(text)
    assert len(findings) == 1
    out = redact_text(text, findings)
    assert FAKE_VALUE not in out
    assert "value123" not in out and "ecret" not in out
    assert "password" in out  # the assignment name itself survives
    assert out.count("# comment") == 5


# --- secrets: overlapping findings -------------------------------------


def test_nested_findings_redact_the_whole_value():
    # The password-in-URL span is nested inside the generic-assignment
    # span for the same value. Redacting both with stale offsets left
    # a trailing character of the value behind.
    text = 'api_key = "https://user:password12345@example.com/x"\n'
    out = redact_text(text, find_literals(text))
    assert "password12345" not in out
    assert out == 'api_key = "***REDACTED***"\n'


def test_redact_text_merges_partial_overlaps_directly():
    text = "0123456789abcdefghij"
    findings = [{"line": 1, "type": "a", "start": 2, "end": 12},
                {"line": 1, "type": "b", "start": 8, "end": 18}]
    assert redact_text(text, findings) == "01***REDACTED***ij"


# --- secrets: truncated PEM must not swallow following code ------------


def test_truncated_pem_does_not_swallow_following_code():
    body = "QUJDREVGRw0123456789"
    text = ("-----BEGIN PRIVATE KEY-----\n"
            f"{body}\n"
            "x = compute_something()\n"
            "y = other_code()\n"
            "-----END SOMETHING PRIVATE KEY-----\n")
    out = redact_text(text, find_literals(text))
    assert body not in out
    assert "x = compute_something()" in out
    assert "y = other_code()" in out


def test_complete_pem_block_still_redacted_whole():
    text = ("-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA12345678\n"
            "abcdEFGH12345678ijklMNOP\n"
            "-----END RSA PRIVATE KEY-----\n"
            "after = 1\n")
    out = redact_text(text, find_literals(text))
    assert "MIIEowIBAAKCAQEA12345678" not in out
    assert "END RSA PRIVATE KEY" not in out
    assert "after = 1" in out


# --- inventory: symlinks and special files fail closed -----------------


def _project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "ok.py").write_text("x = 1\n", encoding="utf-8")
    return proj


def test_inventory_broken_symlink_is_a_named_error(tmp_path):
    proj = _project(tmp_path)
    os.symlink("/nonexistent/target.py", proj / "broken.py")
    with pytest.raises(ValueError, match="broken"):
        build_inventory(proj)


def test_inventory_symlink_to_outside_file_is_refused(tmp_path):
    proj = _project(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside data\n", encoding="utf-8")
    os.symlink(outside, proj / "link.txt")
    with pytest.raises(ValueError, match="outside"):
        build_inventory(proj)
    # And its content must never have been inventoried for export.
    with pytest.raises(ValueError):
        build_inventory(proj)


def test_inventory_internal_symlink_still_works(tmp_path):
    proj = _project(tmp_path)
    os.symlink(proj / "ok.py", proj / "alias.py")
    entries = build_inventory(proj)
    assert {e["path"] for e in entries} == {"ok.py", "alias.py"}


def test_inventory_symlinked_dir_to_outside_is_refused(tmp_path):
    proj = _project(tmp_path)
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "hidden.py").write_text("y = 2\n", encoding="utf-8")
    os.symlink(outside_dir, proj / "linkeddir")
    with pytest.raises(ValueError, match="outside"):
        build_inventory(proj)


def test_inventory_fifo_is_a_named_error_not_a_hang(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("no mkfifo on this platform")
    proj = _project(tmp_path)
    os.mkfifo(proj / "pipe")
    with pytest.raises(ValueError, match="regular file"):
        build_inventory(proj)


# --- surface pack validation -------------------------------------------


def _write_pack(tmp_path: Path, raw: str) -> Path:
    p = tmp_path / "pack.json"
    p.write_text(raw, encoding="utf-8")
    return p


def test_pack_top_level_must_be_an_object(tmp_path):
    with pytest.raises(SurfaceError):
        load_pack(_write_pack(tmp_path, "[1, 2, 3]"))
    with pytest.raises(SurfaceError):
        load_pack(_write_pack(tmp_path, '"just a string"'))


def test_pack_patterns_must_be_a_list_of_objects(tmp_path):
    base = {"id": "x", "version": "1", "date": "2026-01-01",
            "description": "d", "coverage_limits": []}
    with pytest.raises(SurfaceError):
        load_pack(_write_pack(tmp_path, json.dumps(
            {**base, "patterns": "notalist"})))
    with pytest.raises(SurfaceError):
        load_pack(_write_pack(tmp_path, json.dumps(
            {**base, "patterns": [123]})))


def test_pack_pattern_fields_must_be_strings(tmp_path):
    pack = {"id": "x", "version": "1", "date": "2026-01-01",
            "description": "d", "coverage_limits": [],
            "patterns": [{"id": "p", "kind": "glob", "pattern": 123,
                          "reason": "r"}]}
    with pytest.raises(SurfaceError):
        load_pack(_write_pack(tmp_path, json.dumps(pack)))


def test_pack_invalid_utf8_is_a_surface_error(tmp_path):
    p = tmp_path / "pack.json"
    p.write_bytes(b"\xff\xfe{")
    with pytest.raises(SurfaceError):
        load_pack(p)


def test_pack_directory_path_is_a_surface_error(tmp_path):
    with pytest.raises(SurfaceError):
        load_pack(tmp_path)


# --- profile pins -------------------------------------------------------


def _write_profile(tmp_path: Path, raw: str) -> Path:
    (tmp_path / ".ghostslice.json").write_text(raw, encoding="utf-8")
    return tmp_path


def test_profile_top_level_non_object_does_not_crash(tmp_path):
    assert load_profile_pins(_write_profile(tmp_path, "[]")) == {
        "pinned_in": [], "pinned_out": [], "surface": None}
    assert load_profile_pins(_write_profile(tmp_path, '"hello"')) == {
        "pinned_in": [], "pinned_out": [], "surface": None}


def test_profile_string_pin_is_one_glob_not_characters(tmp_path):
    # list("auth/**") produced single-character globs, and the "*"
    # character alone matches every file in the tree.
    pins = load_profile_pins(_write_profile(
        tmp_path, '{"exposure": {"pinned_in": "auth/**"}}'))
    assert pins["pinned_in"] == ["auth/**"]


def test_profile_non_string_pin_entries_are_ignored(tmp_path):
    pins = load_profile_pins(_write_profile(
        tmp_path,
        '{"exposure": {"pinned_in": 123, "pinned_out": ["a", 123, null]}}'))
    assert pins["pinned_in"] == []
    assert pins["pinned_out"] == ["a"]


# --- verify: corrupt bundles are named problems, not crashes -----------


def _bundle_dir(tmp_path: Path, manifest: str, exposure: str) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(manifest, encoding="utf-8")
    (bundle / "exposure.json").write_text(exposure, encoding="utf-8")
    (bundle / "EXPOSURE.md").write_text(
        "Coverage limits: stated. It cannot prove anything else.\n",
        encoding="utf-8")
    return bundle


def test_verify_invalid_json_returns_problems(tmp_path):
    bundle = _bundle_dir(tmp_path, "not json", "{}")
    ok, problems, _notes = verify_bundle(bundle)
    assert ok is False
    assert any("manifest.json is not valid JSON" in p for p in problems)


def test_verify_entry_missing_sha256_returns_problems(tmp_path):
    exposure = json.dumps({
        "partition": [{"path": "a.py", "decision": "surface"}],
        "inventory_file_count": 1, "inventory_hash": "x"})
    bundle = _bundle_dir(
        tmp_path, json.dumps({"files": [{"path": "a.py"}]}), exposure)
    ok, problems, _notes = verify_bundle(bundle)
    assert ok is False
    assert any("missing a path or sha256" in p for p in problems)


def test_verify_duplicate_manifest_entry_is_flagged(tmp_path):
    sha = "0" * 64
    manifest = json.dumps({"files": [
        {"path": "a.py", "sha256": sha}, {"path": "a.py", "sha256": sha}]})
    exposure = json.dumps({
        "partition": [{"path": "a.py", "sha256": sha,
                       "decision": "surface"}],
        "inventory_file_count": 1, "inventory_hash": "bad"})
    bundle = _bundle_dir(tmp_path, manifest, exposure)
    (bundle / "files").mkdir()
    (bundle / "files" / "a.py").write_text("hi\n", encoding="utf-8")
    ok, problems, _notes = verify_bundle(bundle)
    assert ok is False
    assert any("more than once" in p for p in problems)


def test_verify_corrupt_bundle_via_cli_names_problem_no_traceback(
        cli, tmp_path):
    bundle = _bundle_dir(tmp_path, "not json", "{}")
    result = cli(["verify", bundle])
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "not valid JSON" in result.stdout
    assert "Traceback" not in result.stderr


# --- export: output path handling --------------------------------------


def test_export_output_path_that_is_a_file_is_an_export_error(
        tmp_path, surface_pack):
    proj = _project(tmp_path)
    out_file = tmp_path / "outfile"
    out_file.write_text("occupied\n", encoding="utf-8")
    pack = load_pack(surface_pack)
    with pytest.raises(ExportError, match="not a folder"):
        export_bundle(proj, out_file, pack)


# --- signatures fidelity -------------------------------------------------


def test_signatures_preserve_async_and_return_annotations():
    src = ("async def fetch(url: str) -> bytes:\n"
           "    return b''\n"
           "class Client:\n"
           "    async def get(self) -> int:\n"
           "        return 1\n")
    out = signatures_source(src)
    assert "async def fetch(url: str) -> bytes:" in out
    assert "async def get(self) -> int: ..." in out


def test_signatures_keep_annotated_assignments():
    out = signatures_source("count: int = 5\nname: str\n")
    assert "count: int = ..." in out
    assert "name: str" in out
