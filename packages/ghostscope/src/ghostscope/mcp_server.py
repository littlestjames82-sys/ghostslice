"""Stdio MCP server (JSON-RPC), following GhostSlice's pattern.

Tools: scope_pack, scope_explain. Payloads are capped summaries
(no file bodies). Local only. No model calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import __version__
from .pack import explain_from_scope

MAX_FILES = 50
MAX_NOTES = 50

TOOLS = [
    {
        "name": "scope_pack",
        "description": "Build a GhostScope review pack for a local project "
                       "change (git base/head range, staged changes, or a "
                       "diff file) and return a capped summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "out": {"type": "string"},
                "base": {"type": "string"},
                "head": {"type": "string"},
                "staged": {"type": "boolean"},
                "diff": {"type": "string"},
                "fit": {"type": "integer"},
            },
            "required": ["project", "out"],
        },
    },
    {
        "name": "scope_explain",
        "description": "Explain why a file is (or is not) in a GhostScope "
                       "pack: its mode, graph distance, risk score and "
                       "risk reasons.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pack": {"type": "string"},
                "bundle": {"type": "string"},
                "file": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": [],
        },
    },
]


def _capped_scope(scope: dict) -> dict:
    totals = scope.get("totals", {})
    return {
        "totals": totals,
        "changed": [
            {"path": c["path"], "status": c["status"],
             "risk_score": c["risk_score"], "risk_reasons": c["risk_reasons"],
             "lost_covering_tests": c.get("lost_covering_tests", []),
             "symbols": [{"qualified": s["qualified"],
                          "caller_count": s.get("caller_count", 0),
                          "risk_reasons": s.get("risk_reasons", [])}
                         for s in c["symbols"]][:MAX_FILES]}
            for c in scope.get("changed", [])][:MAX_FILES],
        "reading_order": scope.get("reading_order", [])[:MAX_FILES],
        "notes": scope.get("notes", [])[:MAX_NOTES],
        "fit": scope.get("fit"),
        "labels": scope.get("labels", {}),
    }


def tool_scope_pack(args: dict) -> dict:
    """MCP ``scope_pack``: build a pack and return a capped summary.

    Requires ``project`` and ``out`` in ``args``.
    """
    from .gitinput import load_change_input
    from .pack import build_pack
    from .profile import load_scope_profile
    project = args.get("project")
    out = args.get("out")
    if not project or not out:
        raise ValueError("scope_pack requires 'project' and 'out'")
    inp = load_change_input(project, base=args.get("base"),
                            head=args.get("head"),
                            staged=bool(args.get("staged")),
                            diff_file=args.get("diff"))
    result = build_pack(project, out, inp, load_scope_profile(project),
                        fit=args.get("fit"))
    summary = _capped_scope(result["scope"])
    summary["out"] = result["out"]
    summary["fit_ok"] = result["fit_ok"]
    return summary


def tool_scope_explain(args: dict) -> dict:
    """MCP ``scope_explain``: explain a file from a pack's scope.json.

    Requires a pack directory (``pack``, ``bundle``, or ``out``) and
    a file (``file`` or ``path``) in ``args``.
    """
    pack_dir = args.get("pack") or args.get("bundle") or args.get("out")
    file = args.get("file") or args.get("path")
    if not pack_dir or not file:
        raise ValueError("scope_explain requires 'pack' and 'file'")
    scope_path = Path(pack_dir) / "scope.json"
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    return explain_from_scope(scope, file)


_DISPATCH = {"scope_pack": tool_scope_pack, "scope_explain": tool_scope_explain}


def handle_message(msg: dict) -> dict | None:
    """Handle one JSON-RPC message; return the response, or None for notifications."""
    if not isinstance(msg, dict):
        # A well-formed JSON value that is not an object (list,
        # string, number) must get an Invalid Request response,
        # not crash the server with an AttributeError.
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600,
                          "message": "invalid request: expected an object"}}
    method = msg.get("method", "")
    msg_id = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ghostscope", "version": __version__}}}
    if method.startswith("notifications/"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name", "")
        fn = _DISPATCH.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32602, "message": f"unknown tool: {name}"}}
        try:
            result = fn(params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(result, indent=2)}]}}
        except Exception as exc:  # report, never crash the server
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32000, "message": str(exc)[:500]}}
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"unknown method: {method}"}}


def serve() -> int:
    """Serve JSON-RPC requests, one per line, on stdin/stdout until EOF."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            # Answer with a JSON-RPC parse error instead of staying
            # silent, which would leave the client waiting forever.
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": "parse error"}}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0
