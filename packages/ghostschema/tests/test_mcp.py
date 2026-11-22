"""MCP stdio tests (PLAN MVP item 6): schema_slice / schema_inspect.

Skipped unless the CLI advertises an mcp subcommand, so the suite
tracks the core's actual surface instead of guessing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from conftest import requires_cli
from helpers import PETSTORE, find_cli


def _mcp_supported() -> bool:
    prefix, env_extra = find_cli()
    if prefix is None:
        return False
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(prefix + ["--help"], capture_output=True,
                              text=True, timeout=30, env=env)
    except Exception:
        return False
    return "mcp" in (proc.stdout + proc.stderr).lower()


pytestmark = pytest.mark.skipif(
    not _mcp_supported(), reason="core does not advertise an mcp subcommand")


@requires_cli
def test_mcp_initialize_and_tools_list(tmp_path):
    prefix, env_extra = find_cli()
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.Popen(
        prefix + ["mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, env=env)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "ghostschema-tests",
                                   "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    payload = "".join(json.dumps(r) + "\n" for r in requests)
    out, _ = proc.communicate(payload, timeout=60)
    responses = [json.loads(line) for line in out.splitlines() if line.strip()]
    by_id = {r.get("id"): r for r in responses if r.get("id") is not None}
    assert 1 in by_id and "result" in by_id[1], responses
    assert 2 in by_id and "result" in by_id[2], responses
    tools = by_id[2]["result"].get("tools", [])
    names = {t.get("name") for t in tools}
    assert "schema_slice" in names and "schema_inspect" in names, names


@requires_cli
def test_mcp_schema_inspect_returns_summary_only(tmp_path):
    prefix, env_extra = find_cli()
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.Popen(
        prefix + ["mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, env=env)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "ghostschema-tests",
                                   "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "schema_inspect",
                    "arguments": {"path": str(PETSTORE)}}},
    ]
    payload = "".join(json.dumps(r) + "\n" for r in requests)
    out, _ = proc.communicate(payload, timeout=60)
    responses = [json.loads(line) for line in out.splitlines() if line.strip()]
    by_id = {r.get("id"): r for r in responses if r.get("id") is not None}
    assert 2 in by_id, responses
    result = by_id[2].get("result", {})
    text = json.dumps(result)
    # Summary payloads carry listings, not spec bodies: the fixture's
    # long description text must not be inlined wholesale.
    assert "Planted waste: internal audit shape" not in text
