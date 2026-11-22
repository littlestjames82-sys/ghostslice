"""External (remote) $ref tests: listed as unresolved, never fetched.

The petstore fixture's orders surface references
https://example.com/schemas/money.json and the parts schema references
https://example.com/schemas/materials.json. These tests slice entries
that REACH those refs. The suite runs offline by construction: if the
core tried to fetch, the run would fail or hang in this sandbox; the
contract assertions are that the run succeeds, the ref stays visible
in the output, and the manifest lists it as unresolved.
"""

from __future__ import annotations

from conftest import assert_hashes_unchanged, requires_cli
from helpers import (PARTS_SCHEMA, PETSTORE, any_entry_mentions, combined,
                     load_json, manifest_lists, remote_refs, run_cli,
                     unresolved_local_refs)

MONEY_URL = "https://example.com/schemas/money.json"
MATERIAL_URL = "https://example.com/schemas/materials.json"


@requires_cli
def test_external_ref_listed_unresolved_in_manifest(tmp_path):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PETSTORE, "--select", "Order", "-o", out])
    assert proc.returncode == 0, combined(proc)
    manifest = load_json(out / "manifest.json")
    lists = manifest_lists(manifest)
    assert lists["unresolved"], "manifest has no unresolved list"
    assert any_entry_mentions(lists["unresolved"], MONEY_URL), lists["unresolved"]


@requires_cli
def test_external_ref_kept_visible_in_reduced_spec(tmp_path):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PETSTORE, "--select", "listOrders", "-o", out])
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    assert any(MONEY_URL in ref for ref in remote_refs(reduced)), remote_refs(reduced)
    # Keeping a remote ref must not break local closure.
    assert unresolved_local_refs(reduced) == []


@requires_cli
def test_external_ref_unresolved_records_referrer(tmp_path):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PETSTORE, "--select", "Order", "-o", out])
    assert proc.returncode == 0, combined(proc)
    manifest = load_json(out / "manifest.json")
    lists = manifest_lists(manifest)
    entries = [e for e in lists["unresolved"] if MONEY_URL in e]
    assert entries, lists["unresolved"]
    # PLAN: unresolved entries carry the pointer they were referenced
    # from. At minimum the referrer context (Order) must be recorded.
    assert any("Order" in e for e in entries), entries


@requires_cli
def test_external_ref_in_json_schema_listed(tmp_path):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PARTS_SCHEMA, "--select", "Widget", "-o", out])
    assert proc.returncode == 0, combined(proc)
    manifest = load_json(out / "manifest.json")
    lists = manifest_lists(manifest)
    assert any_entry_mentions(lists["unresolved"], MATERIAL_URL), lists["unresolved"]


@requires_cli
def test_unreachable_external_ref_not_reported(tmp_path):
    """Slicing getPet never reaches the orders surface, so its remote
    ref is dropped with it, not listed as an unresolved kept ref."""
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PETSTORE, "--select", "getPet", "-o", out])
    assert proc.returncode == 0, combined(proc)
    manifest = load_json(out / "manifest.json")
    lists = manifest_lists(manifest)
    assert not any_entry_mentions(lists["unresolved"], MONEY_URL), lists["unresolved"]
    reduced = load_json(out / "spec.json")
    assert remote_refs(reduced) == []


@requires_cli
def test_inputs_unchanged_after_external_ref_runs(tmp_path, fixture_hashes):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PETSTORE, "--select", "Order", "-o", out])
    assert proc.returncode == 0, combined(proc)
    assert_hashes_unchanged(fixture_hashes)
