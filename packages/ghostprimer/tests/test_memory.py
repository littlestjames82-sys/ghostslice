"""Shallow-fallback memory primer: fixed file list, latest changelog only,
provenance on every item, and the path taken recorded in the manifest."""
from __future__ import annotations

import json

from conftest import load_manifest, memory_items


def test_fallback_path_recorded(built_bundle):
    blob = json.dumps(load_manifest(built_bundle)).lower()
    assert "fallback" in blob or "shallow" in blob, (
        "manifest must record that memory came from the shallow fallback")


def test_latest_changelog_entry_only(built_bundle):
    primer = (built_bundle / "PRIMER.md").read_text()
    assert "Added the anvil calibration routine." in primer
    assert "bellows timer drift" not in primer  # the older 0.3.1 entry


def test_decisions_included_verbatim(built_bundle):
    primer = (built_bundle / "PRIMER.md").read_text()
    assert "Ship releases on Fridays after the full suite passes." in primer
    assert "Demo widgets are forged at 900 degrees in all fixtures." in primer


def test_memory_items_carry_provenance(built_bundle):
    manifest = load_manifest(built_bundle)
    items = memory_items(manifest)
    assert items, "no memory items recorded in the manifest"
    with_source = [i for i in items
                   if "decisions.md" in json.dumps(i).lower()
                   or "agents.md" in json.dumps(i).lower()
                   or "changelog" in json.dumps(i).lower()]
    assert with_source, "memory items do not name their source files"
