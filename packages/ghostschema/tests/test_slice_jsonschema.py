"""Standalone JSON Schema slicing tests.

Ground truth for parts-schema.json: selecting Widget keeps the chain
Widget -> Gadget -> Sprocket, drops the planted waste defs Doohickey
and Thingamajig, and the reduced document closes locally.
"""

from __future__ import annotations

from conftest import assert_hashes_unchanged, requires_cli
from helpers import (PARTS_SCHEMA, combined, load_json, run_cli,
                     unresolved_local_refs)


def defs_of(doc):
    return set(doc.get("$defs") or doc.get("definitions") or {})


@requires_cli
def test_select_widget_keeps_chain_drops_waste(tmp_path):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PARTS_SCHEMA, "--select", "Widget", "-o", out])
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    assert defs_of(reduced) == {"Widget", "Gadget", "Sprocket"}, defs_of(reduced)
    assert unresolved_local_refs(reduced) == []


@requires_cli
def test_select_widget_by_pointer(tmp_path):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PARTS_SCHEMA, "--select", "#/$defs/Widget",
                    "-o", out])
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    assert "Widget" in defs_of(reduced)
    assert unresolved_local_refs(reduced) == []


@requires_cli
def test_root_reference_to_selected_def(tmp_path):
    """Selecting only Gadget: the root shell is not itself selected, so
    per the PLAN the output root points at the kept def (a root $ref,
    or an anyOf of $refs for several) and still closes."""
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PARTS_SCHEMA, "--select", "Gadget", "-o", out])
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    assert defs_of(reduced) == {"Gadget", "Sprocket"}, defs_of(reduced)
    assert unresolved_local_refs(reduced) == []


@requires_cli
def test_json_schema_input_unchanged(tmp_path, fixture_hashes):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PARTS_SCHEMA, "--select", "Widget", "-o", out])
    assert proc.returncode == 0, combined(proc)
    assert_hashes_unchanged(fixture_hashes)
