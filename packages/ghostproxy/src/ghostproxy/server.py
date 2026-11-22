"""Localhost proxy server (stdlib http.server + http.client).

FAIL-OPEN ABOVE ALL: any error in parsing or transforming a request
forwards the ORIGINAL bytes untouched and records fallback=true in the
ledger. Upstream responses are streamed chunk by chunk and never
buffered whole or modified. Auth headers (x-api-key, authorization,
anthropic-version, ...) are forwarded as-is and NEVER logged, stored,
or written anywhere. Hop-by-hop headers are not forwarded.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .config import ConfigError, ProxyConfig
from .ledger import Ledger, make_entry
from .transform import TransformResult, transform_request

HOP_BY_HOP = {"host", "connection", "keep-alive", "proxy-connection",
              "transfer-encoding", "te", "trailer", "upgrade",
              "content-length"}
MESSAGES_PATHS = ("/v1/messages", "/v1/messages/")
_MESSAGES_SET = {p.rstrip("/") for p in MESSAGES_PATHS}
_LOCAL_PATHS = ("/", "/health", "/api/recent")


class ProxyState:
    def __init__(self, config: ProxyConfig):
        self.config = config
        self.ledger = Ledger(config.ledger_file())
        self.recent: deque = deque(maxlen=50)
        self.lock = threading.Lock()
        parsed = urlparse(config.upstream)
        self.upstream_host = parsed.hostname
        self.upstream_port = parsed.port
        self.upstream_scheme = parsed.scheme or "https"
        self.upstream_base = parsed.path.rstrip("/")

    def record(self, entry: dict) -> None:
        with self.lock:
            self.recent.appendleft(entry)
            try:
                self.ledger.append(entry)
            except Exception:
                pass  # ledger failure must never break a proxied request


def make_handler(state: ProxyState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "GhostProxy/0.1.0"

        # -- logging: method + path + status only. Never headers, never
        # bodies, so an API key cannot reach a log through this server.
        def log_message(self, fmt, *args):  # noqa: A003 - stdlib name
            pass

        # ---------------- local pages ----------------
        def do_GET(self):
            if self.path.split("?", 1)[0] in _LOCAL_PATHS:
                return self._local_page()
            return self._proxy()

        def do_POST(self):
            return self._proxy()

        def do_PUT(self):
            return self._proxy()

        def do_PATCH(self):
            return self._proxy()

        def do_DELETE(self):
            return self._proxy()

        def _local_page(self):
            path_only = self.path.split("?", 1)[0]
            if path_only == "/health":
                body = b'{"status":"ok","tool":"ghostproxy","version":"0.1.0"}'
                return self._send_local(200, body, "application/json")
            if path_only == "/api/recent":
                with state.lock:
                    items = list(state.recent)
                body = json.dumps({"recent": items}).encode()
                return self._send_local(200, body, "application/json")
            with state.lock:
                items = list(state.recent)
            rows = "".join(
                "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td>"
                "<td>{}</td><td>{}</td></tr>".format(
                    _esc(e.get("ts", "")), _esc(e.get("path", "")),
                    e.get("status", ""), e.get("tokens_in", ""),
                    e.get("tokens_out", ""), e.get("fallback", ""))
                for e in items)
            fallbacks = sum(1 for e in items if e.get("fallback"))
            saved = sum(int(e.get("tokens_in", 0)) - int(e.get("tokens_out", 0))
                        for e in items)
            html = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>GhostProxy</title></head><body>"
                "<h1>GhostProxy (local only)</h1>"
                f"<p>Recent requests: {len(items)} | fallback count: "
                f"{fallbacks} | estimated tokens saved: {saved}</p>"
                "<table border='1' cellspacing='0' cellpadding='4'>"
                "<tr><th>time</th><th>path</th><th>status</th>"
                "<th>tokens in</th><th>tokens out</th><th>fallback</th></tr>"
                + rows + "</table>"
                "<p>No request bodies or keys are shown or stored.</p>"
                "</body></html>")
            return self._send_local(200, html.encode(), "text/html; charset=utf-8")

        def _send_local(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # ---------------- request body reading ----------------
        def _read_body(self) -> bytes:
            """Read the request body without ever raising on a malformed
            framing header. The old code did ``int(Content-Length)``
            directly: a non-numeric value crashed the handler (dropping
            the connection, fail-open violated) and a negative value
            made ``rfile.read(-n)`` block until EOF. Chunked bodies
            were silently read as empty and forwarded as empty. All
            three now degrade to a well-defined body instead."""
            transfer_encoding = (self.headers.get("Transfer-Encoding")
                                 or "").lower()
            if "chunked" in transfer_encoding:
                return self._read_chunked()
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return b""
            try:
                length = int(raw_length.strip())
            except (TypeError, ValueError, AttributeError):
                # Unframable: treat as no body and do not let the
                # leftover bytes poison the next keep-alive request.
                self.close_connection = True
                return b""
            if length < 0:
                self.close_connection = True
                return b""
            return self.rfile.read(length) if length else b""

        def _read_chunked(self) -> bytes:
            chunks = []
            while True:
                size_line = self.rfile.readline(65536)
                if not size_line:
                    break
                try:
                    size = int(size_line.split(b";", 1)[0].strip(), 16)
                except ValueError:
                    self.close_connection = True
                    break
                if size == 0:
                    # Consume any trailers up to the blank line.
                    while True:
                        line = self.rfile.readline(65536)
                        if line in (b"\r\n", b"\n", b""):
                            break
                    break
                data = self.rfile.read(size)
                chunks.append(data)
                self.rfile.read(2)  # trailing CRLF after each chunk
                if len(data) < size:
                    break  # peer went away mid-chunk; forward what we have
            return b"".join(chunks)

        # ---------------- proxy core ----------------
        def _proxy(self):
            start = time.monotonic()
            raw = self._read_body()
            cfg = state.config

            body = raw
            transform_dict = None
            fallback = False
            fallback_reason = ""
            # Route on the path only: a query string ("?beta=true" and
            # similar) must not silently disable transformation -- an
            # untransformed request would forward secret-flagged files
            # the guard was supposed to exclude.
            path_only = self.path.split("?", 1)[0]
            if len(raw) > cfg.max_body_bytes:
                fallback, fallback_reason = True, "oversize-body-pass-through"
            elif path_only.rstrip("/") in _MESSAGES_SET and cfg.enabled:
                body, transform_dict, fallback, fallback_reason = \
                    self._try_transform(raw, cfg)

            status = self._forward(body)
            latency_ms = (time.monotonic() - start) * 1000.0
            entry = make_entry(
                project=cfg.project, method=self.command,
                path=self.path.split("?")[0], status=status or 502,
                transform=transform_dict, latency_ms=latency_ms,
                fallback=fallback, fallback_reason=fallback_reason)
            state.record(entry)

        def _try_transform(self, raw: bytes, cfg: ProxyConfig):
            """Fail-open wrapper: ANY failure returns the original bytes."""
            try:
                request = json.loads(raw.decode("utf-8"))
                if not isinstance(request, dict):
                    return raw, None, True, "request-not-an-object"
                result: TransformResult = transform_request(
                    request, budget_tokens=cfg.budget_tokens)
                new_body = json.dumps(result.request).encode("utf-8")
                return new_body, result.to_dict(), result.fallback, \
                    result.fallback_reason
            except Exception as exc:  # fail-open, always
                return raw, None, True, f"transform-error:{type(exc).__name__}"

        def _forward(self, body: bytes):
            """Stream the request upstream and the response back. Returns
            the upstream status code, or None if upstream was unreachable
            (a plain 502 is sent; there is no honest way to fake success)."""
            cfg = state.config
            target = state.upstream_base + self.path
            headers = {}
            for key, value in self.headers.items():
                if key.lower() in HOP_BY_HOP:
                    continue
                # Auth and every other end-to-end header forward as-is.
                headers[key] = value
            if body:
                headers["Content-Length"] = str(len(body))
            conn_cls = (http.client.HTTPSConnection
                        if state.upstream_scheme == "https"
                        else http.client.HTTPConnection)
            conn = conn_cls(state.upstream_host, state.upstream_port,
                            timeout=cfg.upstream_timeout)
            headers_sent = False
            chunked = False
            try:
                conn.request(self.command, target, body=body or None,
                             headers=headers)
                resp = conn.getresponse()
                self.send_response(resp.status, resp.reason)
                resp_len = None
                for key, value in resp.getheaders():
                    lk = key.lower()
                    if lk in HOP_BY_HOP:
                        continue
                    if lk == "content-length":
                        resp_len = int(value)
                    self.send_header(key, value)
                if resp_len is None:
                    self.send_header("Transfer-Encoding", "chunked")
                    chunked = True
                self.end_headers()
                headers_sent = True
                while True:
                    try:
                        chunk = resp.read(8192)
                    except http.client.IncompleteRead as exc:
                        chunk = exc.partial or b""
                        if chunk:
                            self._write_chunk(chunk, chunked)
                        break  # upstream dropped mid-stream: end cleanly
                    except (ConnectionError, OSError,
                            http.client.HTTPException):
                        break  # dropped stream must not wedge the proxy
                    if not chunk:
                        break
                    self._write_chunk(chunk, chunked)
                if chunked:
                    try:
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                    except Exception:
                        pass
                return resp.status
            except Exception:
                if headers_sent:
                    # Too late for a 502; close out the stream gracefully.
                    if chunked:
                        try:
                            self.wfile.write(b"0\r\n\r\n")
                            self.wfile.flush()
                        except Exception:
                            pass
                    return None
                try:
                    msg = b'{"error":"ghostproxy: upstream unreachable"}'
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(msg)))
                    self.end_headers()
                    self.wfile.write(msg)
                except Exception:
                    pass
                return None
            finally:
                conn.close()

        def _write_chunk(self, chunk: bytes, chunked: bool):
            if chunked:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            else:
                self.wfile.write(chunk)
            self.wfile.flush()

    return Handler


def _esc(value) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


BANNER = (
    "GhostProxy 0.1.0 - local only (127.0.0.1), fail-open.\n"
    "Run this only on your own machine. It forwards your client's\n"
    "auth headers as-is and never stores or logs a key, and it never\n"
    "logs request bodies by default. Inspect the ledger and live page\n"
    "any time. Bypass: point your client back at the upstream URL and\n"
    "stop this process - no config of yours is changed by GhostProxy."
)


def serve(config: ProxyConfig) -> None:
    if config.host != "127.0.0.1":
        # ConfigError (not a bare ValueError) so the CLI reports this
        # as a clean configuration refusal instead of a traceback.
        # The config layer accepts "::1" as a loopback literal, but
        # the v0.1 server binds the IPv4 literal only (README rule).
        raise ConfigError(
            "GhostProxy v0.1 binds 127.0.0.1 only "
            f"(got {config.host!r} after normalisation)")
    state = ProxyState(config)
    httpd = ThreadingHTTPServer((config.host, config.port), make_handler(state))
    print(BANNER)
    print(f"Listening on http://{config.host}:{config.port} "
          f"-> upstream {config.upstream}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
