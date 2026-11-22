"""GhostSchema CLI: slice | inspect | mcp.

Exit codes: 0 = success, 2 = could not process (unsupported format,
YAML, parse failure, selection matched nothing, unknown select id).
The input spec is only ever read, never written.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .bundle import build_manifest, write_bundle
from .graphql import outline_sdl, render_outline_md
from .jsreduce import component_entries, list_operations, slice_jsonschema, slice_openapi
from .loader import SchemaError, load_spec


def _parse_select(raw):
    """Normalise a ``--select`` value to a list of id strings.

    Accepts ``None`` (no selection), a comma-separated string from
    the CLI, or a list/tuple from the MCP server. Empty pieces are
    dropped. Returns ``None`` when no selection was given.
    """
    if not raw:
        return None
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw]
    return [part for part in (p.strip() for p in str(raw).split(",")) if part]


def run_slice(spec_path, task=None, select=None, keep_all=False, outdir=None):
    """Slice one spec and write its bundle. Core entry shared by the
    CLI and the MCP server.

    Exactly one selection mode applies, in this order: ``keep_all``
    (``--all``), then ``select`` (``--select`` ids), then ``task``
    (``--task`` wording). JSON specs produce a reduced ``spec.json``;
    GraphQL SDL produces an outline bundle instead. Returns the
    manifest dict. Raises SchemaError on any refusal or failure
    (unsupported or YAML format, unknown select id, selection that
    matched nothing, closure check failure).
    """
    loaded = load_spec(spec_path)
    select_ids = _parse_select(select)
    out = Path(outdir) if outdir else Path.cwd() / "schema-slice"
    if out.resolve() == loaded.path.resolve():
        raise SchemaError("output directory must not be the spec file itself")
    # The input is never modified: refuse if any file the bundle would
    # write lands on the spec itself (an output directory equal to the
    # spec's own directory plus a spec named like a bundle artifact, or
    # a bundle filename symlinked onto the spec).
    artifact_names = (
        ("outline.json", "OUTLINE.md", "manifest.json", "SCHEMA.md")
        if loaded.format == "graphql-sdl"
        else ("spec.json", "manifest.json", "SCHEMA.md")
    )
    for name in artifact_names:
        if (out / name).resolve() == loaded.path.resolve():
            raise SchemaError(
                f"output directory {out} would overwrite the input spec "
                f"({loaded.path}) with bundle file {name}; "
                "choose a different output directory"
            )
    if loaded.format == "graphql-sdl":
        result = outline_sdl(loaded.text, task=task, select_ids=select_ids,
                             keep_all=keep_all)
        outline = result["outline"]
        outline_text = json.dumps(outline, indent=2) + "\n"
        md_text = render_outline_md(outline, loaded.path.name)
        manifest = build_manifest(loaded, "outline", result,
                                  outline_text + md_text)
        write_bundle(out, {"outline.json": outline_text, "OUTLINE.md": md_text},
                     manifest)
        return manifest
    if loaded.format == "openapi":
        result = slice_openapi(loaded.doc, task=task, select_ids=select_ids,
                               keep_all=keep_all)
    else:
        result = slice_jsonschema(loaded.doc, task=task, select_ids=select_ids,
                                  keep_all=keep_all)
    spec_text = json.dumps(result["reduced_doc"], indent=2) + "\n"
    manifest = build_manifest(loaded, "reduced", result, spec_text)
    if result["unresolved"]:
        external = [u for u in result["unresolved"] if not u.get("missing_local")]
        if external:
            manifest["warnings"] = list(manifest["warnings"]) + [
                f"{len(external)} remote reference(s) were not fetched "
                "(static parsing only) and are listed under unresolved_refs"
            ]
            result["warnings"] = manifest["warnings"]
    write_bundle(out, {"spec.json": spec_text}, manifest)
    return manifest


def inspect_data(spec_path):
    """Return a summary dict describing one spec, without slicing it.

    Always includes the detected format, source file name, sha256,
    and byte size. OpenAPI summaries list operations and component
    names; JSON Schema summaries list the title, root properties,
    and definition names; SDL summaries list types and note that
    treatment is outline-only. Raises SchemaError on any refusal.
    """
    loaded = load_spec(spec_path)
    data = {"format": loaded.format, "source": loaded.path.name,
            "sha256": loaded.sha256, "bytes": loaded.size_bytes}
    if loaded.format == "openapi":
        ops = list_operations(loaded.doc)
        data["operations"] = [
            {"operation": op["label"], "operationId": op["node"].get("operationId")}
            for op in ops
        ]
        data["components"] = {
            section: sorted(entries)
            for section, entries in component_entries(loaded.doc).items()
        }
    elif loaded.format == "jsonschema":
        from .jsreduce import DEF_SECTIONS
        data["title"] = loaded.doc.get("title")
        data["defs"] = {
            section: sorted(loaded.doc[section])
            for section in DEF_SECTIONS
            if isinstance(loaded.doc.get(section), dict)
        }
        props = loaded.doc.get("properties")
        data["root_properties"] = sorted(props) if isinstance(props, dict) else []
    else:
        from .graphql import parse_sdl
        types, directives = parse_sdl(loaded.text)
        data["treatment"] = "outline"
        data["types"] = [
            {"name": t["name"], "kind": t["kind"],
             "fields": [f["name"] for f in t["fields"]],
             "values": t["values"], "members": t["members"]}
            for t in types
        ]
        data["directives_not_outlined"] = sorted(set(directives))
    return data


def _print_inspect(data):
    """Print an :func:`inspect_data` summary in plain text."""
    print(f"format: {data['format']}")
    if data["format"] == "openapi":
        print(f"operations: {len(data['operations'])}")
        for op in data["operations"]:
            print(f"  {op['operation']}")
        for section, names in data["components"].items():
            print(f"components/{section}: {len(names)}")
            for name in names:
                print(f"  {name}")
    elif data["format"] == "jsonschema":
        if data.get("title"):
            print(f"title: {data['title']}")
        if data["root_properties"]:
            print("root properties: " + ", ".join(data["root_properties"]))
        for section, names in data["defs"].items():
            print(f"{section}: {len(names)}")
            for name in names:
                print(f"  {name}")
    else:
        print("treatment: outline (GraphQL SDL is outline-only)")
        for t in data["types"]:
            print(f"  {t['kind']} {t['name']}: "
                  f"{len(t['fields'])} fields, {len(t['values'])} values, "
                  f"{len(t['members'])} members")


def _print_summary(manifest, outdir):
    """Print the short stdout summary shown after a successful slice."""
    print(f"GhostSchema: {manifest['source']['name']} ({manifest['format']}, "
          f"treatment: {manifest['treatment']})")
    print(f"Tokens (estimated): {manifest['original_tokens']} -> "
          f"{manifest['sliced_tokens']} (saved {manifest['saved_tokens']})")
    for key, value in manifest["kept"].items():
        if isinstance(value, list):
            print(f"Kept {key}: {len(value)}")
        else:
            print(f"Kept {key}: {value}")
    for key, value in manifest["dropped"].items():
        if isinstance(value, list):
            print(f"Dropped {key}: {len(value)}")
    if manifest["unresolved_refs"]:
        print(f"Unresolved refs (never fetched): {len(manifest['unresolved_refs'])}")
    for warning in manifest["warnings"]:
        print(f"Warning: {warning}")
    print(f"Bundle written to {outdir}")


def main(argv=None):
    """Command-line entry point. Returns 0 on success, 2 on failure."""
    parser = argparse.ArgumentParser(
        prog="ghostschema",
        description="Slice large API specifications down to what a task "
                    "touches. OpenAPI 3.x JSON and standalone JSON Schema "
                    "are reduced by $ref reachability; GraphQL SDL is "
                    "outlined only. Remote $refs are never fetched. "
                    "YAML and Swagger / OpenAPI 2.0 specs are refused.",
        epilog="Exit codes: 0 = success, 2 = the spec could not be "
               "processed (the reason is printed to stderr). "
               "Run 'ghostschema <command> --help' for command help.")
    parser.add_argument("--version", action="version",
                        version=f"ghostschema {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_slice = sub.add_parser(
        "slice", help="slice a spec into a bundle directory",
        description="Slice a spec into a bundle directory containing "
                    "the reduced spec (or SDL outline), manifest.json, "
                    "and SCHEMA.md. The input file is never modified. "
                    "Give one selection: --select, --task, or --all.",
        epilog="Examples:\n"
               "  ghostschema slice api.json --select getPet -o bundle/\n"
               "  ghostschema slice api.json --task \"add a pet\" -o bundle/\n"
               "  ghostschema slice api.json --all -o bundle/\n"
               "  ghostschema slice schema.graphql --select Pet -o bundle/",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p_slice.add_argument("spec", help="path to the spec file (OpenAPI 3.x "
                                      "JSON, JSON Schema JSON, or GraphQL SDL)")
    p_slice.add_argument("--task", help="task description in plain words; "
                                        "operations and schemas are selected "
                                        "by word matching (see README Limits)")
    p_slice.add_argument("--select", help="comma-separated ids: operationIds, "
                                          "'METHOD /path', bare paths, schema "
                                          "names, #/ pointers, SDL type names, "
                                          "or 'root' for JSON Schema; unknown "
                                          "ids fail by name")
    p_slice.add_argument("--all", action="store_true",
                         help="keep the full document (baseline for token "
                              "comparison / escape hatch)")
    p_slice.add_argument("-o", "--out", default=None,
                         help="output bundle directory (default: ./schema-slice)")

    p_inspect = sub.add_parser(
        "inspect", help="list operations/schemas/types in a spec",
        description="List what a spec contains without slicing it: "
                    "its format, operations, schemas, definitions, or "
                    "SDL types, depending on the format detected.")
    p_inspect.add_argument("spec", help="path to the spec file")
    p_inspect.add_argument("--json", action="store_true",
                           help="print the listing as JSON instead of plain text")

    sub.add_parser(
        "mcp", help="run the stdio MCP server",
        description="Run the stdio MCP server (JSON-RPC over stdin and "
                    "stdout) serving the schema_inspect and schema_slice "
                    "tools. Payloads are summaries only, with no spec "
                    "bodies. Local only; no network access.")

    args = parser.parse_args(argv)
    try:
        if args.command == "slice":
            outdir = args.out or "schema-slice"
            manifest = run_slice(args.spec, task=args.task, select=args.select,
                                 keep_all=args.all, outdir=outdir)
            _print_summary(manifest, outdir)
            return 0
        if args.command == "inspect":
            data = inspect_data(args.spec)
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                _print_inspect(data)
            return 0
        if args.command == "mcp":
            from .mcp_server import serve
            return serve()
    except SchemaError as exc:
        print(f"ghostschema: {exc}", file=sys.stderr)
        return 2
    except RecursionError:
        print("ghostschema: spec is nested too deeply to process "
              "statically", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
