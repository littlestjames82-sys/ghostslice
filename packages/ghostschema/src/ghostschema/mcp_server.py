"""Stdio MCP server (JSON-RPC), local only, same discipline as
GhostSlice's MCP server: capped summary payloads, no spec bodies.
Tools: schema_slice, schema_inspect.
"""
from __future__ import annotations

import json
import sys

from . import __version__

MAX_LIST = 200


def _cap(items):
    """Cap a list at MAX_LIST entries, appending a ``... (N more)``
    marker when it was longer, so payloads stay summaries."""
    items = list(items)
    if len(items) > MAX_LIST:
        return items[:MAX_LIST] + [f"... ({len(items) - MAX_LIST} more)"]
    return items


def _tool_slice(args):
    from .cli import run_slice
    manifest = run_slice(
        args["spec"],
        task=args.get("task"),
        select=args.get("select"),
        keep_all=bool(args.get("all")),
        outdir=args["out"],
    )
    return {
        "format": manifest["format"],
        "treatment": manifest["treatment"],
        "original_tokens": manifest["original_tokens"],
        "sliced_tokens": manifest["sliced_tokens"],
        "saved_tokens": manifest["saved_tokens"],
        "kept": {k: (_cap(v) if isinstance(v, list) else v)
                 for k, v in manifest["kept"].items()},
        "dropped": {k: (_cap(v) if isinstance(v, list) else v)
                    for k, v in manifest["dropped"].items()},
        "unresolved_refs": _cap(manifest["unresolved_refs"]),
        "warnings": manifest["warnings"],
        "out": args["out"],
    }


def _tool_inspect(args):
    from .cli import inspect_data
    return inspect_data(args["spec"])


TOOLS = {
    "schema_slice": {
        "description": "Slice a spec (OpenAPI 3.x JSON / JSON Schema / "
                       "GraphQL SDL outline) into an output bundle and "
                       "return the manifest summary (no spec bodies). "
                       "Give one selection: select, task, or all. "
                       "Remote $refs are never fetched; YAML is refused.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": {"type": "string",
                         "description": "path to the spec file"},
                "out": {"type": "string",
                        "description": "output bundle directory"},
                "task": {"type": "string",
                         "description": "task wording for word-matching selection"},
                "select": {"type": "array", "items": {"type": "string"},
                           "description": "explicit ids to select (operationIds, "
                                          "schema names, #/ pointers, or SDL type names)"},
                "all": {"type": "boolean",
                        "description": "keep the full document"},
            },
            "required": ["spec", "out"],
        },
        "run": _tool_slice,
    },
    "schema_inspect": {
        "description": "List operations and component schemas (OpenAPI), "
                       "definitions (JSON Schema), or types (GraphQL SDL) "
                       "in a spec file, with its format, hash, and size. "
                       "Returns a summary only, never spec bodies.",
        "inputSchema": {
            "type": "object",
            "properties": {"spec": {"type": "string",
                                    "description": "path to the spec file"}},
            "required": ["spec"],
        },
        "run": _tool_inspect,
    },
}


def handle(request):
    """Handle one JSON-RPC request dict. Returns the response dict,
    or ``None`` for notifications (which get no response). Supports
    ``initialize``, ``tools/list``, and ``tools/call``; unknown
    methods and tools return JSON-RPC error objects."""
    if not isinstance(request, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {
            "code": -32600, "message": "invalid request: not a JSON object"}}
    method = request.get("method", "")
    if not isinstance(method, str):
        method = ""
    rid = request.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ghostschema", "version": __version__},
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "tools": [{"name": name, "description": t["description"],
                       "inputSchema": t["inputSchema"]}
                      for name, t in TOOLS.items()],
        }}
    if method == "tools/call":
        params = request.get("params")
        if not isinstance(params, dict):
            params = {}
        tool = TOOLS.get(params.get("name", ""))
        if tool is None:
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32602, "message": f"unknown tool {params.get('name')!r}"}}
        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            result = tool["run"](arguments)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(result, indent=2)}],
            }}
        except Exception as exc:  # surfaced to the client, never hidden
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32000, "message": str(exc)}}
    if method.startswith("notifications/"):
        return None
    return {"jsonrpc": "2.0", "id": rid, "error": {
        "code": -32601, "message": f"unknown method {method!r}"}}


def serve(stdin=None, stdout=None):
    """Serve JSON-RPC requests, one JSON object per line, until EOF.
    Blank lines and unparseable lines are skipped. Returns 0."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0
