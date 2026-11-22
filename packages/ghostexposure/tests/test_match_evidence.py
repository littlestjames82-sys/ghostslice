"""Deepen tests: line-level match evidence and pattern coverage.

Before this change a partition record said *which* pattern fired for a
file but not *where* in the source text it fired, and a bundle recorded
nothing about patterns that matched no file at all. Both are evidence
gaps: a receiver could not spot-check a recorded reason, and a pack
pattern that silently matched nothing was invisible in the bundle.

The added evidence is factual only: line numbers recorded from the
sender's source text, per-pattern lists of matched files (including
empty lists), and a verify check that the recorded coverage agrees
with the recorded partition. No decision changes: the partition for a
given tree and pack is exactly the partition built before.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ghostexposure.inventory import build_inventory  # noqa: E402
from ghostexposure.partition import (  # noqa: E402
    MAX_EVIDENCE_LINES,
    build_partition,
    pattern_coverage,
)
from ghostexposure.surface import load_pack  # noqa: E402

from conftest import FIXTURES, copy_fixture  # noqa: E402
from helpers import find_exposure_json, load_json  # noqa: E402

BASIC = FIXTURES / "basic_project"


def _partition():
    pack = load_pack(FIXTURES / "surfaces" / "starter-surface.json")
    entries = build_inventory(BASIC)
    pins = {"pinned_in": [], "pinned_out": [], "surface": None}
    return build_partition(entries, pack, pins), pack


def _reasons_for(partition, path, pattern_id):
    entry = next(d for d in partition if d["path"] == path)
    return [r for r in entry["reasons"] if r.get("pattern_id") == pattern_id]


# --- line-level evidence ---------------------------------------------


def test_text_pattern_hits_record_matching_lines():
    partition, _ = _partition()
    hits = _reasons_for(partition, "auth/login.py", "symbol-login")
    assert len(hits) == 1
    hit = hits[0]
    source_lines = (BASIC / "auth" / "login.py").read_text(
        encoding="utf-8").splitlines()
    # Every recorded line actually contains a symbol-login match, and
    # the lines the pattern fires on are all recorded.
    import re
    expected = [n for n, line in enumerate(source_lines, 1)
                if re.search(r"login|authenticate|verify_password", line)]
    assert expected, "fixture sanity: symbol-login must fire in login.py"
    assert hit["lines"] == expected
    assert hit["line_count"] == len(expected)
    assert hit["occurrences"] >= len(expected)
    assert hit["lines_truncated"] is False


def test_data_pattern_records_its_line():
    partition, _ = _partition()
    hits = _reasons_for(partition, "auth/login.py", "data-personal")
    assert len(hits) == 1
    # password_hash occurs on the `if user and verify_password(...)` line.
    source = (BASIC / "auth" / "login.py").read_text(encoding="utf-8")
    expected_line = next(
        n for n, line in enumerate(source.splitlines(), 1)
        if "password_hash" in line)
    assert hits[0]["lines"] == [expected_line]


def test_glob_hits_record_no_lines():
    partition, _ = _partition()
    hits = _reasons_for(partition, "auth/login.py", "glob-auth")
    assert len(hits) == 1
    # A glob matches the path, not a line: recorded as such, not faked.
    assert hits[0]["lines"] == []
    assert hits[0]["line_count"] == 0
    assert hits[0]["occurrences"] == 0


def test_non_matching_file_carries_no_line_evidence():
    partition, _ = _partition()
    entry = next(d for d in partition if d["path"] == "util/format.py")
    assert entry["decision"] == "out"
    assert entry["reasons"] == []


def test_line_evidence_is_capped_but_counts_are_full():
    pack = load_pack(FIXTURES / "surfaces" / "starter-surface.json")
    text = "\n".join("login  # filler" for _ in range(60)) + "\n"
    entry = {"path": "many.py", "size": len(text),
             "sha256": "0" * 64, "is_text": True, "text": text}
    pins = {"pinned_in": [], "pinned_out": [], "surface": None}
    partition = build_partition([entry], pack, pins)
    hits = _reasons_for(partition, "many.py", "symbol-login")
    assert len(hits) == 1
    assert hits[0]["line_count"] == 60
    assert hits[0]["occurrences"] == 60
    assert len(hits[0]["lines"]) == MAX_EVIDENCE_LINES
    assert hits[0]["lines_truncated"] is True


# --- pattern coverage -------------------------------------------------


def test_pattern_coverage_covers_every_pack_pattern():
    partition, pack = _partition()
    coverage = pattern_coverage(partition, pack)
    assert [c["pattern_id"] for c in coverage] == [
        p["id"] for p in pack["patterns"]]
    by_id = {c["pattern_id"]: c for c in coverage}
    assert by_id["glob-auth"]["matched_files"] == ["auth/login.py"]
    assert by_id["import-stripe"]["matched_file_count"] == 1
    assert by_id["import-stripe"]["matched_files"] == ["payments/charge.py"]
    # import-stripe fires on the import line and the stripe.Charge line.
    assert by_id["import-stripe"]["total_line_hits"] == 2


def test_pattern_coverage_records_zero_match_patterns():
    partition, pack = _partition()
    by_id = {c["pattern_id"]: c for c in pattern_coverage(partition, pack)}
    # The basic fixture has no config/ tree, so glob-config matched
    # nothing. That outcome is recorded, with empty evidence.
    assert by_id["glob-config"]["matched_files"] == []
    assert by_id["glob-config"]["matched_file_count"] == 0
    assert by_id["glob-config"]["total_line_hits"] == 0
    assert by_id["glob-config"]["total_occurrences"] == 0


def test_pattern_coverage_agrees_with_partition_reasons():
    partition, pack = _partition()
    for cov in pattern_coverage(partition, pack):
        from_partition = sorted(
            d["path"] for d in partition
            if any(r.get("pattern_id") == cov["pattern_id"]
                   for r in d["reasons"]))
        assert sorted(cov["matched_files"]) == from_partition


# --- exported bundle ---------------------------------------------------


def _export(cli, project, pack, out):
    result = cli(["export", project, "--surface", pack, "-o", out])
    assert result.returncode == 0, (
        f"export failed:\n{result.stdout}\n{result.stderr}")
    return out


def test_export_records_coverage_and_line_evidence(
        cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    exposure = load_json(find_exposure_json(bundle))
    assert "pattern_coverage" in exposure
    by_id = {c["pattern_id"]: c for c in exposure["pattern_coverage"]}
    assert set(by_id) == {p["id"] for p in exposure["surface_pack"]["patterns"]}
    assert by_id["glob-config"]["matched_files"] == []
    assert "payments/charge.py" in by_id["import-stripe"]["matched_files"]
    # Line evidence travelled into the recorded partition too.
    login = next(d for d in exposure["partition"]
                 if d["path"] == "auth/login.py")
    symbol_hit = next(r for r in login["reasons"]
                      if r.get("pattern_id") == "symbol-login")
    assert symbol_hit["lines"] and symbol_hit["line_count"] == len(
        symbol_hit["lines"])
    md = (bundle / "EXPOSURE.md").read_text(encoding="utf-8")
    assert "Pattern coverage" in md
    assert "glob-config" in md
    assert "no matches recorded" in md
    # The fresh bundle, coverage included, verifies clean.
    v = cli(["verify", bundle])
    assert v.returncode == 0, f"verify failed:\n{v.stdout}\n{v.stderr}"


def test_scan_json_includes_coverage_and_lines(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    result = cli(["scan", project, "--surface", surface_pack, "--json"])
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert "pattern_coverage" in data
    by_id = {c["pattern_id"]: c for c in data["pattern_coverage"]}
    assert by_id["glob-config"]["matched_file_count"] == 0
    login = next(d for d in data["partition"] if d["path"] == "auth/login.py")
    assert any(r.get("lines") for r in login["reasons"])


def test_scan_text_prints_pattern_coverage(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    result = cli(["scan", project, "--surface", surface_pack])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Pattern coverage:" in result.stdout
    assert "glob-config: no files matched" in result.stdout


# --- verify guards the coverage record ---------------------------------


def test_verify_fails_when_coverage_is_tampered(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    tampered = tmp_path / "tampered-coverage"
    shutil.copytree(bundle, tampered)
    path = find_exposure_json(tampered)
    exposure = load_json(path)
    for cov in exposure["pattern_coverage"]:
        if cov["pattern_id"] == "glob-auth":
            cov["matched_files"] = ["util/format.py"]
            cov["matched_file_count"] = 1
    path.write_text(json.dumps(exposure, indent=2) + "\n", encoding="utf-8")
    result = cli(["verify", tampered])
    assert result.returncode != 0
    assert "glob-auth" in (result.stdout + result.stderr)


def test_verify_fails_when_coverage_entry_is_removed(
        cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    tampered = tmp_path / "tampered-missing"
    shutil.copytree(bundle, tampered)
    path = find_exposure_json(tampered)
    exposure = load_json(path)
    exposure["pattern_coverage"] = [
        c for c in exposure["pattern_coverage"]
        if c["pattern_id"] != "import-stripe"]
    path.write_text(json.dumps(exposure, indent=2) + "\n", encoding="utf-8")
    result = cli(["verify", tampered])
    assert result.returncode != 0
    assert "import-stripe" in (result.stdout + result.stderr)


def test_verify_accepts_bundle_without_coverage_record(
        cli, surface_pack, tmp_path):
    """Bundles written before coverage recording carry no such key;
    verify does not fail them for its absence."""
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    legacy = tmp_path / "legacy-bundle"
    shutil.copytree(bundle, legacy)
    path = find_exposure_json(legacy)
    exposure = load_json(path)
    del exposure["pattern_coverage"]
    path.write_text(json.dumps(exposure, indent=2) + "\n", encoding="utf-8")
    result = cli(["verify", legacy])
    assert result.returncode == 0, (
        f"legacy bundle must verify:\n{result.stdout}\n{result.stderr}")
