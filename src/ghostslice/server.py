"""Local web dashboard server (stdlib http.server only, binds 127.0.0.1)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .exporter import SLICABLE, build_bundle
from .graph import build_graph, recommendations
from .ledger import summary as ledger_summary
from .pricing import load_prices
from .profile import load_profile
from .scanner import scan
from .secrets_scan import scan_scan_result
from .slicer import MODES, slice_text
from .tokens import METHOD as TOKEN_METHOD

_DASHBOARD = Path(__file__).with_name("dashboard.html")


def _default_mode(entry) -> str:
    if entry.is_test:
        return "strip-tests"
    if entry.is_lockfile:
        return "exclude"
    if entry.language in SLICABLE:
        return "signatures"
    return "full"


class _State:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.profile = load_profile(self.root)
        matcher = self.profile.is_ignored if self.profile.path else None
        self.scan = scan(self.root, ignore_matcher=matcher)
        self.graph = build_graph(self.scan)
        self.recommendations = recommendations(self.scan, self.graph, self.profile)
        from .duplicates import find_duplicates
        self.duplicates = find_duplicates(self.scan)
        self.secrets = scan_scan_result(self.scan)
        from .lint import lint_project
        self.lint = lint_project(self.root, profile=self.profile,
                                 scan_result=self.scan, graph=self.graph,
                                 recs=self.recommendations,
                                 dups=self.duplicates, secrets=self.secrets)
        self.by_path = {f.path: f for f in self.scan.files}
        self._mode_tokens_cache: dict[tuple[str, str], int] = {}

    def mode_tokens(self, entry, mode: str) -> int:
        key = (entry.path, mode)
        if key not in self._mode_tokens_cache:
            if mode == "full":
                self._mode_tokens_cache[key] = entry.tokens
            elif mode == "exclude":
                self._mode_tokens_cache[key] = 0
            else:
                source = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
                self._mode_tokens_cache[key] = slice_text(entry.path, source, mode).sliced_tokens
        return self._mode_tokens_cache[key]

    def scan_payload(self) -> dict:
        files = []
        for entry in self.scan.files:
            d = entry.to_dict()
            d.pop("abspath", None)
            d["default_mode"] = _default_mode(entry)
            d["mode"] = d["default_mode"]
            d["mode_tokens"] = {m: self.mode_tokens(entry, m) for m in MODES}
            files.append(d)
        return {
            "root": str(self.root),
            "total_tokens": self.scan.total_tokens,
            "file_count": len(files),
            "token_method": TOKEN_METHOD,
            "files": files,
            "profile": self.profile.to_dict(),
            "recommendations": self.recommendations,
            "history": ledger_summary(self.root),
        }


def make_server(root: str, port: int = 8765, host: str = "127.0.0.1"):
    state = _State(root)
    prices = load_prices()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, code, body, content_type="application/json"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj), "application/json")

        def do_GET(self):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if parsed.path == "/":
                html = _DASHBOARD.read_text(encoding="utf-8") if _DASHBOARD.is_file() else "<h1>GhostSlice</h1>"
                self._send(200, html, "text/html; charset=utf-8")
            elif parsed.path == "/api/scan":
                self._json(200, state.scan_payload())
            elif parsed.path == "/api/prices":
                payload = {k: v for k, v in prices.items() if not k.startswith("_")}
                self._json(200, payload)
            elif parsed.path == "/api/graph":
                self._json(200, {"graph": state.graph,
                                 "recommendations": state.recommendations,
                                 "duplicates": state.duplicates})
            elif parsed.path == "/api/secrets":
                self._json(200, {"findings": state.secrets, "count": len(state.secrets),
                                 "note": "values redacted to first 4 characters"})
            elif parsed.path == "/api/lint":
                self._json(200, state.lint)
            elif parsed.path == "/api/history":
                self._json(200, ledger_summary(state.root))
            elif parsed.path == "/api/preview":
                rel = (qs.get("path") or [""])[0]
                mode = (qs.get("mode") or ["signatures"])[0]
                entry = state.by_path.get(rel)
                if entry is None:
                    self._json(404, {"error": f"no such file in scan: {rel}"})
                    return
                if mode not in MODES:
                    self._json(400, {"error": f"unknown mode: {mode}"})
                    return
                source = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
                self._json(200, slice_text(rel, source, mode).to_dict())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._json(400, {"error": "invalid JSON body"})
                return
            if parsed.path == "/api/export":
                selections = body.get("selections") or {}
                out_name = body.get("out") or ".claude_context"
                # Local tool: bundle always lands inside the served project.
                out = state.root / out_name
                try:
                    manifest = build_bundle(state.root, out, selections=selections)
                except Exception as exc:  # surface the error in the UI
                    self._json(200, {"ok": False, "error": str(exc)})
                    return
                self._json(200, {
                    "ok": True, "bundle": str(out),
                    "total_original_tokens": manifest["total_original_tokens"],
                    "total_sliced_tokens": manifest["total_sliced_tokens"],
                })
            else:
                self._json(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler), state


def serve(root: str, port: int = 8765, host: str = "127.0.0.1") -> None:
    server, _state = make_server(root, port=port, host=host)
    print(f"GhostSlice dashboard: http://{host}:{server.server_address[1]}/  (project: {root})")
    print("Token counts are estimates. Prices come from local prices.json (not live). Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
