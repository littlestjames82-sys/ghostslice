"""MCP server for GhostReview: stdio JSON-RPC, stdlib only.

Same pattern as the GhostSlice / GhostVerify MCP servers:
newline-delimited JSON-RPC 2.0 over stdin/stdout, no network. The
tool returns a capped summary (no diff text, no file bodies).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import __version__
from .core import build_review
from .inputs import diff_from_file, diff_from_git

PROTOCOL_VERSION = "2024-11-05"
RISK_CAP = 50
CHANGE_CAP = 50
DEPENDENT_CAP = 50

TOOLS = [
    {"name": "review_diff",
     "description": "Plain-English verdict summary of a change: what changed, symbols touched, one-hop dependents, risk flags, and citations of a supplied GhostVerify report / GhostScope pack. Static evidence only, no file bodies, no diff text. Translation only: it invents no findings and approves nothing. 'project' is required; 'diff' is a diff file path ('-' for stdin), otherwise the git working tree is used, or staged changes when 'staged' is true.",
     "inputSchema": {"type": "object",
                     "properties": {"project": {"type": "string"},
                                    "diff": {"type": "string"},
                                    "staged": {"type": "boolean", "default": False},
                                    "verify_report": {"type": "string"},
                                    "scope_pack": {"type": "string"}},
                     "required": ["project"]}},
]


def _capped(report: dict) -> dict:
    """Copy *report* with risks, changes, and dependents capped.

    Truncation is marked with ``*_truncated`` / ``*_total`` fields so
    a caller can tell the payload was capped. No diff text or file
    bodies are ever added.
    """
    out = dict(report)
    risks = out.get("risks") or []
    if len(risks) > RISK_CAP:
        out["risks"] = risks[:RISK_CAP]
        out["risks_truncated"] = True
        out["risks_total"] = len(risks)
    # The pre-polish cap trimmed risks only; a large diff could
    # still return hundreds of change rows and dependent lists.
    changes = out.get("changes") or []
    if len(changes) > CHANGE_CAP:
        out["changes"] = changes[:CHANGE_CAP]
        out["changes_truncated"] = True
        out["changes_total"] = len(changes)
    deps = out.get("dependents")
    if isinstance(deps, dict):
        trimmed = {}
        any_trimmed = False
        for key, entry in deps.items():
            entry = dict(entry or {})
            lst = entry.get("dependents") or []
            if len(lst) > DEPENDENT_CAP:
                entry["dependents"] = lst[:DEPENDENT_CAP]
                entry["dependents_truncated"] = True
                entry["dependents_total"] = len(lst)
                any_trimmed = True
            trimmed[key] = entry
        out["dependents"] = trimmed
        if any_trimmed:
            out["dependents_truncated"] = True
    return out


def _review_diff(args) -> dict:
    """Run one ``review_diff`` call: diff from a file, or from git."""
    notes = []
    if args.get("diff"):
        text, source = diff_from_file(args["diff"])
    else:
        text, source, notes = diff_from_git(Path(args["project"]),
                                            staged=bool(args.get("staged")))
    return _capped(build_review(args["project"], text, source,
                                verify_report=args.get("verify_report"),
                                scope_pack=args.get("scope_pack"),
                                extra_notes=notes))


def _dispatch(request: dict):
    """Handle one JSON-RPC request; notifications return ``None``."""
    method = request.get("method", "")
    params = request.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ghostreview",
                               "version": __version__}}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name != "review_diff":
            raise ValueError(f"unknown tool: {name}")
        result = _review_diff(arguments)
        return {"content": [{"type": "text",
                             "text": json.dumps(result, indent=2)}]}
    raise ValueError(f"unknown method: {method}")


def serve(stdin=None, stdout=None) -> int:
    """Serve newline-delimited JSON-RPC on stdio until EOF; returns 0."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        if not isinstance(request, dict):
            # Valid JSON but not a request object: answer with an
            # invalid-request error instead of dying on .get and
            # taking the whole server down with it.
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32600,
                              "message": "invalid request: expected "
                                         "a JSON object"}}
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()
            continue
        try:
            result = _dispatch(request)
        except Exception as exc:  # report as JSON-RPC error, keep serving
            resp = {"jsonrpc": "2.0", "id": request.get("id"),
                    "error": {"code": -32000, "message": str(exc)}}
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()
            continue
        if result is not None and request.get("id") is not None:
            resp = {"jsonrpc": "2.0", "id": request.get("id"),
                    "result": result}
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()
    return 0
