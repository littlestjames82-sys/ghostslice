"""Verification bar #1 (PLAN.md): on a fixture tree, in + out equals the
inventory exactly. Zero unaccounted, zero double-counted."""
from __future__ import annotations

from pathlib import Path

from conftest import copy_fixture
from helpers import bundle_payload_files, find_exposure_json, get_partition, inventory, load_json


def _export(cli, project: Path, pack: Path, out: Path):
    result = cli(["export", project, "--surface", pack, "-o", out])
    assert result.returncode == 0, f"export failed:\n{result.stdout}\n{result.stderr}"
    return out


def test_partition_completeness(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    exposure = load_json(find_exposure_json(bundle))
    in_set, out_set, conflict_set = get_partition(exposure)

    inv = inventory(project)
    assert conflict_set == set(), f"basic fixture has no conflicts, got {conflict_set}"
    assert in_set & out_set == set(), f"double-counted files: {in_set & out_set}"
    assert in_set | out_set == inv, (
        f"partition must account for every file.\n"
        f"unaccounted: {sorted(inv - in_set - out_set)}\n"
        f"not in inventory: {sorted((in_set | out_set) - inv)}"
    )


def test_partition_decisions_match_the_surface(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    exposure = load_json(find_exposure_json(bundle))
    in_set, out_set, _ = get_partition(exposure)

    assert "auth/login.py" in in_set, "auth glob must put login.py in the surface"
    assert "payments/charge.py" in in_set, "payments glob / stripe import must put charge.py in"
    assert "util/format.py" in out_set, "unrelated helper has no signal and must be out"
    assert "docs/guide.md" in out_set


def test_bundle_payload_matches_partition(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    exposure = load_json(find_exposure_json(bundle))
    in_set, out_set, _ = get_partition(exposure)
    payload = bundle_payload_files(bundle)

    leaked = payload & out_set
    assert leaked == set(), f"OUT files were shipped in the bundle: {leaked}"
    # Surface files (not just graph context) must actually be present.
    for surface_file in ("auth/login.py", "payments/charge.py"):
        assert surface_file in payload, f"surface file {surface_file} missing from bundle payload"
