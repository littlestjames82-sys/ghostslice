"""Shared harness for GhostProxy tests.

Everything here is local: the fake upstream binds 127.0.0.1 on an
ephemeral port, the proxy under test binds 127.0.0.1, and no test
ever contacts a real upstream or spends anything. If the proxy core
(src/ghostproxy, Agent A's half) is not present yet, proxy-dependent
tests skip with an explicit reason instead of passing or failing
spuriously; see REPORT_B.md for the contract these tests encode.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
GHOSTSLICE_SRC = Path.home() / "workspace" / "ghostslice" / "src"

# Make in-process imports work regardless of the caller's PYTHONPATH
# or of this copy's depth on disk: test modules import ``ghostproxy``
# (src layout) directly, and the fallback-parity tests import
# ``ghostslice`` directly. ProxyProcess below already puts exactly
# these two paths on PYTHONPATH for the proxy subprocess; this is the
# same bootstrap for the test process itself. (The sibling-layout
# bootstrap in ghostproxy.tokens only resolves when the two checkouts
# sit side by side, which copies of this tree do not guarantee.)
for _path in (SRC, GHOSTSLICE_SRC):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

CORE_PRESENT = (SRC / "ghostproxy").is_dir() and any(
    (SRC / "ghostproxy" / name).exists() for name in ("__main__.py", "cli.py", "server.py", "proxy.py")
)

requires_core = pytest.mark.skipif(
    not CORE_PRESENT,
    reason="GhostProxy core not present yet (src/ghostproxy missing); contract test only",
)
requires_ghostslice = pytest.mark.skipif(
    not (GHOSTSLICE_SRC / "ghostslice").is_dir(),
    reason="GhostSlice checkout not found next to GhostProxy",
)

# Canaries. These are fake, labelled values used only to prove that
# nothing the proxy writes to disk contains credential-shaped or
# secret content. They are canaries, not real credentials.
CANARY_API_KEY = "CANARY-API-KEY-ghostproxy-leak-test-0000000001"
CANARY_SECRET = "CANARY-SECRET-ghostproxy-leak-test-0000000002"
CANARIES = {"api-key": CANARY_API_KEY, "secret": CANARY_SECRET}

# Markers planted in fixture files so tests can tell exactly which
# content reached the fake upstream.
SECRET_MARKER = "GHOSTPROXY_SECRET_FILE_BODY_MARKER"
LOCKFILE_MARKER = "GHOSTPROXY_LOCKFILE_BODY_MARKER"
BIG_BODY_MARKER = "GHOSTPROXY_BIG_FUNCTION_BODY_MARKER"
DUP_MARKER = "GHOSTPROXY_DUPLICATE_FILE_MARKER"
PROMPT_MARKER = "GHOSTPROXY_USER_PROMPT_MARKER"


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http_post(url, body, headers=None, timeout=30):
    """POST bytes, return (status, response_bytes) without raising on 4xx/5xx."""
    req = urllib.request.Request(url, data=body, method="POST")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def http_get(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()
    except OSError:
        return None, b""


# ---------------------------------------------------------------- fake upstream

class _UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep test output quiet
        pass

    def _record(self, body):
        self.server.recorded.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
            }
        )

    def _send(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_HEAD(self):
        self._record(b"")
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._record(b"")
        self._send(200, b"{}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self._record(body)
        mode = self.server.mode
        if mode == "error500":
            self._send(500, b'{"type":"error","error":{"type":"api_error",'
                            b'"message":"fake upstream failure"}}')
            return
        if mode == "stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for i in range(3):
                payload = f'data: {{"type":"content_block_delta","index":0,"delta":{{"text":"chunk-{i}"}}}}\n\n'.encode()
                if self.server.drop_after is not None and i >= self.server.drop_after:
                    self.connection.close()
                    return
                self.wfile.write(b"%x\r\n%s\r\n" % (len(payload), payload))
                self.wfile.flush()
                time.sleep(0.02)
            self.wfile.write(b"0\r\n\r\n")
            return
        if mode == "mirror":
            self._send(200, body, self.headers.get("Content-Type", "application/json"))
            return
        # default: echo_json
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            parsed = None
        reply = json.dumps(
            {
                "id": "msg_fake_upstream",
                "type": "message",
                "received": parsed,
                "raw_body_len": len(body),
                "received_headers": self.server.recorded[-1]["headers"],
            }
        ).encode()
        self._send(200, reply)


class FakeUpstream:
    """A stand-in Anthropic-shaped upstream on 127.0.0.1. No real calls."""

    def __init__(self, mode="echo_json"):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
        self.server.mode = mode
        self.server.recorded = []
        self.server.drop_after = None
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def mode(self):
        return self.server.mode

    @mode.setter
    def mode(self, value):
        self.server.mode = value

    @property
    def recorded(self):
        return self.server.recorded

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


# ---------------------------------------------------------------- proxy process

class ProxyProcess:
    """Launches the proxy via its documented CLI (see README.md).

    Documented contract assumed here (REPORT_B.md lists it in full):
      PYTHONPATH=src python3 -m ghostproxy serve --host 127.0.0.1
          --port N --upstream URL --project DIR [--ledger PATH]
    Stdout/stderr go to a log file inside the work dir so the leak
    scan covers them too.
    """

    def __init__(self, project, upstream_url, workdir, extra_args=(), env_extra=None):
        self.project = Path(project)
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.log_path = self.workdir / "proxy-process.log"
        env = dict(os.environ)
        paths = [str(SRC)]
        if GHOSTSLICE_SRC.is_dir():
            paths.append(str(GHOSTSLICE_SRC))
        env["PYTHONPATH"] = os.pathsep.join(paths + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        env.update(env_extra or {})
        cmd = [
            sys.executable, "-m", "ghostproxy", "serve",
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "--upstream", upstream_url,
            "--project", str(self.project),
        ] + list(extra_args)
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(cmd, cwd=self.workdir, env=env,
                                     stdout=self._log, stderr=subprocess.STDOUT)

    def wait_ready(self, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"proxy exited early with code {self.proc.returncode}; "
                    f"log: {self.log_path.read_text(errors='replace')[-2000:]}"
                )
            status, _ = http_get(self.url + "/", timeout=2)
            if status is not None:
                return True
            time.sleep(0.1)
        raise RuntimeError(f"proxy did not start listening within {timeout}s")

    def log_text(self):
        self._log.flush()
        return self.log_path.read_text(errors="replace") if self.log_path.exists() else ""

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self._log.close()

    def __enter__(self):
        self.wait_ready()
        return self

    def __exit__(self, *exc):
        self.stop()


@pytest.fixture()
def fake_upstream():
    with FakeUpstream() as upstream:
        yield upstream


def make_project(base: Path) -> Path:
    """A small project with one of everything the proxy should treat."""
    project = base / "project"
    project.mkdir(parents=True)
    (project / "app.py").write_text(
        '"""Entry point."""\nfrom big_module import compute\n\n\n'
        "def main():\n    return compute(21)\n"
    )
    body_lines = "\n".join(f"    value_{i} = {i}  # filler line {i}" for i in range(60))
    (project / "big_module.py").write_text(
        '"""Big module."""\n\n\ndef compute(x):\n'
        f"{body_lines}\n    return x  # {BIG_BODY_MARKER}\n"
    )
    dup = (f'"""Duplicated helper. {DUP_MARKER}"""\n\n\n'
           "def helper():\n    return 'duplicated'\n")
    (project / "dup_a.py").write_text(dup)
    (project / "dup_b.py").write_text(dup)
    (project / "package-lock.json").write_text(
        '{"name": "fixture", "lockfileVersion": 3, "marker": "' + LOCKFILE_MARKER + '",'
        ' "packages": {"": {"name": "fixture", "dependencies": {"left-pad": "1.3.0"}}}}\n'
    )
    (project / "local_secrets.py").write_text(
        f'API_TOKEN = "{CANARY_SECRET}"\nMARKER = "{SECRET_MARKER}"\n'
    )
    return project


def write_profile(project: Path, proxy_section: dict) -> Path:
    profile = {"proxy": proxy_section}
    path = Path(project) / ".ghostslice.json"
    path.write_text(json.dumps(profile, indent=2))
    return path


def context_block(path: str, text: str, mode: str = "full") -> str:
    """One file section as a client pastes it into a request.

    Uses the bare ``# File: <path>`` header the proxy recognises.
    GhostSlice's own PROMPT.md uses ``# File: <path> (mode: ...)``;
    the gap between the two is pinned by an xfail test in
    test_transform.py (see REPORT_B.md).
    """
    return f"# File: {path}\n\n{text}"


def context_block_mode_header(path: str, text: str, mode: str = "full") -> str:
    """The exact header shape GhostSlice PROMPT.md writes."""
    return f"# File: {path} (mode: {mode})\n\n{text}"


def messages_request(sections, extra=None):
    """An Anthropic Messages-shaped request carrying context sections.

    ``sections`` is a list of strings (context blocks). They ride in a
    single user message alongside an ordinary prompt block, a system
    field, and conversation history, mirroring how an agent client
    pastes a GhostSlice bundle in.
    """
    content = [{"type": "text", "text": s} for s in sections]
    content.append({"type": "text", "text": f"Please review this code. {PROMPT_MARKER}"})
    request = {
        "model": "claude-test-model",
        "max_tokens": 1024,
        "system": "You are a careful reviewer. GHOSTPROXY_SYSTEM_MARKER",
        "messages": [
            {"role": "user", "content": "Earlier question, kept verbatim."},
            {"role": "assistant", "content": "Earlier answer, kept verbatim."},
            {"role": "user", "content": content},
        ],
    }
    if extra:
        request.update(extra)
    return request


def project_sections(project: Path):
    sections = []
    for name in ("app.py", "big_module.py", "dup_a.py", "dup_b.py",
                 "package-lock.json", "local_secrets.py"):
        sections.append(context_block(name, (Path(project) / name).read_text()))
    return sections


def wait_for(predicate, timeout=8, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    return predicate()
