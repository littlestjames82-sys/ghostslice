"""Node pack contract: package.json vs parser-lite imports, lock pins."""
from __future__ import annotations

import json

from conftest import combined, needs_cli, run_pack
from helpers import banned_hits, section_bodies


@needs_cli
def test_node_pack_places_gaps_in_right_sections(node_gap_project, tmp_path):
    proc, found = run_pack(node_gap_project, tmp_path / "out")
    # Findings present (axios imported, not declared): exit 1, as doctor.
    assert proc.returncode == 1, combined(proc)
    assert found is not None, "pack produced no DEPS.md + deps-manifest.json"
    deps_md, _ = found
    text = deps_md.read_text()
    bodies = section_bodies(text)
    for key in ("declared_and_used", "declared_not_imported",
                "imported_not_declared", "pins"):
        assert key in bodies, f"DEPS.md is missing the {key} section"

    assert "express" in bodies["declared_and_used"].lower()

    not_imported = bodies["declared_not_imported"].lower()
    assert "lodash" in not_imported
    assert "no import found" in not_imported

    not_declared = bodies["imported_not_declared"].lower()
    assert "axios" in not_declared
    assert "index.js" in not_declared, (
        "imported-not-declared must name the importing files as evidence")

    # The local ./util require is not a package gap.
    assert "util" not in not_declared


@needs_cli
def test_node_pins_match_lockfile_exactly(node_gap_project, tmp_path):
    proc, found = run_pack(node_gap_project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)
    assert found is not None
    deps_md, manifest = found
    bodies = section_bodies(deps_md.read_text())
    pins = bodies.get("pins", "")
    # Exact strings from the fixture package-lock.json.
    assert "4.18.2" in pins, "express lockfile pin missing from pins section"
    assert "4.17.21" in pins, "lodash lockfile pin missing from pins section"
    manifest_text = manifest.read_text()
    assert "4.18.2" in manifest_text and "4.17.21" in manifest_text
    json.loads(manifest_text)  # manifest is valid JSON


@needs_cli
def test_node_pack_is_smaller_than_raw_lockfile(node_gap_project, tmp_path):
    """Plan bar: lockfiles are summarised, never reproduced whole."""
    proc, found = run_pack(node_gap_project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)
    assert found is not None
    deps_md, manifest = found
    lock_size = (node_gap_project / "package-lock.json").stat().st_size
    pack_size = deps_md.stat().st_size + manifest.stat().st_size
    assert pack_size < lock_size, (
        f"pack ({pack_size} bytes) is not smaller than the raw lockfile "
        f"({lock_size} bytes); the lockfile must be summarised, not copied")
    # The lockfile's per-entry payload (integrity hashes, resolved
    # URLs) is summary-level data and must not be reproduced.
    assert "sha512-" not in deps_md.read_text()
    assert "sha512-" not in manifest.read_text()
    assert "registry.invalid" not in deps_md.read_text()


@needs_cli
def test_node_pack_has_no_verdict_wording(node_gap_project, tmp_path):
    proc, found = run_pack(node_gap_project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)
    assert found is not None
    deps_md, manifest = found
    hits = banned_hits(deps_md.read_text(), manifest.read_text(),
                       combined(proc))
    assert hits == [], f"verdict wording in pack output: {hits}"
