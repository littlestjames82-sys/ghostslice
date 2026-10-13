"""MCP server for GhostSlice: stdio JSON-RPC, stdlib only.

Same pattern family as the Ghost Hands MCP server: newline-delimited
JSON-RPC 2.0 over stdin/stdout, no network, no extra dependencies.

Tools:
  scan_project   {path}                          -> scan totals + per-file tokens + recommendations
  slice_file     {path, file, mode}              -> sliced text + before/after token estimates
  estimate_cost  {path, model?}                  -> pre-flight cost for the default selection
  lint_project   {path, strict?}                 -> context-lint findings (rules L001-L010) + exit code
  export_bundle  {path, out, preset?}            -> writes a bundle, returns manifest totals

Token counts are estimates (see tokens.py); prices are the local dated
prices.json, never live.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import __version__
from .exporter import build_bundle, estimate_context_tokens
from .graph import build_graph, recommendations
from .pricing import estimate_cost, get_model, load_prices
from .profile import PRESETS, load_profile
from .scanner import scan
from .slicer import MODES, slice_text
from .tokens import METHOD as TOKEN_METHOD

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "scan_project",
        "description": "Scan a project: per-file estimated token costs, totals, and prune recommendations.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "slice_file",
        "description": "Slice one file (modes: full, signatures, interfaces, strip-tests, exclude) and return the sliced text with before/after estimated tokens.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "project root"},
                "file": {"type": "string", "description": "file path, relative to the project root or absolute"},
                "mode": {"type": "string", "enum": list(MODES), "default": "signatures"},
            },
            "required": ["path", "file"],
        },
    },
    {
        "name": "estimate_cost",
        "description": "Pre-flight input cost estimate for the project's default sliced selection, using the local dated prices.json.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "model": {"type": "string", "default": "claude-sonnet"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "lint_project",
        "description": "Lint a project's default export selection for context waste (rules L001-L010: oversize files, full-mode slicable code, dead weight, duplicates, secrets, giant lines, generated files, tests, lockfiles, tiny-file noise). Findings carry estimated token costs; secret findings are metadata only. Returns the lint payload plus an exit_code field (1 on any error finding, or on warnings when strict is true).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "strict": {"type": "boolean", "default": False},
            },
            "required": ["path"],
        },
    },
    {
        "name": "check_secrets",
        "description": "Scan a project for likely secrets in files that would be exported. Findings are redacted (path, line, pattern type only).",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "export_bundle",
        "description": "Export a context bundle (manifest.json, PROMPT.md, sliced files) for a project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "out": {"type": "string"},
                "preset": {"type": "string", "enum": list(PRESETS),
                           "default": "claude-code"},
            },
            "required": ["path", "out"],
        },
    },
]


def _scan_project(args: dict) -> dict:
    profile = load_profile(args["path"])
    matcher = profile.is_ignored if profile.path else None
    result = scan(args["path"], ignore_matcher=matcher)
    graph = build_graph(result)
    return {
        "root": result.root,
        "file_count": len(result.files),
        "total_tokens": result.total_tokens,
        "token_method": TOKEN_METHOD,
        "files": [{k: v for k, v in f.to_dict().items() if k != "abspath"}
                  for f in result.files],
        "recommendations": recommendations(result, graph, profile),
    }


def _slice_file(args: dict) -> dict:
    root = Path(args["path"]).resolve()
    file_arg = Path(args["file"])
    abspath = file_arg if file_arg.is_absolute() else root / file_arg
    rel = str(abspath.relative_to(root)) if abspath.is_relative_to(root) else abspath.name
    source = abspath.read_text(encoding="utf-8", errors="replace")
    return slice_text(rel, source, args.get("mode", "signatures")).to_dict()


def _estimate_cost(args: dict) -> dict:
    prices = load_prices()
    profile = load_profile(args["path"])
    model = get_model(prices, args.get("model") or profile.model or "claude-sonnet")
    before, after = estimate_context_tokens(args["path"], profile=profile)
    return {
        "model": model["id"],
        "model_name": model.get("name", model["id"]),
        "prices_as_of": prices.get("as_of"),
        "prices_note": "Local prices.json, not live.",
        "before_tokens": before,
        "after_tokens": after,
        "saved_tokens": before - after,
        "before_cost_usd": round(estimate_cost(before, model), 4),
        "after_cost_usd": round(estimate_cost(after, model), 4),
    }


def _export_bundle(args: dict) -> dict:
    profile = load_profile(args["path"])
    manifest = build_bundle(args["path"], args["out"], profile=profile,
                            preset=args.get("preset", "claude-code"))
    return {
        "bundle": str(Path(args["out"]).resolve()),
        "preset": manifest.get("preset"),
        "files": len(manifest["files"]),
        "total_original_tokens": manifest["total_original_tokens"],
        "total_sliced_tokens": manifest["total_sliced_tokens"],
        "total_saved_tokens": manifest["total_saved_tokens"],
    }


def _check_secrets(args: dict) -> dict:
    from .secrets_scan import scan_path
    findings = scan_path(args["path"])
    return {"findings": findings, "count": len(findings),
            "note": "values redacted to first 4 characters; pattern types only"}


def _lint_project(args: dict) -> dict:
    from .lint import lint_exit_code, lint_project
    profile = load_profile(args["path"])
    payload = lint_project(args["path"], profile=profile)
    payload = dict(payload)
    payload["exit_code"] = lint_exit_code(payload, strict=bool(args.get("strict")))
    return payload


_DISPATCH = {
    "scan_project": _scan_project,
    "slice_file": _slice_file,
    "estimate_cost": _estimate_cost,
    "export_bundle": _export_bundle,
    "check_secrets": _check_secrets,
    "lint_project": _lint_project,
}


def handle_message(msg: dict) -> dict | None:
    """Pure JSON-RPC handler (testable without stdio)."""
    method = msg.get("method", "")
    msg_id = msg.get("id")
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ghostslice", "version": __version__},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name", "")
        fn = _DISPATCH.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32602, "message": f"unknown tool: {name}"}}
        try:
            payload = fn(params.get("arguments") or {})
            text = json.dumps(payload, indent=2)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as exc:
            result = {"content": [{"type": "text", "text": f"error: {exc}"}],
                      "isError": True}
    else:
        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"method not found: {method}"}}
    if msg_id is None:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def run_stdio(instream=None, outstream=None) -> None:
    instream = instream or sys.stdin
    outstream = outstream or sys.stdout
    for line in instream:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_message(msg)
        if resp is not None:
            outstream.write(json.dumps(resp) + "\n")
            outstream.flush()
