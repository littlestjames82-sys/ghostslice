"""MCP server for GhostSlice: stdio JSON-RPC, stdlib only.

Same pattern family as the Ghost Hands MCP server: newline-delimited
JSON-RPC 2.0 over stdin/stdout, no network, no extra dependencies.

Tools:
  scan_project   {path}                          -> scan totals + per-file tokens + recommendations
  slice_file     {path, file, mode}              -> sliced text + before/after token estimates
  estimate_cost  {path, model?}                  -> pre-flight cost for the default selection
  lint_project   {path, strict?}                 -> context-lint findings (rules L001-L010) + exit code
  check_secrets  {path}                          -> redacted secret findings (metadata only)
  project_graph  {path}                          -> import/entry graph summary (capped, v1.0.5)
  project_history {path, model?, since?, top?}   -> savings-ledger analytics (capped, v1.0.5)
  doctor         {path}                          -> the doctor checks as data (read-only, v1.0.5)
  export_bundle  {path, out, preset?}            -> writes a bundle, returns manifest totals

Parity rule (v1.0.5): the MCP surface carries the CLI's read-only
project insights; stateful or writing operations stay CLI-only
(watch, serve, init, redact, cache clear, report/completions file
output). The aggregate gates (ci, check-budget) are compositions
of tools already here (lint_project, check_secrets, estimate_cost)
plus an exit code, so they stay CLI-only too. Payloads are
summaries with caps, never raw dumps: project_history omits the
ledger's raw record list and caps per-run detail, project_graph
caps its per-file adjacency list — both report totals and a
truncation flag when a cap engages.

Token counts are estimates (see tokens.py); prices are the local dated
prices.json, never live.

Plugins (v0.23): tools that scan, slice, lint, estimate, or export
honour the project's profile "plugins" entries — the profile is
the only loading point for MCP (there is no --plugin flag here).
A profile plugin that fails to LOAD surfaces as that tool call's
error result; a plugin failing on ONE file degrades per plugins.py's
failure discipline (full text + a manifest "plugin_errors" entry
on export).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import __version__
from . import plugins as _plugins
from .exporter import build_bundle, estimate_context_tokens
from .graph import (build_graph, find_entry_points, importers_of,
                    reachable_from, recommendations)
from .pricing import estimate_cost, get_model, load_prices
from .profile import PRESETS, load_profile
from .scanner import scan
from .slicer import MODES, slice_text
from .tokens import METHOD as TOKEN_METHOD
from .textio import read_text as _gs_read_text

PROTOCOL_VERSION = "2024-11-05"

# Payload caps for the v1.0.5 insight tools (see the module
# docstring's parity rule): summaries, never raw dumps.
GRAPH_FILE_CAP = 100        # per-file adjacency rows in project_graph
GRAPH_LIST_CAP = 100        # entry/external/unreachable list rows
HISTORY_RUN_CAP = 50        # per-run detail rows in project_history

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
        "name": "project_graph",
        "description": "Import/entry graph summary for a project: entry points, per-file imports/importers/external dependencies (most-imported files first, capped at 100 files with totals and a truncation flag), total edge count, and files unreachable from the entry points. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "project_history",
        "description": "Savings-ledger analytics for a project (the `history` payload): run totals, aggregates with p50/p90 percentiles, best/worst runs, and estimated dollars saved at the model's input rate from the local dated prices.json. since takes an ISO date, an ISO datetime, or a relative form like 7d; top keeps only the N largest-savings runs. The raw ledger records are omitted and per-run detail is capped at the 50 most recent runs (totals and a truncation flag report the cap). A project with no ledger returns zero runs, not an error.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "model": {"type": "string", "default": "claude-sonnet"},
                "since": {"type": "string",
                          "description": "ISO date, ISO datetime, or relative Nd (e.g. 7d)"},
                "top": {"type": "integer", "minimum": 1,
                        "description": "keep only the N runs with the largest savings"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "doctor",
        "description": "The `doctor` health checks for a project, as data: Python runtime, GhostSlice version, estimator stamp, price table, profile, content cache, savings ledger, profile plugins (loaded to verify, exactly as any command loads them), git hygiene, and workspace detection — each ok/warn/fail with a one-line remedy. Doctor never writes; the remedies are text, not actions.",
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
                "redact": {"type": "boolean",
                           "description": "replace flagged secret values in slices "
                                          "with [REDACTED:...] placeholders "
                                          "(default: the profile setting)"},
                "symbols": {"type": "array", "items": {"type": "string"},
                            "description": "symbol-level selection (v0.18): names, "
                                           "Class.method qualified names, file.py:name "
                                           "scoping, or * globs; matched files ship with "
                                           "those symbols' bodies plus signature "
                                           "context, other files are excluded (profile "
                                           "entry points keep their mode). An entry "
                                           "matching nothing is an error."},
            },
            "required": ["path", "out"],
        },
    },
]


def _project_plugins(path):
    """The plugin set a project's profile names (v0.23). MCP has no
    --plugin flag: the profile is the only loading point here, and
    it is the project's own standing opt-in."""
    profile = load_profile(path)
    return profile, _plugins.load_for_project(path, profile=profile)


def _scan_project(args: dict) -> dict:
    profile, pset = _project_plugins(args["path"])
    with _plugins.activated(pset):
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
    source = _gs_read_text(abspath)
    _, pset = _project_plugins(root)
    with _plugins.activated(pset):
        out = slice_text(rel, source,
                         args.get("mode", "signatures")).to_dict()
    if pset.errors:
        out["plugin_errors"] = list(pset.errors)
    return out


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
                            preset=args.get("preset", "claude-code"),
                            redact=args.get("redact"),
                            symbols=args.get("symbols"))
    out = {
        "bundle": str(Path(args["out"]).resolve()),
        "preset": manifest.get("preset"),
        "files": len(manifest["files"]),
        "total_original_tokens": manifest["total_original_tokens"],
        "total_sliced_tokens": manifest["total_sliced_tokens"],
        "total_saved_tokens": manifest["total_saved_tokens"],
    }
    if manifest.get("redaction"):
        out["redaction"] = manifest["redaction"]
    if manifest.get("symbols"):
        out["symbols"] = manifest["symbols"]
    if manifest.get("plugins"):
        out["plugins"] = manifest["plugins"]
    if manifest.get("plugin_errors"):
        out["plugin_errors"] = manifest["plugin_errors"]
    return out


def _check_secrets(args: dict) -> dict:
    from .secrets_scan import scan_path
    findings = scan_path(args["path"])
    return {"findings": findings, "count": len(findings),
            "note": "values redacted to first 4 characters; pattern types only"}


def _lint_project(args: dict) -> dict:
    from .lint import lint_exit_code, lint_project
    profile, pset = _project_plugins(args["path"])
    with _plugins.activated(pset):
        payload = lint_project(args["path"], profile=profile)
    payload = dict(payload)
    if pset.errors:
        payload["plugin_errors"] = list(pset.errors)
    payload["exit_code"] = lint_exit_code(payload, strict=bool(args.get("strict")))
    return payload


def _project_graph(args: dict) -> dict:
    profile, pset = _project_plugins(args["path"])
    with _plugins.activated(pset):
        matcher = profile.is_ignored if profile.path else None
        result = scan(args["path"], ignore_matcher=matcher)
        graph = build_graph(result)
    entries = find_entry_points(result, profile)
    rev = importers_of(graph)
    reachable = reachable_from(entries, graph) if entries else set()
    by_path = {f.path: f for f in result.files}
    files = [{
        "path": path,
        "tokens": by_path[path].tokens if path in by_path else 0,
        "imports": graph[path]["imports"],
        "importers": rev.get(path, []),
        "external": graph[path]["external"],
    } for path in sorted(graph,
                         key=lambda p: (-len(rev.get(p, [])), p))]
    external_all = sorted({e for d in graph.values()
                           for e in d["external"]})
    unreachable = sorted(p for p in graph
                         if entries and p not in reachable
                         and p not in entries)
    return {
        "root": result.root,
        "file_count": len(result.files),
        "edge_count": sum(len(d["imports"]) for d in graph.values()),
        "token_method": TOKEN_METHOD,
        "entry_points": entries,
        "external_dependencies": external_all[:GRAPH_LIST_CAP],
        "external_dependencies_total": len(external_all),
        "external_dependencies_truncated":
            len(external_all) > GRAPH_LIST_CAP,
        "unreachable": unreachable[:GRAPH_LIST_CAP],
        "unreachable_total": len(unreachable),
        "unreachable_truncated": len(unreachable) > GRAPH_LIST_CAP,
        "files": files[:GRAPH_FILE_CAP],
        "files_total": len(files),
        "files_truncated": len(files) > GRAPH_FILE_CAP,
    }


def _project_history(args: dict) -> dict:
    from .ledger import analytics, parse_since
    prices = load_prices()
    profile = load_profile(args["path"])
    model = get_model(prices,
                      args.get("model") or profile.model
                      or "claude-sonnet")
    since = parse_since(args["since"]) if args.get("since") else None
    data = dict(analytics(args["path"], model=model, prices=prices,
                          since=since, top=args.get("top")))
    # The summary block carries the ledger's raw record list; the
    # MCP surface ships the derived analytics, not the raw dump.
    data.pop("records", None)
    detail = data.get("runs_detail", [])
    if len(detail) > HISTORY_RUN_CAP:
        data["runs_detail"] = detail[-HISTORY_RUN_CAP:]
        data["runs_detail_truncated"] = True
        data["runs_detail_total"] = len(detail)
    return data


def _doctor(args: dict) -> dict:
    # run_doctor is read-only by contract (its module docstring:
    # "Doctor NEVER writes"); its plugins check loads the profile's
    # plugins to verify them, the same standing opt-in every other
    # tool here already runs under.
    from .doctor import run_doctor
    return run_doctor(args["path"])


_DISPATCH = {
    "scan_project": _scan_project,
    "slice_file": _slice_file,
    "estimate_cost": _estimate_cost,
    "export_bundle": _export_bundle,
    "check_secrets": _check_secrets,
    "lint_project": _lint_project,
    "project_graph": _project_graph,
    "project_history": _project_history,
    "doctor": _doctor,
}


def handle_message(msg: dict) -> dict | None:
    """Pure JSON-RPC handler (testable without stdio)."""
    if not isinstance(msg, dict):
        return None  # v0.21: non-object JSON is not a request
    method = msg.get("method") or ""
    if not isinstance(method, str):
        method = ""
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
        if not isinstance(params, dict):
            params = {}
        name = params.get("name", "")
        if not isinstance(name, str):
            name = ""
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
        if not isinstance(msg, dict):
            continue  # v0.21: a JSON scalar/array line is not a request
        resp = handle_message(msg)
        if resp is not None:
            outstream.write(json.dumps(resp) + "\n")
            outstream.flush()
