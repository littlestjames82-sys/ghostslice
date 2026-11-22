"""Python pack contract: gaps land in the right sections, pins exact."""
from __future__ import annotations

import json

from conftest import combined, needs_cli, run_pack
from helpers import banned_hits, section_bodies


@needs_cli
def test_python_pack_places_gaps_in_right_sections(python_gap_project,
                                                   tmp_path):
    proc, found = run_pack(python_gap_project, tmp_path / "out")
    # Findings present (numpy imported, not declared): exit 1, as doctor.
    assert proc.returncode == 1, combined(proc)
    assert found is not None, "pack produced no DEPS.md + deps-manifest.json"
    deps_md, _ = found
    bodies = section_bodies(deps_md.read_text())
    for key in ("declared_and_used", "declared_not_imported",
                "imported_not_declared", "pins"):
        assert key in bodies, f"DEPS.md is missing the {key} section"

    used = bodies["declared_and_used"].lower()
    assert "requests" in used
    # PIL is the import name; the distribution is Pillow (built-in map).
    assert "pillow" in used or "pil" in used

    not_imported = bodies["declared_not_imported"].lower()
    assert "colorama" in not_imported
    # The wording rule: evidence phrasing, never a removal verdict.
    assert "no import found" in not_imported

    not_declared = bodies["imported_not_declared"].lower()
    assert "numpy" in not_declared
    assert "app.py" in not_declared, (
        "imported-not-declared must name the importing files as evidence")

    # Stdlib and local modules are classified separately, never gaps.
    assert "numpy" not in not_imported
    assert "colorama" not in not_declared
    for section in (not_imported, not_declared):
        assert "\nos\n" not in "\n" + section, "stdlib leaked into a gap section"
    assert "helper" not in not_declared, "local module flagged as undeclared"


@needs_cli
def test_python_pins_match_requirements_exactly(python_gap_project, tmp_path):
    proc, found = run_pack(python_gap_project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)
    assert found is not None
    deps_md, manifest = found
    bodies = section_bodies(deps_md.read_text())
    pins = bodies.get("pins", "")
    # Exact strings from the fixture requirements.txt.
    assert "2.31.0" in pins, "requests pin from requirements.txt missing"
    assert "10.2.0" in pins, "Pillow pin from requirements.txt missing"
    assert "0.4.6" in pins, "colorama pin from requirements.txt missing"
    manifest_text = manifest.read_text()
    assert "2.31.0" in manifest_text
    data = json.loads(manifest_text)
    assert isinstance(data, dict) and data, "manifest JSON is empty"


@needs_cli
def test_python_pack_has_no_verdict_wording(python_gap_project, tmp_path):
    proc, found = run_pack(python_gap_project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)
    assert found is not None
    deps_md, manifest = found
    hits = banned_hits(deps_md.read_text(), manifest.read_text(),
                       combined(proc))
    assert hits == [], f"verdict wording in pack output: {hits}"


@needs_cli
def test_clean_project_pack_is_quiet(clean_project, tmp_path):
    proc, found = run_pack(clean_project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    assert found is not None
    deps_md, _ = found
    bodies = section_bodies(deps_md.read_text())
    assert "imported_not_declared" in bodies
    section = bodies["imported_not_declared"].lower()
    assert "requests" not in section, (
        "a declared-and-imported package appeared as not declared")
    assert "declared_not_imported" in bodies
    assert "requests" not in bodies["declared_not_imported"].lower()
