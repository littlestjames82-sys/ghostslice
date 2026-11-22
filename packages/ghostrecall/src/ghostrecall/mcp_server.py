"""Stdio MCP server (JSON-RPC), same pattern as GhostSlice's.

Tools: recall_search, recall_bundle, recall_explain.
Payloads are capped: item text is truncated, results are limited.
"""
from __future__ import annotations
import json, sys

from . import __version__
from .bundle import build_bundle
from .profile import load_profile
from .recall import explain, select
from .sources import assert_project_root, collect_items
from .tokens import estimate

MAX_TEXT = 2000
MAX_RESULTS = 20

TOOLS = [
    {"name": "recall_search", "description": "TF-IDF search project memory for a task",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "task": {"type": "string"},
         "limit": {"type": "integer"}}, "required": ["project", "task"]}},
    {"name": "recall_bundle", "description": "Build a combined GhostRecall bundle",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "out": {"type": "string"},
         "task": {"type": "string"}, "fit": {"type": "integer"},
         "slice_bundle": {"type": "string"}}, "required": ["project", "out"]}},
    {"name": "recall_explain", "description": "Explain why an item was or was not selected",
     "inputSchema": {"type": "object", "properties": {
         "project": {"type": "string"}, "task": {"type": "string"},
         "item": {"type": "string"}}, "required": ["project", "task", "item"]}},
]

def _call(name: str, args: dict):
    """Dispatch one MCP tool call and return its JSON-friendly result.

    Raises ValueError for an unknown tool name; serve() turns that
    into a JSON-RPC error instead of crashing.
    """
    if name == "recall_search":
        root = assert_project_root(args["project"])
        profile = load_profile(root)
        items = collect_items(root, include_git=bool(profile.get("include_git", True)),
                              git_limit=int(profile.get("git_limit", 200)))
        selected, not_selected, conflicts = select(items, args["task"], profile)
        out = []
        for e in selected[:MAX_RESULTS]:
            if e["item"].blocked:
                continue  # defence in depth: never preview secret-bearing text
            d = e["item"].to_dict(include_text=False)
            d["score"] = e["score"]; d["pinned"] = e["pinned"]
            d["tokens_estimate"] = estimate(e["item"].text)
            d["text_preview"] = e["item"].text[:MAX_TEXT]
            out.append(d)
        return {"selected": out, "conflicts": conflicts,
                "not_selected_count": len(not_selected)}
    if name == "recall_bundle":
        mf = build_bundle(args["project"], args["out"], task=args.get("task", ""),
                          fit=args.get("fit"), slice_bundle=args.get("slice_bundle"))
        return {"totals": mf["totals"], "items": [i["id"] for i in mf["items"]][:MAX_RESULTS],
                "excluded": len(mf["excluded"]), "conflicts": mf["conflicts"]}
    if name == "recall_explain":
        root = assert_project_root(args["project"])
        profile = load_profile(root)
        items = collect_items(root, include_git=bool(profile.get("include_git", True)),
                              git_limit=int(profile.get("git_limit", 200)))
        return explain(items, args["task"], args["item"], profile)
    raise ValueError(f"unknown tool: {name}")

def serve(stdin=None, stdout=None) -> int:
    """Serve JSON-RPC requests, one per line, until stdin closes.

    Handles initialize, tools/list and tools/call; notifications are
    ignored. Returns 0.
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        method = req.get("method", "")
        result, error = None, None
        try:
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05",
                          "serverInfo": {"name": "ghostrecall", "version": __version__},
                          "capabilities": {"tools": {}}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = req.get("params", {})
                result = {"content": [{"type": "text", "text": json.dumps(
                    _call(params.get("name", ""), params.get("arguments", {})), indent=2)}]}
            elif method.startswith("notifications/"):
                continue
            else:
                error = {"code": -32601, "message": f"method not found: {method}"}
        except Exception as e:  # surfaced as JSON-RPC error, never a crash
            error = {"code": -32000, "message": str(e)}
        if rid is not None:
            resp = {"jsonrpc": "2.0", "id": rid}
            if error:
                resp["error"] = error
            else:
                resp["result"] = result
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()
    return 0
