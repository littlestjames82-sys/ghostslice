"""OpenAPI slicing tests: reachability, closure, manifest discipline.

Ground truth for the petstore fixture (proved in test_fixtures.py):
slicing --select getPet must keep the operation getPet, the chain
Pet -> PetDetails -> Tag plus PetStatus, the shared NotFound response
and the Error schema, and the PetId path parameter. It must drop the
whole orders surface, the other pet operations, and the planted waste
schemas (LegacyPet, AuditRecord, Invoice), each named in the manifest.
"""

from __future__ import annotations

from conftest import assert_hashes_unchanged, requires_cli
from helpers import (PETSTORE, any_entry_mentions, combined, load_json,
                     manifest_lists, run_cli, unresolved_local_refs)

EXPECTED_KEPT_SCHEMAS = {"Pet", "PetDetails", "Tag", "PetStatus", "Error"}
EXPECTED_DROPPED_SCHEMAS = {
    "PetSummary", "PetInput",
    "Order", "OrderLine", "OrderInput", "OrderStatus",
    "LegacyPet", "AuditRecord", "Invoice",
}


def slice_petstore(tmp_path, *extra):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PETSTORE, "-o", out, *extra])
    return proc, out


@requires_cli
def test_select_getpet_exit_ok_and_bundle_shape(tmp_path):
    proc, out = slice_petstore(tmp_path, "--select", "getPet")
    assert proc.returncode == 0, combined(proc)
    assert (out / "spec.json").is_file(), f"bundle contents: {sorted(p.name for p in out.iterdir())}"
    assert (out / "manifest.json").is_file()
    assert (out / "SCHEMA.md").is_file()


@requires_cli
def test_select_getpet_reduced_spec_parses_and_closes(tmp_path):
    proc, out = slice_petstore(tmp_path, "--select", "getPet")
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    assert str(reduced.get("openapi", "")).startswith("3.")
    bad = unresolved_local_refs(reduced)
    assert bad == [], f"reduced spec has dangling local $refs: {bad}"


@requires_cli
def test_select_getpet_keeps_chain_drops_unrelated(tmp_path):
    proc, out = slice_petstore(tmp_path, "--select", "getPet")
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    kept_schemas = set(reduced.get("components", {}).get("schemas", {}))
    assert EXPECTED_KEPT_SCHEMAS <= kept_schemas, kept_schemas
    assert kept_schemas.isdisjoint(EXPECTED_DROPPED_SCHEMAS), kept_schemas
    # Only the getPet operation survives on the kept path.
    paths = reduced.get("paths", {})
    assert set(paths) == {"/pets/{petId}"}, paths.keys()
    assert set(paths["/pets/{petId}"]) - {"parameters"} == {"get"}
    # Errors: the shared NotFound response and PetId parameter survive.
    assert "NotFound" in reduced["components"].get("responses", {})
    assert "PetId" in reduced["components"].get("parameters", {})
    assert "PageSize" not in reduced["components"].get("parameters", {})


@requires_cli
def test_select_getpet_manifest_names_kept_and_dropped(tmp_path):
    proc, out = slice_petstore(tmp_path, "--select", "getPet")
    assert proc.returncode == 0, combined(proc)
    manifest = load_json(out / "manifest.json")
    lists = manifest_lists(manifest)
    for name in ("Pet", "Tag", "getPet"):
        assert any_entry_mentions(lists["kept"], name), lists["kept"]
    for name in ("Order", "LegacyPet", "AuditRecord", "listOrders"):
        assert any_entry_mentions(lists["dropped"], name), lists["dropped"]
    assert manifest.get("treatment") == "reduced"
    # Token honesty shape: estimates are present integers, sliced < full
    # for a fixture with planted waste.
    original = manifest.get("original_tokens")
    sliced = manifest.get("sliced_tokens")
    assert isinstance(original, int) and isinstance(sliced, int)
    assert 0 < sliced < original


@requires_cli
def test_select_by_schema_name_and_pointer(tmp_path):
    for selector in ("Pet", "#/components/schemas/Pet"):
        out = tmp_path / f"bundle-{abs(hash(selector)) % 9999}"
        proc = run_cli(["slice", PETSTORE, "--select", selector, "-o", out])
        assert proc.returncode == 0, f"{selector}: {combined(proc)}"
        reduced = load_json(out / "spec.json")
        schemas = set(reduced.get("components", {}).get("schemas", {}))
        assert {"Pet", "PetDetails", "Tag"} <= schemas
        assert unresolved_local_refs(reduced) == []


@requires_cli
def test_select_unknown_id_fails_loudly_by_name(tmp_path):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PETSTORE, "--select", "NoSuchThing", "-o", out])
    assert proc.returncode == 2, combined(proc)
    assert "NoSuchThing" in combined(proc)


@requires_cli
def test_all_flag_keeps_everything(tmp_path):
    proc, out = slice_petstore(tmp_path, "--all")
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    schemas = set(reduced.get("components", {}).get("schemas", {}))
    full = set(load_json(PETSTORE)["components"]["schemas"])
    assert schemas == full, (full - schemas)
    assert unresolved_local_refs(reduced) == []


@requires_cli
def test_task_selection_keeps_named_operation(tmp_path):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", PETSTORE, "--task", "getPet details for one pet",
                    "-o", out])
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    manifest = load_json(out / "manifest.json")
    lists = manifest_lists(manifest)
    assert any_entry_mentions(lists["kept"], "getPet"), lists["kept"]
    assert unresolved_local_refs(reduced) == []


@requires_cli
def test_input_byte_identical_after_slice(tmp_path, fixture_hashes):
    proc, _ = slice_petstore(tmp_path, "--select", "getPet")
    assert proc.returncode == 0, combined(proc)
    assert_hashes_unchanged(fixture_hashes)
