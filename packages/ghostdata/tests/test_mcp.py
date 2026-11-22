"""MCP stdio handshake (PLAN.md MVP 5): initialize, tools/list, and a
data_schema call whose payload carries no planted sensitive values
and no sample rows."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from conftest import CANARIES, ROOT, requires_core


def _mcp_session(requests, timeout=60):
    env = dict(os.environ)
    src = ROOT / "src"
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "ghostdata", "mcp"],
        input="".join(json.dumps(r) + "\n" for r in requests),
        env=env, capture_output=True, text=True, timeout=timeout)
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()
            if line.strip()]


@requires_core
def test_mcp_initialize_and_tools_list():
    replies = _mcp_session([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list",
         "params": {}},
    ])
    by_id = {r["id"]: r for r in replies}
    assert 1 in by_id and 2 in by_id
    names = {t["name"] for t in by_id[2]["result"]["tools"]}
    assert names == {"data_schema", "data_pack"}


@requires_core
def test_mcp_data_schema_payload_has_no_canaries(people_csv):
    replies = _mcp_session([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "data_schema",
                    "arguments": {"path": str(people_csv)}}},
    ])
    by_id = {r["id"]: r for r in replies}
    payload = json.dumps(by_id[2])
    for canary in CANARIES:
        assert canary not in payload
    assert "people.csv" in payload or "integer" in payload
