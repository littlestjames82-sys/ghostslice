"""Hardening tests (improvement lane HARDEN, Oct 18, 2026).

Each test pins a bug found by probing the v0.1 core with hostile or
merely unlucky inputs: BOM-saved specs, bundle output that would land
on the input file itself, malformed $ref pointers, compact SDL that
packs definitions onto one line, a stray quote in an SDL comment,
wrapped GraphQL root types, deeply nested schemas, unwritable bundle
paths, and malformed MCP traffic. Before the fixes these crashed with
tracebacks, were refused outright, silently lost types, or (worst)
overwrote the input spec. The contract now: succeed correctly, or
refuse cleanly with exit 2 and no traceback, and never modify input.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from conftest import requires_cli
from helpers import (PETSTORE, SDL_SCHEMA, combined, find_cli, load_json,
                     manifest_lists, run_cli, sha256_of)


def write_json(tmp_path, doc, name="api.json"):
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# --------------------------------------------------------------------- BOM

@requires_cli
def test_bom_saved_json_spec_slices(tmp_path):
    spec = tmp_path / "bom.json"
    spec.write_bytes(b"\xef\xbb\xbf" + PETSTORE.read_bytes())
    out = tmp_path / "bundle"
    proc = run_cli(["slice", spec, "--select", "getPet", "-o", out])
    assert proc.returncode == 0, combined(proc)
    manifest = load_json(out / "manifest.json")
    assert manifest["format"] == "openapi"
    # The recorded hash still describes the raw file, BOM included.
    assert manifest["source"]["sha256"] == sha256_of(spec)


@requires_cli
def test_bom_saved_sdl_outlines_first_type(tmp_path):
    # The BOM sits directly on the first definition line: an unstripped
    # BOM breaks the parser's definition anchor and the type is lost.
    spec = tmp_path / "bom.graphql"
    spec.write_bytes(
        b"\xef\xbb\xbf" + b"type Query { pet: String }\n")
    out = tmp_path / "bundle"
    proc = run_cli(["slice", spec, "--all", "-o", out])
    assert proc.returncode == 0, combined(proc)
    outline = load_json(out / "outline.json")
    assert [t["name"] for t in outline["types"]] == ["Query"], outline


# ------------------------------------------------- input is never overwritten

@requires_cli
def test_output_dir_must_not_overwrite_input_named_spec_json(tmp_path):
    spec = tmp_path / "spec.json"
    shutil.copy(PETSTORE, spec)
    before = sha256_of(spec)
    proc = run_cli(["slice", spec, "--select", "getPet", "-o", tmp_path])
    assert proc.returncode == 2, combined(proc)
    assert "overwrite" in combined(proc), combined(proc)
    assert sha256_of(spec) == before


@requires_cli
def test_output_dir_must_not_overwrite_input_named_manifest_json(tmp_path):
    spec = tmp_path / "manifest.json"
    shutil.copy(PETSTORE, spec)
    before = sha256_of(spec)
    proc = run_cli(["slice", spec, "--select", "getPet", "-o", tmp_path])
    assert proc.returncode == 2, combined(proc)
    assert sha256_of(spec) == before


@requires_cli
def test_output_dir_must_not_overwrite_sdl_input_named_outline_json(tmp_path):
    spec = tmp_path / "outline.json"
    shutil.copy(SDL_SCHEMA, spec)
    before = sha256_of(spec)
    proc = run_cli(["slice", spec, "--all", "-o", tmp_path])
    assert proc.returncode == 2, combined(proc)
    assert sha256_of(spec) == before


@requires_cli
def test_output_dir_beside_input_is_still_allowed(tmp_path):
    spec = tmp_path / "api.json"
    shutil.copy(PETSTORE, spec)
    before = sha256_of(spec)
    proc = run_cli(["slice", spec, "--select", "getPet", "-o", tmp_path])
    assert proc.returncode == 0, combined(proc)
    assert (tmp_path / "spec.json").exists()
    assert sha256_of(spec) == before


# ------------------------------------------------------------- hostile $refs

@requires_cli
def test_task_selection_tolerates_root_fragment_ref(tmp_path):
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": {"/pets": {"get": {
            "operationId": "getPet",
            "responses": {"200": {"description": "ok", "content": {
                "application/json": {"schema": {"$ref": "#/"}}}}},
        }}},
        "components": {"schemas": {"Pet": {"type": "object"}}},
    }
    spec = write_json(tmp_path, doc)
    out = tmp_path / "bundle"
    proc = run_cli(["slice", spec, "--task", "pet", "-o", out])
    assert proc.returncode == 0, combined(proc)
    assert "Traceback" not in combined(proc)


@requires_cli
def test_non_ascii_digit_pointer_segment_does_not_crash(tmp_path):
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": {},
        "components": {"schemas": {"Pet": {
            "type": "object",
            "allOf": [{"$ref": "#/components/schemas/Pet/allOf/²"}],
        }}},
    }
    spec = write_json(tmp_path, doc)
    out = tmp_path / "bundle"
    proc = run_cli(["slice", spec, "--select", "Pet", "-o", out])
    assert proc.returncode == 0, combined(proc)
    assert "Traceback" not in combined(proc)
    lists = manifest_lists(load_json(out / "manifest.json"))
    assert any("allOf" in entry for entry in lists["unresolved"]), lists


# ------------------------------------------------------------------ SDL edges

def slice_sdl_text(tmp_path, text, *extra):
    spec = tmp_path / "case.graphql"
    spec.write_text(text, encoding="utf-8")
    out = tmp_path / "bundle"
    proc = run_cli(["slice", spec, "-o", out, *extra])
    return proc, out


@requires_cli
def test_sdl_two_definitions_on_one_line_both_parsed(tmp_path):
    proc, out = slice_sdl_text(
        tmp_path, "type Query { pet: Pet } type Pet { id: ID }\n", "--all")
    assert proc.returncode == 0, combined(proc)
    names = [t["name"] for t in load_json(out / "outline.json")["types"]]
    assert names == ["Query", "Pet"], names


@requires_cli
def test_sdl_stray_quote_in_comment_does_not_swallow_types(tmp_path):
    text = (
        '# comment with an "unbalanced quote\n'
        "type Query { pet: Pet }\n"
        "type Pet { id: ID }\n"
        '"a description"\n'
        "type Extra { x: String }\n"
    )
    proc, out = slice_sdl_text(tmp_path, text, "--all")
    assert proc.returncode == 0, combined(proc)
    names = [t["name"] for t in load_json(out / "outline.json")["types"]]
    assert names == ["Query", "Pet", "Extra"], names


@requires_cli
def test_sdl_schema_block_kept_when_root_type_is_wrapped(tmp_path):
    text = "schema { query: Query! }\ntype Query { pet: String }\n"
    proc, out = slice_sdl_text(tmp_path, text, "--select", "Query")
    assert proc.returncode == 0, combined(proc)
    names = [t["name"] for t in load_json(out / "outline.json")["types"]]
    assert "schema" in names and "Query" in names, names


# --------------------------------------------------------- clean failure modes

@requires_cli
def test_deeply_nested_spec_fails_cleanly_exit2(tmp_path):
    node = {"type": "string"}
    for _ in range(300):
        node = {"type": "object", "properties": {"a": node}}
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "Deep", "version": "1"},
        "paths": {},
        "components": {"schemas": {"Deep": node}},
    }
    spec = write_json(tmp_path, doc, name="deep.json")
    out = tmp_path / "bundle"
    proc = run_cli(["slice", spec, "--all", "-o", out])
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)
    assert "deeply" in combined(proc), combined(proc)


@requires_cli
def test_unwritable_bundle_path_fails_cleanly_exit2(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    proc = run_cli(["slice", PETSTORE, "--select", "getPet",
                    "-o", blocker / "sub"])
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)


@requires_cli
def test_mcp_server_survives_malformed_lines(tmp_path):
    prefix, env_extra = find_cli()
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.Popen(
        prefix + ["mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, env=env)
    payload = "\n".join([
        "123",
        '"a bare string"',
        "[1, 2]",
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": None}),
        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "initialize",
                    "params": {}}),
    ]) + "\n"
    out, _ = proc.communicate(payload, timeout=60)
    assert proc.returncode == 0
    responses = [json.loads(line) for line in out.splitlines() if line.strip()]
    by_id = {r.get("id"): r for r in responses}
    assert "result" in by_id[99], responses
    assert "error" in by_id[1], responses
