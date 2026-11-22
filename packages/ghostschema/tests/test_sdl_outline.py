"""GraphQL SDL tests: outline only, labelled outline everywhere.

Ground truth for schema.graphql: selecting Pet keeps Pet, PetDetails,
Tag, and PetStatus (by name reachability through field types), and
drops Order, OrderLine, OrderStatus, and the planted waste type
AuditLog, each named in the manifest. No .graphql file is ever
emitted: an outline is not a reduced schema.
"""

from __future__ import annotations

import json

from conftest import assert_hashes_unchanged, requires_cli
from helpers import SDL_SCHEMA, combined, load_json, manifest_lists, run_cli


def slice_sdl(tmp_path, *extra):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", SDL_SCHEMA, "-o", out, *extra])
    return proc, out


@requires_cli
def test_sdl_bundle_is_outline_shaped(tmp_path):
    proc, out = slice_sdl(tmp_path, "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    assert (out / "outline.json").is_file(), (
        f"bundle contents: {sorted(p.name for p in out.iterdir())}")
    assert (out / "OUTLINE.md").is_file()
    assert (out / "manifest.json").is_file()
    # No reduced SDL document is ever emitted.
    emitted = [p.name for p in out.iterdir()
               if p.suffix in (".graphql", ".gql")]
    assert emitted == [], f"SDL output must be outline only, found {emitted}"


@requires_cli
def test_sdl_outline_labelled_everywhere(tmp_path):
    proc, out = slice_sdl(tmp_path, "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    outline_text = (out / "outline.json").read_text(encoding="utf-8")
    assert "outline" in outline_text.lower()
    md_text = (out / "OUTLINE.md").read_text(encoding="utf-8")
    assert "outline" in md_text.lower()
    manifest = load_json(out / "manifest.json")
    assert manifest.get("treatment") == "outline", manifest.get("treatment")


@requires_cli
def test_sdl_outline_names_reachable_types_and_fields(tmp_path):
    proc, out = slice_sdl(tmp_path, "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    outline = load_json(out / "outline.json")
    text = json.dumps(outline)
    for name in ("Pet", "PetDetails", "Tag", "PetStatus"):
        assert name in text, f"{name} missing from outline"
    # Fields ride along with their types in an outline.
    for field in ("primaryTag", "breed", "label"):
        assert field in text, f"field {field} missing from outline"


@requires_cli
def test_sdl_dropped_types_named_in_manifest(tmp_path):
    proc, out = slice_sdl(tmp_path, "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    manifest = load_json(out / "manifest.json")
    lists = manifest_lists(manifest)
    from helpers import any_entry_mentions
    for name in ("Order", "AuditLog"):
        assert any_entry_mentions(lists["dropped"], name), lists["dropped"]
    # The waste type must not be among the outline's KEPT types. (The
    # outline artifact may legitimately name dropped types in its own
    # dropped listing; that is not keeping them.)
    outline = load_json(out / "outline.json")
    kept_type_names = {t.get("name") for t in outline.get("types", [])
                       if isinstance(t, dict)}
    assert "AuditLog" not in kept_type_names, kept_type_names
    assert "Order" not in kept_type_names, kept_type_names


@requires_cli
def test_sdl_input_byte_identical(tmp_path, fixture_hashes):
    proc, _ = slice_sdl(tmp_path, "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    assert_hashes_unchanged(fixture_hashes)
