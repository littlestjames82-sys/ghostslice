"""Implicit-reference reachability: discriminator mappings and Links.

OpenAPI names targets without a $ref key: ``discriminator.mapping``
values name subtype schemas, and Link Objects carry ``operationId``
or ``operationRef``. Before this coverage, slicing kept the carrier
(a polymorphic schema, a response with links) but dropped the named
targets, leaving dangling references the $ref closure check cannot
see. These tests pin the deepened graph: local implicit targets are
kept transitively, external ones are listed unresolved and never
fetched, and unreachable implicit targets are dropped with their
carrier, exactly like $refs.
"""

from __future__ import annotations

import json

from conftest import requires_cli
from helpers import (any_entry_mentions, combined, load_json,
                     manifest_lists, run_cli, unresolved_local_refs)

ROBOT_URL = "https://example.com/schemas/robot.json"


def _spec():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Implicit Pets", "version": "1"},
        "paths": {
            "/pets/{id}": {"get": {
                "operationId": "getPet",
                "responses": {"200": {
                    "description": "ok",
                    "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/Pet"}}},
                    "links": {"Owner": {"operationId": "getOwner"}},
                }},
            }},
            "/owners/{id}": {"get": {
                "operationId": "getOwner",
                "responses": {"200": {
                    "description": "ok",
                    "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/Owner"}}},
                    "links": {"Vets": {
                        "operationRef": "#/paths/~1vets/get"}},
                }},
            }},
            "/vets": {"get": {
                "operationId": "listVets",
                "responses": {"200": {"description": "ok"}},
            }},
            "/unrelated": {"get": {
                "operationId": "getUnrelated",
                "responses": {"200": {
                    "description": "ok",
                    "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/Unrelated"}}},
                }},
            }},
        },
        "components": {"schemas": {
            "Pet": {
                "type": "object",
                "discriminator": {"propertyName": "kind", "mapping": {
                    "dog": "#/components/schemas/Dog",
                    "cat": "Cat",
                    "robot": ROBOT_URL,
                }},
                "properties": {"kind": {"type": "string"}},
            },
            "Dog": {"type": "object", "properties": {
                "breed": {"$ref": "#/components/schemas/Breed"}}},
            "Cat": {"type": "object"},
            "Breed": {"type": "string"},
            "Owner": {"type": "object"},
            "Unrelated": {"type": "object", "discriminator": {
                "propertyName": "kind",
                "mapping": {"dog": "#/components/schemas/Dog"}}},
        }},
    }


def _write(tmp_path, spec=None):
    path = tmp_path / "implicit.json"
    path.write_text(json.dumps(spec if spec is not None else _spec()),
                    encoding="utf-8")
    return path


def _slice(tmp_path, spec_path, *extra):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", spec_path, "-o", out, *extra])
    return proc, out


@requires_cli
def test_discriminator_mapping_targets_kept_transitively(tmp_path):
    proc, out = _slice(tmp_path, _write(tmp_path), "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    schemas = set(reduced.get("components", {}).get("schemas", {}))
    # '#/components/schemas/Dog' pointer mapping and bare-name 'Cat'
    # mapping are both followed; Dog's own $ref chain (Breed) rides.
    assert {"Pet", "Dog", "Cat", "Breed"} <= schemas, schemas
    assert "Unrelated" not in schemas
    assert unresolved_local_refs(reduced) == []


@requires_cli
def test_external_discriminator_mapping_listed_never_fetched(tmp_path):
    proc, out = _slice(tmp_path, _write(tmp_path), "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    manifest = load_json(out / "manifest.json")
    lists = manifest_lists(manifest)
    entries = [e for e in lists["unresolved"] if ROBOT_URL in e]
    assert entries, lists["unresolved"]
    assert any("discriminator" in e for e in entries), entries
    # The mapping stays visible in the reduced spec (nothing dangles
    # silently), pointing at the listed unresolved URL.
    reduced = load_json(out / "spec.json")
    mapping = reduced["components"]["schemas"]["Pet"]["discriminator"]["mapping"]
    assert mapping["robot"] == ROBOT_URL


@requires_cli
def test_link_operation_id_and_ref_chain_kept(tmp_path):
    proc, out = _slice(tmp_path, _write(tmp_path), "--select", "getPet")
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    # getPet links by operationId to getOwner; getOwner links by
    # operationRef to listVets. Both hops survive; unrelated drops.
    assert set(reduced.get("paths", {})) == {
        "/pets/{id}", "/owners/{id}", "/vets"}, reduced.get("paths", {})
    manifest = load_json(out / "manifest.json")
    lists = manifest_lists(manifest)
    for name in ("getOwner", "listVets", "Owner"):
        assert any_entry_mentions(lists["kept"], name), lists["kept"]
    assert any_entry_mentions(lists["dropped"], "getUnrelated")
    assert unresolved_local_refs(reduced) == []


@requires_cli
def test_unreachable_implicit_targets_not_followed(tmp_path):
    """Unrelated carries a discriminator mapping to Dog, but slicing
    an operation that never reaches Unrelated must not drag Dog in."""
    proc, out = _slice(tmp_path, _write(tmp_path), "--select", "listVets")
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    schemas = set(reduced.get("components", {}).get("schemas", {}))
    assert "Dog" not in schemas and "Pet" not in schemas, schemas
    manifest = load_json(out / "manifest.json")
    lists = manifest_lists(manifest)
    assert not any_entry_mentions(lists["unresolved"], ROBOT_URL)


@requires_cli
def test_missing_discriminator_target_reported_not_silent(tmp_path):
    spec = _spec()
    spec["components"]["schemas"]["Pet"]["discriminator"]["mapping"]["ghost"] = \
        "#/components/schemas/Ghost"
    proc, out = _slice(tmp_path, _write(tmp_path, spec), "--select", "Pet")
    assert proc.returncode == 0, combined(proc)
    manifest = load_json(out / "manifest.json")
    lists = manifest_lists(manifest)
    assert any_entry_mentions(lists["unresolved"], "Ghost"), lists["unresolved"]
    assert any("Ghost" in w for w in manifest["warnings"]), manifest["warnings"]


@requires_cli
def test_link_to_component_link_object_followed(tmp_path):
    """A response link that is itself a $ref to components/links must
    still resolve its operationId once the link object is reached."""
    spec = _spec()
    spec["paths"]["/pets/{id}"]["get"]["responses"]["200"]["links"] = {
        "Owner": {"$ref": "#/components/links/OwnerLink"}}
    spec["components"]["links"] = {
        "OwnerLink": {"operationId": "getOwner"}}
    proc, out = _slice(tmp_path, _write(tmp_path, spec),
                       "--select", "getPet")
    assert proc.returncode == 0, combined(proc)
    reduced = load_json(out / "spec.json")
    assert "/owners/{id}" in reduced.get("paths", {}), reduced.get("paths", {})
    assert "OwnerLink" in reduced.get("components", {}).get("links", {})
    assert unresolved_local_refs(reduced) == []
