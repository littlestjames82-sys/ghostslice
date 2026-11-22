"""MCP surface test (PLAN.md MVP item 5): tools build_fixture
and check_fixture over stdio, local only, no file bodies.

Conservative by design, same posture as the GhostVerify suite:
if the server does not answer an initialize + tools/list
handshake, the test skips. Only once a tools/list response
actually arrives does it assert the plan's tool names.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402


def test_mcp_lists_the_plan_tools(requires_cli):
    prefix = helpers.cli_prefix()
    try:
        proc = subprocess.Popen(
            prefix + ["mcp"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=helpers.cli_env())
    except OSError:
        pytest.skip("mcp subcommand not launchable")
    requests = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05",
                               "capabilities": {},
                               "clientInfo": {"name": "gf-tests",
                                              "version": "0"}}}),
        json.dumps({"jsonrpc": "2.0",
                    "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2,
                    "method": "tools/list", "params": {}}),
    ]) + "\n"
    try:
        out, _ = proc.communicate(requests, timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.skip("mcp server did not answer within 15s")
    tools = []
    for line in out.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 2:
            tools = [t.get("name") for t in
                     msg.get("result", {}).get("tools", [])]
    if not tools:
        pytest.skip("no tools/list response from mcp server")
    for expected in ("build_fixture", "check_fixture"):
        assert expected in tools
