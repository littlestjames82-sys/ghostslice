"""CLI build tests (PLAN.md MVP item 1 + verification bar).

Contract pinned here:

- ``ghostfixture build <project> <bundle> -o <out>`` exits 0 and
  writes fixture-manifest.json + FIXTURE.md into the output tree.
- Referenced files are copied as ORIGINALS (byte-identical to
  the source project, not the bundle's sliced text).
- The import closure adds local files the bundle never
  referenced, recursively: main.py pulls helper.py, helper.py
  pulls util_math.py, each recorded as import-closure with its
  importer named.
- Unreferenced files are absent.
- A secret-flagged referenced file is excluded by default,
  named path + pattern types only, and its value appears in no
  byte of the output tree; --include-flagged overrides and the
  flag stays on record.
- A manifest entry at mode ``exclude`` is never copied, even
  when a seed file imports it.
- A referenced file missing from the project is left out with
  reason missing-in-project; the build still succeeds.
- The source project is byte-identical after the run.

All tests skip cleanly while no ghostfixture CLI is discoverable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

pytestmark = pytest.mark.usefixtures("requires_cli")


def _included_paths(manifest):
    return {e["path"] for e in manifest["included"]}


def test_build_succeeds_and_writes_manifest_and_summary(
        repro_project, repro_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    assert (out / "fixture-manifest.json").is_file()
    assert (out / "FIXTURE.md").is_file()
    manifest = helpers.fixture_manifest(out)
    for key in ("task", "source_project", "source_bundle",
                "max_bytes", "totals", "included",
                "excluded_flagged", "left_out",
                "external_references"):
        assert key in manifest, key
    assert manifest["source_bundle_manifest_sha256"]


def test_referenced_files_copied_as_originals(
        repro_project, repro_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    for rel in ("app/main.py", "app/config.py"):
        copied = out / rel
        assert copied.is_file(), rel
        assert copied.read_bytes() == (repro_project / rel).read_bytes()
    manifest = helpers.fixture_manifest(out)
    reasons = {e["path"]: e["reason"] for e in manifest["included"]}
    assert reasons["app/main.py"] == "bundle-referenced"
    assert reasons["app/config.py"] == "bundle-referenced"


def test_import_closure_pulls_two_levels_with_importers(
        repro_project, repro_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    for rel in ("app/helper.py", "app/util_math.py"):
        copied = out / rel
        assert copied.is_file(), rel
        assert copied.read_bytes() == (repro_project / rel).read_bytes()
    manifest = helpers.fixture_manifest(out)
    closure = {e["path"]: e for e in manifest["included"]
               if e["reason"] == "import-closure"}
    assert "app/helper.py" in closure
    assert "app/util_math.py" in closure
    via_helper = str(closure["app/helper.py"].get("via", ""))
    via_util = str(closure["app/util_math.py"].get("via", ""))
    assert "main" in via_helper, closure["app/helper.py"]
    assert "helper" in via_util, closure["app/util_math.py"]


def test_unreferenced_files_are_absent(
        repro_project, repro_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    names = {p.name for p in helpers.output_files(out)}
    assert "unrelated.py" not in names
    assert "notes.txt" not in names
    manifest = helpers.fixture_manifest(out)
    assert "app/unrelated.py" not in _included_paths(manifest)


def test_secret_flagged_file_excluded_and_named_path_and_type_only(
        repro_project, repro_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    assert not (out / helpers.SECRET_FILE).exists()
    manifest = helpers.fixture_manifest(out)
    flagged = {e["path"]: e for e in manifest["excluded_flagged"]}
    assert helpers.SECRET_FILE in flagged, manifest["excluded_flagged"]
    types = flagged[helpers.SECRET_FILE].get("types") or []
    assert types, "flagged entry must name at least one pattern type"
    # The canary value appears in NO byte of the output tree,
    # and not in the CLI output either.
    assert helpers.CANARY.encode() not in helpers.all_output_bytes(out)
    assert helpers.CANARY not in helpers.combined(proc)


def test_include_flagged_override_includes_but_keeps_the_flag(
        repro_project, repro_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(
        repro_project, repro_bundle, out, extra=["--include-flagged"])
    assert proc.returncode == 0, helpers.combined(proc)
    copied = out / helpers.SECRET_FILE
    assert copied.is_file()
    assert copied.read_bytes() == (
        repro_project / helpers.SECRET_FILE).read_bytes()
    manifest = helpers.fixture_manifest(out)
    flagged = {e["path"]: e for e in manifest["excluded_flagged"]}
    assert helpers.SECRET_FILE in flagged
    assert flagged[helpers.SECRET_FILE].get("included_by_override") is True


def test_manifest_exclude_mode_is_never_copied(
        repro_project, tmp_path):
    bundle = helpers.build_bundle(
        repro_project, tmp_path / "bundle_x",
        [("app/main.py", "full"), ("app/config.py", "exclude")])
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    assert not (out / "app/config.py").exists()
    manifest = helpers.fixture_manifest(out)
    assert "app/config.py" not in _included_paths(manifest)


def test_missing_referenced_file_left_out_with_reason(
        repro_project, tmp_path):
    bundle = helpers.build_bundle(
        repro_project, tmp_path / "bundle_m",
        helpers.REPRO_BUNDLE_FILES + [("app/unrelated.py", "full")])
    (repro_project / "app/unrelated.py").unlink()
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    assert not (out / "app/unrelated.py").exists()
    manifest = helpers.fixture_manifest(out)
    left = {e["path"]: e for e in manifest["left_out"]}
    assert left["app/unrelated.py"]["reason"] == "missing-in-project"


def test_source_project_byte_identical_after_build(
        repro_project, repro_bundle, tmp_path):
    before = helpers.tree_hashes(repro_project)
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    after = helpers.tree_hashes(repro_project)
    assert before == after


def test_manifest_totals_match_the_tree(
        repro_project, repro_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(repro_project, repro_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    totals = manifest["totals"]
    assert totals["files_included"] == len(manifest["included"])
    disk_bytes = sum((out / e["path"]).stat().st_size
                     for e in manifest["included"])
    assert totals["bytes_copied"] == disk_bytes
    cap_text = helpers.combined(proc)
    assert "cap" in cap_text.lower()
    assert str(manifest["max_bytes"]) in cap_text
