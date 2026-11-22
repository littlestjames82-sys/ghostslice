"""Fixture ground-truth tests (no GhostSchema core needed).

These prove the planted fixtures actually encode what the behavioural
tests assert: the A -> B -> C reachability chain, the unrelated orders
surface, planted waste schemas referenced by nothing, the external
https $ref, and the SDL type graph. If a fixture drifts, these fail
first and say why.
"""

from __future__ import annotations

import json

from helpers import (PARTS_SCHEMA, PETSTORE, SDL_SCHEMA, SWAGGER2,
                     YAML_IN_JSON, YAML_SPEC, iter_refs, load_json,
                     local_refs, reachable_schema_names, remote_refs,
                     resolve_pointer, unresolved_local_refs)

MONEY_URL = "https://example.com/schemas/money.json"
MATERIAL_URL = "https://example.com/schemas/materials.json"


def test_openapi_fixture_parses_and_is_openapi3():
    spec = load_json(PETSTORE)
    assert str(spec.get("openapi", "")).startswith("3.")
    assert spec["info"]["title"]


def test_openapi_fixture_is_internally_closed():
    spec = load_json(PETSTORE)
    assert unresolved_local_refs(spec) == [], (
        "the FULL fixture must close: every local $ref resolves in it; "
        "only reduced outputs are allowed to be tested for closure "
        "against themselves")


def test_openapi_chain_a_b_c():
    """getPet -> Pet -> PetDetails -> Tag, and Pet -> Tag directly."""
    spec = load_json(PETSTORE)
    op = spec["paths"]["/pets/{petId}"]["get"]
    assert op["operationId"] == "getPet"
    ok_resp = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok_resp == {"$ref": "#/components/schemas/Pet"}
    reachable = reachable_schema_names(spec, ["Pet"])
    assert {"Pet", "PetDetails", "Tag", "PetStatus"} <= reachable


def test_openapi_unrelated_and_waste_sets_exist():
    spec = load_json(PETSTORE)
    schemas = spec["components"]["schemas"]
    # Orders surface: reachable from its own operations, not from Pet.
    from_pet = reachable_schema_names(spec, ["Pet"])
    for name in ("Order", "OrderLine", "OrderInput", "OrderStatus"):
        assert name in schemas
        assert name not in from_pet
    # Planted waste: defined but referenced by no other node at all.
    text = json.dumps(spec)
    for name in ("LegacyPet", "AuditRecord", "Invoice"):
        assert name in schemas
        refs = [ref for _, ref in iter_refs(spec)
                if ref == f"#/components/schemas/{name}"]
        assert refs == [], f"{name} is supposed to be unreferenced waste"


def test_openapi_external_ref_is_planted_in_orders():
    spec = load_json(PETSTORE)
    remotes = remote_refs(spec)
    assert any(MONEY_URL in ref for ref in remotes), remotes
    order_refs = [ref for _, ref in iter_refs(spec["components"]["schemas"]["Order"])]
    assert any(MONEY_URL in ref for ref in order_refs)


def test_openapi_error_reachable_via_shared_response():
    spec = load_json(PETSTORE)
    not_found = spec["components"]["responses"]["NotFound"]
    target = resolve_pointer(spec, "#/components/schemas/Error")
    assert target is not None
    refs = [ref for _, ref in iter_refs(not_found)]
    assert "#/components/schemas/Error" in refs


def test_parts_schema_chain_and_waste():
    doc = load_json(PARTS_SCHEMA)
    defs = doc["$defs"]
    assert set(defs) == {"Widget", "Gadget", "Sprocket",
                         "Doohickey", "Thingamajig"}
    widget_refs = [r for _, r in iter_refs(defs["Widget"])]
    assert "#/$defs/Gadget" in widget_refs
    gadget_refs = [r for _, r in iter_refs(defs["Gadget"])]
    assert "#/$defs/Sprocket" in gadget_refs
    assert any(MATERIAL_URL in r for r in gadget_refs)
    # The full document closes locally too.
    assert unresolved_local_refs(doc) == []
    assert doc["properties"]["mainWidget"] == {"$ref": "#/$defs/Widget"}


def test_sdl_fixture_type_graph():
    text = SDL_SCHEMA.read_text(encoding="utf-8")
    for decl in ("type Query", "type Pet", "type PetDetails", "type Tag",
                 "enum PetStatus", "input PetFilter", "type Order",
                 "type OrderLine", "enum OrderStatus",
                 "union SearchResult = Pet | Order", "type AuditLog",
                 "scalar DateTime"):
        assert decl in text, decl
    # AuditLog is the planted unreachable type.
    assert text.count("AuditLog") == 1


def test_yaml_fixtures_are_yaml_not_json():
    for path in (YAML_SPEC, YAML_IN_JSON):
        text = path.read_text(encoding="utf-8")
        assert "openapi: 3.0.3" in text
        try:
            json.loads(text)
            raise AssertionError(f"{path.name} unexpectedly parses as JSON")
        except json.JSONDecodeError:
            pass


def test_swagger_fixture_is_swagger2():
    doc = load_json(SWAGGER2)
    assert doc.get("swagger") == "2.0"
    assert "openapi" not in doc
