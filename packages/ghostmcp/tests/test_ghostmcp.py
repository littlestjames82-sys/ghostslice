"""GhostMCP tests: the CLI contract against two fixture MCP
servers built here — a stdio JSON-RPC server script (spawned
per invocation, like real use) and a stdlib http.server
implementing the Streamable-HTTP-style POST flow with an
Mcp-Session-Id. No network beyond loopback, stdlib only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
SECRET_VALUE = "do-not-print-this-value"

TOOLS = [
    {"name": "echo", "description": "Echo back the text argument.",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string"}},
                     "required": ["text"]}},
    {"name": "add", "description": "Add two numbers.",
     "inputSchema": {"type": "object",
                     "properties": {"a": {"type": "number"},
                                    "b": {"type": "number"}},
                     "required": ["a", "b"]}},
    {"name": "fail",
     "description": "Always returns an error result.",
     "inputSchema": {"type": "object", "properties": {}}},
]

FIXTURE_SERVER = r'''
import json
import sys

TOOLS = json.loads(r"""__TOOLS_JSON__""")


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "serverInfo": {"name": "fixture", "version": "1.0.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid,
                "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            result = {"content": [{"type": "text",
                      "text": str(args.get("text", ""))}],
                      "isError": False}
        elif name == "add":
            result = {"content": [{"type": "text", "text": str(
                args.get("a", 0) + args.get("b", 0))}],
                "isError": False}
        elif name == "fail":
            result = {"content": [{"type": "text",
                      "text": "it broke on purpose"}],
                      "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32602, "message": "unknown tool"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "resources": [
                {"uri": "note://hello", "name": "Hello note",
                 "mimeType": "text/plain",
                 "description": "A small text resource."},
                {"uri": "blob://pic", "name": "Picture",
                 "mimeType": "image/png"}]}}
    if method == "resources/read":
        uri = (msg.get("params") or {}).get("uri")
        if uri == "note://hello":
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "contents": [{"uri": uri,
                              "mimeType": "text/plain",
                              "text": "hello resource"}]}}
        if uri == "blob://pic":
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "contents": [{"uri": uri,
                              "mimeType": "image/png",
                              "blob": "QkxPQkJBU0U2NA=="}]}}
        return {"jsonrpc": "2.0", "id": mid, "error": {
            "code": -32602, "message": "unknown resource"}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "prompts": [{"name": "greet",
                         "description": "Greet someone.",
                         "arguments": [
                             {"name": "who", "required": True},
                             {"name": "tone",
                              "required": False}]}]}}
    if method == "prompts/get":
        params = msg.get("params") or {}
        who = (params.get("arguments") or {}).get("who", "?")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "description": "Greet someone.",
            "messages": [{"role": "user", "content": {
                "type": "text",
                "text": "Say hello to " + str(who) + "."}}]}}
    if mid is None:
        return None  # a notification: no reply
    return {"jsonrpc": "2.0", "id": mid, "error": {
        "code": -32601, "message": "method not found"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


main()
'''.replace("__TOOLS_JSON__", json.dumps(TOOLS))


def run_cli(*argv):
    """Run the CLI exactly as GhostIDE will; return
    (exit_code, parsed_stdout, raw_stdout)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    r = subprocess.run(
        [sys.executable, "-m", "ghostmcp", *argv],
        capture_output=True, text=True, env=env, timeout=60,
        stdin=subprocess.DEVNULL)
    return r.returncode, json.loads(r.stdout), r.stdout


@pytest.fixture()
def stdio_config(tmp_path):
    server_py = tmp_path / "fixture_server.py"
    server_py.write_text(FIXTURE_SERVER)
    config = {"mcpServers": {
        "fixture": {"command": sys.executable,
                    "args": [str(server_py)],
                    "env": {"FIXTURE_SECRET": SECRET_VALUE,
                            "FIXTURE_FLAG": "1"}},
        "remote": {"url": "http://127.0.0.1:9/never-connected"},
    }}
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps(config))
    return path


# ---------------------------------------------------------------
# servers verb

def test_servers_lists_stdio_and_http_without_connecting(
        stdio_config):
    code, out, raw = run_cli("servers", "--config", str(stdio_config))
    assert code == 0
    assert out["config"] == str(stdio_config)
    by_name = {s["name"]: s for s in out["servers"]}
    assert by_name["fixture"]["transport"] == "stdio"
    assert "fixture_server.py" in by_name["fixture"]["target"]
    assert by_name["remote"]["transport"] == "http"
    assert by_name["remote"]["target"] == \
        "http://127.0.0.1:9/never-connected"
    # env names only, never values, nowhere in the output
    assert by_name["fixture"]["env_names"] == [
        "FIXTURE_FLAG", "FIXTURE_SECRET"]
    assert SECRET_VALUE not in raw


def test_servers_missing_config(tmp_path):
    code, out, _ = run_cli(
        "servers", "--config", str(tmp_path / "nope.json"))
    assert code == 2
    assert "not found" in out["error"]


# ---------------------------------------------------------------
# stdio: tools + call

def test_tools_over_stdio(stdio_config):
    code, out, _ = run_cli("tools", "--config", str(stdio_config),
                           "--server", "fixture")
    assert code == 0
    assert out["server"] == "fixture"
    names = {t["name"] for t in out["tools"]}
    assert names == {"echo", "add", "fail"}
    echo = next(t for t in out["tools"] if t["name"] == "echo")
    assert echo["inputSchema"]["required"] == ["text"]


def test_call_echo(stdio_config):
    code, out, _ = run_cli(
        "call", "--config", str(stdio_config), "--server",
        "fixture", "--tool", "echo", "--args",
        json.dumps({"text": "hello mcp"}))
    assert code == 0
    assert out == {"server": "fixture", "tool": "echo",
                   "isError": False, "text": "hello mcp"}


def test_call_add(stdio_config):
    code, out, _ = run_cli(
        "call", "--config", str(stdio_config), "--server",
        "fixture", "--tool", "add", "--args",
        json.dumps({"a": 3, "b": 4}))
    assert code == 0
    assert out["isError"] is False
    assert out["text"] == "7"


def test_call_error_tool_is_not_a_cli_error(stdio_config):
    code, out, _ = run_cli(
        "call", "--config", str(stdio_config), "--server",
        "fixture", "--tool", "fail", "--args", "{}")
    assert code == 0
    assert out["isError"] is True
    assert "it broke on purpose" in out["text"]


def test_call_unknown_server(stdio_config):
    code, out, _ = run_cli(
        "call", "--config", str(stdio_config), "--server",
        "ghost", "--tool", "echo", "--args", "{}")
    assert code == 2
    assert "no server named 'ghost'" in out["error"]


def test_call_bad_args_json(stdio_config):
    code, out, _ = run_cli(
        "call", "--config", str(stdio_config), "--server",
        "fixture", "--tool", "echo", "--args", "{not json")
    assert code == 2
    assert "--args" in out["error"]


# ---------------------------------------------------------------
# HTTP transport

class HttpFixture:
    """A tiny MCP-over-HTTP server: initialize issues an
    Mcp-Session-Id; later requests must carry it back."""

    SESSION_ID = "ghostmcp-test-session"

    def __init__(self, sse=False):
        self.sse = sse
        self.session_headers = []  # header per non-initialize POST
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length")
                             or 0)
                body = self.rfile.read(length) if length else b""
                try:
                    msg = json.loads(body.decode("utf-8")) \
                        if body else {}
                except ValueError:
                    msg = {}
                method = msg.get("method")
                mid = msg.get("id")
                if method == "initialize":
                    payload = {"jsonrpc": "2.0", "id": mid,
                               "result": {
                                   "protocolVersion": "2024-11-05",
                                   "capabilities": {},
                                   "serverInfo": {
                                       "name": "http-fixture",
                                       "version": "1.0.0"}}}
                    return self._reply(payload, session=True)
                outer.session_headers.append(
                    self.headers.get("Mcp-Session-Id"))
                if mid is None:  # notification: 202, no body
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if method == "tools/list":
                    payload = {"jsonrpc": "2.0", "id": mid,
                               "result": {"tools": TOOLS}}
                elif method == "tools/call":
                    args = (msg.get("params") or {}).get(
                        "arguments") or {}
                    payload = {"jsonrpc": "2.0", "id": mid,
                               "result": {"content": [{
                                   "type": "text",
                                   "text": str(args.get(
                                       "text", ""))}],
                                   "isError": False}}
                else:
                    payload = {"jsonrpc": "2.0", "id": mid,
                               "error": {"code": -32601,
                                         "message": "nope"}}
                self._reply(payload, session=False)

            def _reply(self, payload, session):
                data = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                if session:
                    self.send_header("Mcp-Session-Id",
                                     outer.SESSION_ID)
                if outer.sse:
                    self.send_header("Content-Type",
                                     "text/event-stream")
                    self.end_headers()
                    self.wfile.write(b"data: " + data + b"\n\n")
                else:
                    self.send_header("Content-Type",
                                     "application/json")
                    self.send_header("Content-Length",
                                     str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/mcp"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        return False


def _http_config(tmp_path, url):
    path = tmp_path / "http-mcp.json"
    path.write_text(json.dumps(
        {"mcpServers": {"web": {"url": url}}}))
    return path


def test_http_tools_and_call_carry_session_id(tmp_path):
    with HttpFixture() as fx:
        config = _http_config(tmp_path, fx.url)
        code, out, _ = run_cli("tools", "--config", str(config),
                               "--server", "web")
        assert code == 0
        assert {t["name"] for t in out["tools"]} == \
            {"echo", "add", "fail"}
        code, out, _ = run_cli(
            "call", "--config", str(config), "--server", "web",
            "--tool", "echo", "--args",
            json.dumps({"text": "over http"}))
        assert code == 0
        assert out["isError"] is False
        assert out["text"] == "over http"
    # every POST after initialize (the initialized notification,
    # tools/list, tools/call) carried the issued session id
    assert len(fx.session_headers) >= 3
    assert all(h == HttpFixture.SESSION_ID
               for h in fx.session_headers)


def test_http_sse_tools(tmp_path):
    with HttpFixture(sse=True) as fx:
        config = _http_config(tmp_path, fx.url)
        code, out, _ = run_cli("tools", "--config", str(config),
                               "--server", "web")
        assert code == 0
        assert {t["name"] for t in out["tools"]} == \
            {"echo", "add", "fail"}


# ---------------- 0.2.0: resources + prompts ----------------

def test_resources_list_and_read_text(stdio_config):
    code, out, _ = run_cli("resources", "--config",
                           str(stdio_config), "--server",
                           "fixture")
    assert code == 0
    assert [r["uri"] for r in out["resources"]] == \
        ["note://hello", "blob://pic"]
    code, out, _ = run_cli("resource", "--config",
                           str(stdio_config), "--server",
                           "fixture", "--uri", "note://hello")
    assert code == 0
    assert out["contents"][0]["text"] == "hello resource"


def test_resource_blob_is_reported_by_size_never_dumped(
        stdio_config):
    code, out, raw = run_cli("resource", "--config",
                             str(stdio_config), "--server",
                             "fixture", "--uri", "blob://pic")
    assert code == 0
    entry = out["contents"][0]
    assert entry["blob_base64_chars"] == len("QkxPQkJBU0U2NA==")
    assert "QkxPQkJBU0U2NA==" not in raw


def test_resource_unknown_uri_is_a_clean_error(stdio_config):
    code, out, _ = run_cli("resource", "--config",
                           str(stdio_config), "--server",
                           "fixture", "--uri", "nope://x")
    assert code == 2
    assert "unknown resource" in out["error"]


def test_prompts_list_and_get(stdio_config):
    code, out, _ = run_cli("prompts", "--config",
                           str(stdio_config), "--server",
                           "fixture")
    assert code == 0
    assert out["prompts"][0]["name"] == "greet"
    assert out["prompts"][0]["arguments"][0] == \
        {"name": "who", "required": True}
    code, out, _ = run_cli("prompt", "--config",
                           str(stdio_config), "--server",
                           "fixture", "--name", "greet",
                           "--args", json.dumps({"who": "Ada"}))
    assert code == 0
    assert out["messages"] == [
        {"role": "user", "text": "Say hello to Ada."}]


def test_prompt_bad_args_json_is_a_clean_error(stdio_config):
    code, out, _ = run_cli("prompt", "--config",
                           str(stdio_config), "--server",
                           "fixture", "--name", "greet",
                           "--args", "not json")
    assert code == 2
    assert "not valid JSON" in out["error"]
