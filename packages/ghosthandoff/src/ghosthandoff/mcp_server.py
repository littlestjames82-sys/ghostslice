"""Stdio MCP server for GhostHandoff. Local only, no network.

Run it with ``ghosthandoff mcp``; it speaks newline-delimited
JSON-RPC on stdin/stdout and handles ``initialize``, ``ping``,
``tools/list``, and ``tools/call``.

Tools:
- build_handoff: build a pack, return capped summary counts + pack paths.
  Arguments: ``project`` (required), ``out``, ``since``, ``base``.
- read_handoff: return a pack's HANDOFF.md, capped at 8000 characters.
  Argument: ``pack_dir`` (required).

Payloads never include project file bodies; HANDOFF.md is itself the
capped, redacted, extractive summary. Building a pack through MCP
follows the same rules as the CLI: propose-only, writes only the two
pack files into the output directory.
"""
from __future__ import annotations

import json
import os
import sys

from . import __version__
from .pack import write_pack

MAX_MD_CHARS = 8000

TOOLS = [
    {
        "name": "build_handoff",
        "description": "Build a session handoff pack (HANDOFF.md + handoff.json) for a "
                       "project from repo facts. Propose-only: writes only the pack files "
                       "into the output directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "project directory"},
                "out": {"type": "string", "description": "output directory (default ./handoff-out)"},
                "since": {"type": "string", "description": "duration (2h), ISO time, or git ref"},
                "base": {"type": "string", "description": "optional ref for diff stats"},
            },
            "required": ["project"],
        },
    },
    {
        "name": "read_handoff",
        "description": "Read a built pack's HANDOFF.md (capped at 8000 characters).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pack_dir": {"type": "string", "description": "directory containing HANDOFF.md"},
            },
            "required": ["pack_dir"],
        },
    },
]


def _result(req_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _text_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call_tool(name: str, arguments: dict) -> dict:
    """Dispatch one MCP tool call and return its text result payload.

    Unknown tools, a missing project directory, and an unwritable
    pack all come back as error results (``isError``) rather than
    exceptions, so the client session stays alive.
    """
    if name == "build_handoff":
        project = arguments.get("project", "")
        if not os.path.isdir(project):
            return _text_result(f"project path is not a directory: {project}", is_error=True)
        out_dir = arguments.get("out") or os.path.join(os.getcwd(), "handoff-out")
        try:
            data = write_pack(project, out_dir, since=arguments.get("since"),
                              base=arguments.get("base"))
        except (FileExistsError, OSError) as exc:
            return _text_result(f"could not build pack: {exc}", is_error=True)
        git = data.get("git") or {}
        summary = {
            "pack_markdown": data["pack"]["markdown"],
            "pack_json": data["pack"]["json"],
            "git_available": bool(git.get("available")),
            "commits_in_window": git.get("commit_count", 0),
            "files_touched": git.get("files_changed_total", 0),
            "markers": (data.get("markers") or {}).get("total", 0),
            "open_loops": [lp["kind"] for lp in data.get("open_loops", [])],
            "next_steps": len(data.get("next_steps", [])),
        }
        return _text_result(json.dumps(summary, indent=2))
    if name == "read_handoff":
        pack_dir = arguments.get("pack_dir", "")
        md_path = os.path.join(pack_dir, "HANDOFF.md")
        if not os.path.isfile(md_path):
            return _text_result(f"no HANDOFF.md in {pack_dir}", is_error=True)
        with open(md_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if len(text) > MAX_MD_CHARS:
            text = text[:MAX_MD_CHARS] + "\n[truncated by GhostHandoff MCP cap]\n"
        return _text_result(text)
    return _text_result(f"unknown tool: {name}", is_error=True)


def handle(request: dict) -> dict | None:
    """Handle one JSON-RPC request dict; ``None`` means no reply (notification)."""
    method = request.get("method", "")
    req_id = request.get("id")
    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ghosthandoff", "version": __version__},
        })
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        params = request.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            return _result(req_id, _call_tool(params.get("name", ""), arguments))
        except Exception as exc:
            # One malformed call must not kill the server: answer it
            # with an error result and keep serving later requests.
            return _result(req_id, _text_result(
                f"tool call failed: {exc}", is_error=True))
    if req_id is not None:
        return _error(req_id, -32601, f"method not found: {method}")
    return None


def serve(stdin=None, stdout=None) -> None:
    """Serve newline-delimited JSON-RPC until stdin reaches EOF."""
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
            continue  # valid JSON, but not a request object: skip it
        response = handle(request)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
