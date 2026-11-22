"""Merge/remove round-trip tests (PLAN.md Verification bar).

Merge a pack into a fixture project, export with the real GhostSlice,
remove the pack, export again: the second export's manifest totals
must match the pre-merge totals exactly, and the project profile must
be restored. Removal after the user has edited the merged profile
must be reported as not cleanly reversible instead of overwriting
the user's edit.
"""
from __future__ import annotations

import json

import pytest

from conftest import (combined, export_totals, ghostslice_available,
                      merge, remove)

pytestmark = pytest.mark.skipif(
    not ghostslice_available(),
    reason="GhostSlice checkout not found (set GHOSTSLICE_SRC); "
           "the round-trip needs the real exporter",
)

SIGNATURES_FRAGMENT = {
    "ignore": [],
    "modes": {"src/**": "signatures"},
}


def test_merge_remove_roundtrip_restores_export_totals(
        pack_factory, project_factory, tmp_path):
    project = project_factory()
    before_profile = (project / ".ghostslice.json").read_bytes()
    baseline = export_totals(project, tmp_path / "out-before")

    pack = pack_factory(fragment=SIGNATURES_FRAGMENT)
    proc = merge(pack, project)
    assert proc.returncode == 0, combined(proc)
    assert (project / ".ghostslice.json").read_bytes() != before_profile, (
        "merge reported success but the profile did not change")

    merged_totals = export_totals(project, tmp_path / "out-merged")
    assert merged_totals["total_sliced_tokens"] <= baseline["total_sliced_tokens"], (
        "a signatures-mode pack should not increase the sliced total: "
        f"baseline={baseline}, merged={merged_totals}")
    assert merged_totals["total_original_tokens"] == baseline["total_original_tokens"]

    proc = remove("demo-python", project)
    assert proc.returncode == 0, combined(proc)

    after = export_totals(project, tmp_path / "out-after")
    assert after == baseline, (
        f"export totals after remove differ from the pre-merge baseline:\n"
        f"baseline={baseline}\nafter={after}")
    restored = json.loads((project / ".ghostslice.json").read_text())
    assert restored == json.loads(before_profile), (
        "profile after remove is not the pre-merge profile")


def test_remove_unmerged_pack_fails_cleanly(pack_factory, project_factory):
    project = project_factory()
    proc = remove("demo-python", project)
    assert proc.returncode != 0, "remove of a never-merged pack reported success"
    assert "demo-python" in combined(proc) or "not" in combined(proc).lower()


def test_remove_after_user_edit_reports_not_clean_and_keeps_edit(
        pack_factory, project_factory):
    pack = pack_factory(fragment=SIGNATURES_FRAGMENT)
    project = project_factory()
    proc = merge(pack, project)
    assert proc.returncode == 0, combined(proc)

    # The user edits the merged profile by hand.
    profile_path = project / ".ghostslice.json"
    edited = json.loads(profile_path.read_text())
    edited["budget_tokens"] = 12345
    profile_path.write_text(json.dumps(edited, indent=2) + "\n")

    proc = remove("demo-python", project)
    out = combined(proc)
    assert proc.returncode != 0, (
        "remove silently overwrote a profile the user edited after merging")
    assert json.loads(profile_path.read_text())["budget_tokens"] == 12345, (
        "remove modified the user's post-merge edit")
    assert out.strip(), "remove should explain why it cannot reverse cleanly"
