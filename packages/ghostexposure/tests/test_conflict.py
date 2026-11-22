"""Conflict rule (PLAN.md MVP #1): a file matched by a sensitive pattern
AND a user pin-out is a conflict requiring a human decision. It must
never be resolved silently."""
from __future__ import annotations

import json
from pathlib import Path

from conftest import copy_fixture
from helpers import find_exposure_json, get_partition, load_json


def test_scan_reports_the_conflict(cli, surface_pack, tmp_path):
    project = copy_fixture("conflict_project", tmp_path)
    result = cli(["scan", project, "--surface", surface_pack])
    combined = (result.stdout + result.stderr).lower()

    named_in_output = "session.py" in combined and "conflict" in combined
    named_in_file = False
    for candidate in project.rglob("*.json"):
        try:
            data = json.loads(candidate.read_text())
        except (ValueError, UnicodeDecodeError):
            continue
        _, _, conflicts = get_partition(data)
        if "auth/session.py" in conflicts:
            named_in_file = True
    assert named_in_output or named_in_file, (
        "scan must list auth/session.py as a conflict (pattern match + user pin-out)"
    )


def test_export_does_not_silently_resolve_the_conflict(cli, surface_pack, tmp_path):
    project = copy_fixture("conflict_project", tmp_path)
    out = tmp_path / "bundle"
    result = cli(["export", project, "--surface", surface_pack, "-o", out])

    if result.returncode != 0:
        # Refusing to export an unresolved conflict is a correct outcome,
        # as long as it says what the conflict is.
        assert "session.py" in (result.stdout + result.stderr)
        return

    exposure = load_json(find_exposure_json(out))
    in_set, out_set, conflict_set = get_partition(exposure)
    assert "auth/session.py" in conflict_set, (
        "export succeeded but decided auth/session.py "
        f"(in={in_set}, out={out_set}) with no conflict marker: silent resolution"
    )
