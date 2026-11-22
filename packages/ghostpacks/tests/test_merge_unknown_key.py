"""Merge validation tests (PLAN.md Verification bar: Safety test).

A profile fragment carrying an unknown top-level key must fail the
merge, the error must name the key (Slice profile discipline: unknown
keys fail loudly, never silently ignored), and the failed merge must
leave the project profile and lockfile untouched.
"""
from __future__ import annotations

import json

from conftest import combined, merge

BOGUS_KEY = "bogus_pack_key_xyz"


def test_merge_with_unknown_profile_key_fails_and_names_it(pack_factory, project_factory):
    pack = pack_factory(fragment={
        "ignore": [],
        "modes": {},
        BOGUS_KEY: True,
    })
    project = project_factory()
    proc = merge(pack, project)
    out = combined(proc)
    assert proc.returncode != 0, "merge accepted a fragment with an unknown key"
    assert BOGUS_KEY in out, f"merge error must name the unknown key:\n{out}"


def test_failed_merge_leaves_project_untouched(pack_factory, project_factory):
    pack = pack_factory(fragment={BOGUS_KEY: "nope"})
    project = project_factory()
    before = (project / ".ghostslice.json").read_bytes()
    proc = merge(pack, project)
    assert proc.returncode != 0
    assert (project / ".ghostslice.json").read_bytes() == before, (
        "a failed merge modified the project profile")
    lockfile = project / ".ghostslice-packs.json"
    if lockfile.exists():
        entries = json.loads(lockfile.read_text())
        recorded = entries if isinstance(entries, list) else entries.get("packs", [])
        assert all(e.get("id") != "demo-python" for e in recorded), (
            "a failed merge was still recorded in the lockfile")


def test_merge_with_only_known_keys_succeeds(pack_factory, project_factory):
    pack = pack_factory(fragment={
        "ignore": ["generated/**"],
        "modes": {"src/**": "signatures"},
        "budget_tokens": 50000,
    })
    project = project_factory()
    proc = merge(pack, project)
    assert proc.returncode == 0, combined(proc)
    merged = json.loads((project / ".ghostslice.json").read_text())
    assert merged["modes"].get("src/**") == "signatures"
    assert "generated/**" in merged.get("ignore", [])


def test_successful_merge_records_lockfile_provenance(pack_factory, project_factory):
    pack = pack_factory()
    project = project_factory()
    proc = merge(pack, project)
    assert proc.returncode == 0, combined(proc)
    lockfile = project / ".ghostslice-packs.json"
    assert lockfile.exists(), "merge did not write the .ghostslice-packs.json lockfile"
    text = lockfile.read_text()
    data = json.loads(text)
    entries = data if isinstance(data, list) else data.get("packs", data)
    blob = json.dumps(entries)
    assert "demo-python" in blob and "0.1.0" in blob, (
        f"lockfile should record pack id and version:\n{text}")


def test_merge_declined_at_preview_leaves_project_untouched(pack_factory, project_factory):
    # PLAN.md: merge previews a full diff and requires an explicit yes.
    pack = pack_factory()
    project = project_factory()
    before = (project / ".ghostslice.json").read_bytes()
    proc = merge(pack, project, answer="n\n")
    assert (project / ".ghostslice.json").read_bytes() == before, (
        "merge applied changes after the user answered no at the preview")
