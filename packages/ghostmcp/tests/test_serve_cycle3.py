"""Cycle 3 daemon behaviors: per-server drop (I1),
idle reaping (I13) and session age/idle fields (I15).

Uses a tiny stdio MCP fixture written into tmp_path so
the tests are hermetic.
"""
import json
import sys
import time

from ghostmcp import serve

FIXTURE = r'''
import json, sys
for line in sys.stdin:
    try:
        req = json.loads(line)
    except Exception:
        continue
    if "id" not in req:
        continue
    m = req.get("method", "")
    if m == "initialize":
        res = {"protocolVersion": "2024-11-05",
               "capabilities": {},
               "serverInfo": {"name": "fx", "version": "0"}}
    elif m == "tools/list":
        res = {"tools": [{"name": "echo", "description": "",
                          "inputSchema": {"type": "object"}}]}
    elif m == "tools/call":
        res = {"content": [{"type": "text", "text": "echoed"}],
               "isError": False}
    else:
        res = {}
    sys.stdout.write(json.dumps(
        {"jsonrpc": "2.0", "id": req["id"], "result": res}) + "\n")
    sys.stdout.flush()
'''


def _daemon(tmp_path):
    fx = tmp_path / "fx.py"
    fx.write_text(FIXTURE)
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"fx": {
        "command": sys.executable, "args": [str(fx)]}}}))
    return serve._Daemon(str(cfg))


def test_sessions_carry_age_and_idle(tmp_path):
    d = _daemon(tmp_path)
    d.handle({"verb": "tools", "server": "fx"})
    s = d.handle({"verb": "sessions"})["sessions"]
    assert len(s) == 1
    assert s[0]["server"] == "fx" and s[0]["calls"] == 1
    assert s[0]["age_s"] >= 0 and s[0]["idle_s"] >= 0
    d.handle({"verb": "shutdown"})


def test_drop_closes_only_that_session(tmp_path):
    d = _daemon(tmp_path)
    d.handle({"verb": "tools", "server": "fx"})
    assert d.handle({"verb": "drop", "server": "fx"}) == {
        "ok": True}
    assert d.handle({"verb": "sessions"})["sessions"] == []
    # and the server can come straight back
    out = d.handle({"verb": "tools", "server": "fx"})
    assert out["tools"][0]["name"] == "echo"
    d.handle({"verb": "shutdown"})


def test_idle_sessions_are_reaped(tmp_path, monkeypatch):
    monkeypatch.setattr(serve, "IDLE_LIMIT_S", 0.05)
    d = _daemon(tmp_path)
    d.handle({"verb": "tools", "server": "fx"})
    time.sleep(0.08)
    assert d.handle({"verb": "sessions"})["sessions"] == []
    d.handle({"verb": "shutdown"})
