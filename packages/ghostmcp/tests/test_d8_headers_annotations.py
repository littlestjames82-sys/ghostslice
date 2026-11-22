"""D8 (GhostIDE Desktop Cycle 2): config ``headers`` ride
HTTP requests (values never surface), ``tools/list`` keeps
server annotations, and ``servers`` reports header names
only. Added alongside the IDE's MCP polish; the fixtures
mirror test_ghostmcp.py's patterns."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, __file__.rsplit("/tests/", 1)[0] + "/src")

from ghostmcp.client import describe_servers, list_tools  # noqa: E402
from ghostmcp.cli import main  # noqa: E402

TOOLS = [
    {"name": "echo", "description": "Echo text.",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string"}}},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "wipe", "description": "Wipe things.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"destructiveHint": True}},
]

STDIO_SERVER = r'''
import json
import sys

TOOLS = __TOOLS__


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            out = {"protocolVersion": "2024-11-05",
                   "capabilities": {},
                   "serverInfo": {"name": "fx", "version": "1"}}
        elif method == "tools/list":
            out = {"tools": TOOLS}
        elif mid is None:
            continue
        else:
            out = None
        if mid is not None:
            print(json.dumps({"jsonrpc": "2.0", "id": mid,
                              "result": out}), flush=True)


main()
'''


def _stdio_config(tmp_path):
    srv = tmp_path / "fx.py"
    srv.write_text(STDIO_SERVER.replace(
        "__TOOLS__", repr(TOOLS)))
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {
        "fx": {"command": sys.executable, "args": [str(srv)]}}}))
    return cfg


def test_annotations_survive_tools_list(tmp_path):
    out = list_tools(str(_stdio_config(tmp_path)), "fx",
                     timeout=15)
    by_name = {t["name"]: t for t in out["tools"]}
    assert by_name["echo"]["annotations"] == {
        "readOnlyHint": True, "openWorldHint": False}
    assert by_name["wipe"]["annotations"] == {
        "destructiveHint": True}


class AuthFixture:
    """HTTP MCP fixture that 401s unless the configured
    bearer token arrives, and records what it saw."""

    TOKEN = "Bearer d8-test-token"

    def __init__(self):
        self.seen_auth = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                msg = json.loads(body.decode()) if body else {}
                outer.seen_auth.append(
                    self.headers.get("Authorization"))
                if self.headers.get("Authorization") != \
                        outer.TOKEN:
                    self.send_response(401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                mid = msg.get("id")
                if mid is None:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                method = msg.get("method")
                if method == "initialize":
                    result = {"protocolVersion": "2024-11-05",
                              "capabilities": {},
                              "serverInfo": {"name": "authfx",
                                             "version": "1"}}
                elif method == "tools/list":
                    result = {"tools": TOOLS}
                else:
                    result = {}
                data = json.dumps({"jsonrpc": "2.0", "id": mid,
                                   "result": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type",
                                 "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0),
                                          Handler)
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


def test_http_headers_ride_requests_and_stay_secret(tmp_path):
    with AuthFixture() as fx:
        cfg = tmp_path / "mcp.json"
        cfg.write_text(json.dumps({"mcpServers": {"web": {
            "url": fx.url,
            "headers": {"Authorization": AuthFixture.TOKEN}}}}))
        out = list_tools(str(cfg), "web", timeout=15)
        assert [t["name"] for t in out["tools"]] == \
            ["echo", "wipe"]
        assert fx.seen_auth and all(
            a == AuthFixture.TOKEN for a in fx.seen_auth)
        described = describe_servers(str(cfg))
        assert described[0]["header_names"] == ["Authorization"]
        assert AuthFixture.TOKEN not in json.dumps(described)


def test_http_without_header_is_refused(tmp_path):
    with AuthFixture() as fx:
        cfg = tmp_path / "mcp.json"
        cfg.write_text(json.dumps(
            {"mcpServers": {"web": {"url": fx.url}}}))
        try:
            list_tools(str(cfg), "web", timeout=15)
        except Exception as e:
            assert "401" in str(e)
        else:
            raise AssertionError("expected an HTTP 401 error")
