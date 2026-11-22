"""Stdio MCP server: data_schema and data_pack, capped payloads.

Local only, no network. Payloads carry schema and counts only, never
sample rows.
"""
from __future__ import annotations

import json
import sys

from . import __version__
from .core import analyze
from .pack import build_pack
from .readers import DataError

TOOLS = [
    {"name": "data_schema",
     "description": "Infer the schema of a CSV, TSV, JSON array, "
                    "top-level JSON object, or JSONL file: types, null "
                    "rates, distinct counts, ranges, and redaction "
                    "flags. No sample rows returned.",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string"}},
                     "required": ["path"]}},
    {"name": "data_pack",
     "description": "Build a GhostData pack (manifest, PROMPT.md, bounded "
                    "redacted sample) for a data file.",
     "inputSchema": {"type": "object",
                     "properties": {
                         "path": {"type": "string"},
                         "out": {"type": "string"},
                         "sample": {"type": "integer"}},
                     "required": ["path", "out"]}},
]


def _summary(result):
    """Trim an analyze() result to the MCP summary payload: format,
    counts (malformed examples capped at five), schema, and the
    redaction record. Sample rows are never included."""
    out = {
        "format": result["format"],
        "counts": {k: v for k, v in result["counts"].items()
                   if k != "malformed_examples"},
        "malformed_examples": result["counts"].get(
            "malformed_examples", [])[:5],
        "columns": result["schema"],
        "redacted_columns": result["redacted_columns"],
        "redacted_nested": result.get("redacted_nested", []),
    }
    if result.get("structure") is not None:
        out["structure"] = result["structure"]
    return out


def handle(request: dict):
    """Handle one JSON-RPC request dict and return the response dict.

    Supports initialize, tools/list, and tools/call for the
    data_schema and data_pack tools. Notifications (requests with no
    id) that need no reply return None. Tool arguments accept "path"
    and its alias "file" for the input file.
    """
    method = request.get("method", "")
    rid = request.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ghostdata", "version": __version__}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        try:
            # Accept "file" as an alias for "path": both spellings show
            # up in client calls and the PLAN names neither.
            target = args.get("path") or args.get("file")
            if name == "data_schema":
                payload = _summary(analyze(target))
            elif name == "data_pack":
                manifest = build_pack(
                    target, args["out"],
                    sample_size=int(args.get("sample", 60)))
                payload = {
                    "format": manifest["source"]["format"],
                    "counts": manifest["counts"],
                    "columns": manifest["columns"],
                    "redacted_columns": manifest["redaction"]["columns"],
                    "redacted_nested": manifest["redaction"].get(
                        "nested", []),
                    "tokens": manifest["tokens"],
                    "sample_rows": manifest["sample"]["rows"],
                }
                if "structure" in manifest:
                    payload["structure"] = manifest["structure"]
            else:
                return {"jsonrpc": "2.0", "id": rid, "error": {
                    "code": -32602, "message": "unknown tool: %s" % name}}
        except (DataError, ValueError, KeyError, TypeError,
                AttributeError, OSError) as exc:
            # TypeError/AttributeError cover malformed call arguments
            # (a missing path, a null sample size, non-dict
            # arguments): the caller gets a JSON-RPC error, not an
            # exception escaping handle() (serve() then misreported
            # it as a -32700 parse error).
            return {"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32000, "message": str(exc)}}
        text = json.dumps(payload, indent=2)
        if len(text) > 20000:
            text = text[:20000] + "\n... (truncated)"
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": text}]}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": -32601, "message": "unknown method: %s" % method}}
    return None


def serve(stdin=None, stdout=None) -> None:
    """Serve JSON-RPC requests, one JSON object per line, until the
    input reaches EOF. Local stdio only; nothing is opened on the
    network."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = handle(json.loads(line))
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {
                "code": -32700, "message": str(exc)}}
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
