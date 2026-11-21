"""Local web dashboard server (stdlib http.server only, binds 127.0.0.1)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .exporter import is_slicable, build_bundle, resolve_modes_detailed
from .fit import fit_modes
from .graph import build_graph, recommendations
from .ledger import analytics as ledger_analytics
from .pricing import get_model, load_prices
from .profile import load_profile
from .scanner import language_for, scan
from .secrets_scan import redact_text, scan_scan_result
from .slicer import MODES, slice_text
from .textio import read_text as _gs_read_text
from .tokens import METHOD as TOKEN_METHOD, estimate_tokens
from .workspaces import summarize_packages

_DASHBOARD = Path(__file__).with_name("dashboard.html")


def history_payload(root, profile=None) -> dict:
    """v0.14: the full ledger analytics payload (summary keys plus
    trend/aggregates/charts), priced at the profile's model (default
    claude-sonnet) from the local dated prices snapshot."""
    prices = load_prices()
    try:
        model = get_model(prices, (profile.model if profile else None)
                          or "claude-sonnet")
    except KeyError:
        model = None
    return ledger_analytics(root, model=model, prices=prices)


def _default_mode(entry) -> str:
    if entry.is_test:
        return "strip-tests"
    if entry.is_lockfile:
        return "exclude"
    if is_slicable(entry.language):
        return "signatures"
    return "full"


# v0.22: per-side character cap for /api/slice payloads. The token
# counts in the response always describe the FULL text; only the
# displayed text is cut, and the response says so (truncated flag).
SLICE_PREVIEW_CAP = 200_000

# v1.0.2: caps for the /api/graph "calls" payload. Symbols ship in
# full (the dashboard's per-file call view needs every symbol of
# the file being previewed, and symbol rows are small), but the
# edge list of a large project is not bounded by anything, so it
# is cut at CALL_EDGE_CAP entries (the payload reports the true
# total and a truncated flag, and the UI repeats the caveat where
# the lists render). Dead candidates are capped the same way.
CALL_EDGE_CAP = 2000
CALL_DEAD_CAP = 200

# v1.0.6: per-list cap for the /api/calls per-symbol endpoint. The
# bulk payload above is cut for size, so on a large project most
# symbols' relationships fall past it; the per-symbol endpoint
# serves ONE symbol's complete lists from the same memoised build.
# The cap is generous (a symbol with more than 500 distinct callers
# is vanishingly rare) but bounded, and like the bulk caps it is
# reported with true totals and a truncated flag.
CALL_LIST_CAP = 500


def _cap_text(text: str) -> tuple[str, bool]:
    """(text, was_truncated): cut at SLICE_PREVIEW_CAP characters
    with an explicit in-band marker, so a capped pane can never be
    mistaken for the whole file."""
    if len(text) <= SLICE_PREVIEW_CAP:
        return text, False
    marker = (f"\n\n[dashboard: truncated — showing the first "
              f"{SLICE_PREVIEW_CAP:,} of {len(text):,} characters]")
    return text[:SLICE_PREVIEW_CAP] + marker, True


class _State:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.profile = load_profile(self.root)
        # v0.23: the dashboard honours the profile's plugins, like
        # every other surface: they load at startup (silently — the
        # profile is the user's standing opt-in) and stay active for
        # the server's life, so scans, previews, and exports all see
        # the plugin languages. A broken plugin raises here and
        # `serve` reports it as a startup failure (exit 2), the same
        # fast-fail rule as the CLI.
        from . import plugins as _plugins_mod
        _plugins_mod.activate(_plugins_mod.load_for_project(
            self.root, profile=self.profile))
        matcher = self.profile.is_ignored if self.profile.path else None
        self.scan = scan(self.root, ignore_matcher=matcher)
        self.graph = build_graph(self.scan)
        self.recommendations = recommendations(self.scan, self.graph, self.profile)
        from .duplicates import find_duplicates, near_min_chars_for
        self.duplicates = find_duplicates(
            self.scan, near_min_chars=near_min_chars_for(self.profile))
        self.secrets = scan_scan_result(self.scan)
        from .lint import lint_project
        self.lint = lint_project(self.root, profile=self.profile,
                                 scan_result=self.scan, graph=self.graph,
                                 recs=self.recommendations,
                                 dups=self.duplicates, secrets=self.secrets)
        self.by_path = {f.path: f for f in self.scan.files}
        self._mode_tokens_cache: dict[tuple[str, str], int] = {}
        self._slice_cache: dict[tuple[str, str], object] = {}
        self._slice_lock = threading.Lock()
        # v1.0.2: the call-graph payload is built lazily on the
        # first /api/graph request and kept for the server's life —
        # the state is a startup snapshot, so a per-run memo matches
        # its semantics (same rule as the slice memo above).
        # v1.0.3: serve() additionally warms the build on a daemon
        # thread at startup (start_calls_warmup), so the first graph
        # request usually finds it ready; the lazy path remains the
        # fallback and the two produce identical payloads.
        self._calls_payload: dict | None = None
        # v1.0.6: the UNCAPPED build result, kept alongside the
        # capped bulk payload so /api/calls can serve one symbol's
        # complete lists from the same single build (no re-scan).
        self._calls_full: dict | None = None
        self._calls_error: BaseException | None = None
        self._calls_lock = threading.Lock()
        self._calls_thread: threading.Thread | None = None

    def slice_result(self, entry, mode: str):
        """Memoised slice_text for the preview endpoints (v0.22).

        The state is a startup snapshot (the scan, the graph, and the
        mode-token table already are), so memoising the SliceResult
        per (path, mode) matches the dashboard's semantics; the cache
        is flushed wholesale when it grows past 256 entries rather
        than kept as an unbounded second copy of the project."""
        key = (entry.path, mode)
        with self._slice_lock:
            hit = self._slice_cache.get(key)
        if hit is not None:
            return hit
        result = slice_text(entry.path, _gs_read_text(entry.abspath), mode)
        with self._slice_lock:
            if len(self._slice_cache) >= 256:
                self._slice_cache.clear()
            self._slice_cache[key] = result
        return result

    def preview_entry(self, rel: str):
        """Resolve a client-supplied relative path to a scanned file
        for the content-serving endpoints (/api/slice, /api/preview).

        Returns (entry, None) or (None, (status, message)). Defence
        in depth, because these endpoints return raw file content:
        the raw path must be relative, backslash-free, and free of
        `..` segments (parse_qs has already URL-decoded it, so %2e%2e
        arrives as `..` and is caught here); the path must be a file
        the scanner included; and the file's RESOLVED path must stay
        inside the project root — the scanner follows file symlinks,
        so a link pointing outside the project is in the scan, but
        its content is not served (403)."""
        if not rel:
            return None, (400, "missing path")
        if rel.startswith("/") or "\\" in rel \
                or any(seg == ".." for seg in rel.split("/")):
            return None, (400, f"invalid path: {rel}")
        entry = self.by_path.get(rel)
        if entry is None:
            return None, (404, f"no such file in scan: {rel}")
        resolved = Path(entry.abspath).resolve()
        if not resolved.is_relative_to(self.root):
            return None, (403, f"path resolves outside the project: {rel}")
        return entry, None

    def mode_tokens(self, entry, mode: str) -> int:
        key = (entry.path, mode)
        if key not in self._mode_tokens_cache:
            if mode == "full":
                self._mode_tokens_cache[key] = entry.tokens
            elif mode == "exclude":
                self._mode_tokens_cache[key] = 0
            else:
                source = _gs_read_text(entry.abspath)
                self._mode_tokens_cache[key] = slice_text(entry.path, source, mode).sliced_tokens
        return self._mode_tokens_cache[key]

    def _build_calls_payload(self) -> dict:
        from .callgraph import build_call_graph
        full = build_call_graph(self.scan, self.profile, self.graph)
        self._calls_full = full
        edges = full["edges"]
        dead = full["dead"]
        return {
            "symbols": full["symbols"],
            "edges": edges[:CALL_EDGE_CAP],
            "edges_total": len(edges),
            "edges_truncated": len(edges) > CALL_EDGE_CAP,
            "dead": dead[:CALL_DEAD_CAP],
            "dead_total": len(dead),
            "dead_truncated": len(dead) > CALL_DEAD_CAP,
            "counts": full["counts"],
            "skipped_files": full["skipped_files"],
            "note": full["note"],
            "scope": ("call analysis covers Python files "
                      "only; other files have no call data"),
        }

    def calls_payload(self) -> dict:
        """Call relationships for the served project (v1.0.2):
        Python symbols with their call edges from
        callgraph.build_call_graph over the state's startup scan.

        Computed once — by the startup warm-up thread when serve()
        ran one, otherwise lazily here — then memoised for the
        server run. A request that arrives while the build is in
        flight waits on the build lock and receives the same final
        payload object as every other request; the payload contract
        has no "building" state. Non-Python files honestly have no
        call data: they simply contribute no symbols or edges, and
        the payload's "scope" line says the analysis is Python-only.
        Edge and dead lists are capped (CALL_EDGE_CAP /
        CALL_DEAD_CAP) with the true totals and truncation flags
        reported alongside.

        A build failure is stored and re-raised on every call: the
        build runs over the fixed startup scan snapshot, so it is
        deterministic and a silent retry could not succeed — the
        failure surfaces on the graph request exactly as the lazy
        build's would, instead of being swallowed by the warm-up
        thread."""
        if self._calls_payload is not None:
            return self._calls_payload
        if self._calls_error is not None:
            raise self._calls_error
        with self._calls_lock:
            if self._calls_payload is not None:
                return self._calls_payload
            if self._calls_error is not None:
                raise self._calls_error
            try:
                self._calls_payload = self._build_calls_payload()
            except BaseException as exc:
                self._calls_error = exc
                raise
        return self._calls_payload

    def symbol_calls(self, query: str) -> tuple[int, dict]:
        """One symbol's complete call lists (v1.0.6): the bulk
        /api/graph payload caps its edge list (CALL_EDGE_CAP), so
        past the cap a symbol's relationships are invisible in the
        UI. This serves a single symbol's callers / callees /
        referenced-by from the SAME memoised build the bulk
        payload was cut from — `calls_payload()` runs first (and
        is the only build trigger), so the warm-up/lazy interplay
        and the stored-failure semantics are exactly /api/graph's.

        `query` is a symbol id ("path:Qualified.name", what the
        panel holds) or a bare qualified name. An id always wins;
        a qualified name matching several files' symbols is
        answered honestly with the candidate list instead of a
        silent pick. Returns (status, payload): 404 with an error
        object for an unknown symbol, matching the content
        endpoints' error style."""
        self.calls_payload()
        full = self._calls_full
        symbols = full["symbols"]
        by_id = {s["id"]: s for s in symbols}
        target = by_id.get(query)
        if target is None:
            matches = [s for s in symbols if s["qualified"] == query]
            if len(matches) == 1:
                target = matches[0]
            elif matches:
                return 200, {
                    "ambiguous": True,
                    "query": query,
                    "matches": [{"id": s["id"],
                                 "qualified": s["qualified"],
                                 "path": s["path"],
                                 "kind": s["kind"]}
                                for s in matches],
                    "note": ("the qualified name matches symbols in "
                             "several files; ask by symbol id "
                             "(\"path:Qualified.name\") to pick one"),
                }
        if target is None:
            return 404, {"error": f"no such symbol: {query}"}
        sid = target["id"]

        def row(other_id: str, kind: str, sites: int) -> dict:
            other = by_id.get(other_id)
            if other is not None:
                qualified, path = other["qualified"], other["path"]
            elif other_id.endswith(":<module>"):
                qualified = "<module>"
                path = other_id[:-len(":<module>")]
            else:  # pragma: no cover - edges carry resolved ids
                qualified, path = other_id, ""
            return {"id": other_id, "qualified": qualified,
                    "path": path, "kind": kind, "sites": sites}

        def collect(key: str, want_kind: str | None) -> list[dict]:
            rows = []
            for e in full["edges"]:
                if want_kind is None and e["kind"] == "reference":
                    continue
                if want_kind is not None and e["kind"] != want_kind:
                    continue
                if key == "callee" and e["callee"] == sid:
                    rows.append(row(e["caller"], e["kind"], e["sites"]))
                elif key == "caller" and e["caller"] == sid:
                    rows.append(row(e["callee"], e["kind"], e["sites"]))
            rows.sort(key=lambda r: (-r["sites"], r["id"]))
            return rows

        callers = collect("callee", None)
        callees = collect("caller", None)
        referenced_by = collect("callee", "reference")

        def capped(rows: list[dict]) -> tuple[list[dict], int, bool]:
            return rows[:CALL_LIST_CAP], len(rows), \
                len(rows) > CALL_LIST_CAP

        c_rows, c_total, c_trunc = capped(callers)
        e_rows, e_total, e_trunc = capped(callees)
        r_rows, r_total, r_trunc = capped(referenced_by)
        return 200, {
            "symbol": target,
            "callers": c_rows, "callers_total": c_total,
            "callers_truncated": c_trunc,
            "callees": e_rows, "callees_total": e_total,
            "callees_truncated": e_trunc,
            "referenced_by": r_rows, "referenced_by_total": r_total,
            "referenced_by_truncated": r_trunc,
            "list_cap": CALL_LIST_CAP,
            "dead": sid in {d["id"] for d in full["dead"]},
            "scope": ("call analysis covers Python files "
                      "only; other files have no call data"),
            "note": ("complete lists for this symbol from the "
                     "project call graph (the bulk /api/graph "
                     "payload is capped; this endpoint is not, up "
                     f"to {CALL_LIST_CAP} entries per list)"),
        }

    def start_calls_warmup(self) -> None:
        """Begin building the call-graph payload on a daemon thread
        (v1.0.3). Called by serve() once the server exists, so the
        ~seconds the build costs are spent while the user is still
        opening the page instead of on the first /api/graph request.

        Idempotent (repeat calls are no-ops) and never fatal: the
        thread is a daemon, so it cannot hold the process open past
        shutdown, and a build failure is recorded on the state by
        calls_payload() and reported by the next graph request —
        the server keeps serving every other endpoint meanwhile."""
        with self._calls_lock:
            if self._calls_thread is not None \
                    or self._calls_payload is not None \
                    or self._calls_error is not None:
                return
            self._calls_thread = threading.Thread(
                target=self._warm_calls, name="ghostslice-calls-warmup",
                daemon=True)
        self._calls_thread.start()

    def _warm_calls(self) -> None:
        try:
            self.calls_payload()
        except BaseException:
            # Already recorded on the state; the next /api/graph
            # request re-raises it there. This thread's only job is
            # to have the result (or the failure) ready early.
            pass

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
            # v0.13: per-package subtotals (API only; the dashboard
            # UI renders them from G17 on).
            "packages": summarize_packages(self.scan),
            "profile": self.profile.to_dict(),
            "recommendations": self.recommendations,
            "history": history_payload(self.root, self.profile),
        }


def _totals_for_options(state, *, selections=None, default_mode=None,
                        fit=None, exclude_secrets=False, redact=False,
                        auto_shrink=None):
    """(before, after, resolved_modes, fit_report) for one option set,
    computed in memory with the exporter's own machinery — the same
    resolve_modes_detailed / fit_modes / slice_text / redact_text
    calls build_bundle makes, in the same order (resolve, fit ladder
    on pre-redaction slices, then per-file slice + redact + recount).
    The dashboard what-if is therefore not a second estimator: the
    v0.22 ground-truth test pins its totals against a real
    build_bundle manifest for every option combination.

    Judged on the server's scan snapshot (file set, profile), with
    file contents read fresh — exactly the dashboard's preview
    semantics. Writes nothing."""
    result = state.scan
    profile = state.profile
    secret_files = ({f["path"] for f in state.secrets}
                    if exclude_secrets else set())
    resolved, _reasons = resolve_modes_detailed(
        result, profile=profile, selections=selections or {},
        default_mode=default_mode, secret_files=secret_files,
        auto_shrink=auto_shrink)
    fit_report = None
    if fit is not None:
        resolved, fit_report = fit_modes(
            result, resolved, fit, profile=profile,
            protected=set(selections or {}))
    before = after = 0
    for entry in result.files:
        mode = resolved[entry.path]
        r = slice_text(entry.path, _gs_read_text(entry.abspath), mode)
        before += r.original_tokens
        tokens = r.sliced_tokens
        if redact and mode != "exclude" and r.text:
            new_text, applied, _leftovers = redact_text(entry.path, r.text)
            if applied:
                tokens = estimate_tokens(new_text, language_for(entry.path))
        after += tokens
    return before, after, resolved, fit_report


def whatif_payload(state, options: dict) -> dict:
    """The /api/whatif response: candidate totals for the panel's
    options, the plain-default-export baseline, and the mode-change
    diff between them. `options` is the validated request body (see
    _validate_panel_options)."""
    profile = state.profile
    redact = profile.redact if options.get("redact") is None \
        else options["redact"]
    before, after, resolved, fit_report = _totals_for_options(
        state, selections=options.get("selections"),
        default_mode=options.get("mode"), fit=options.get("fit"),
        exclude_secrets=bool(options.get("exclude_secrets")),
        redact=redact, auto_shrink=options.get("auto_shrink"))
    b_before, b_after, b_resolved, _ = _totals_for_options(
        state, redact=profile.redact)
    changed = [{"path": p, "from": b_resolved[p], "to": resolved[p]}
               for p in resolved if resolved[p] != b_resolved[p]]
    notes: list[str] = []
    if options.get("exclude_secrets"):
        notes.append(
            f"{len({f['path'] for f in state.secrets})} file(s) flagged "
            "by the secret guard are excluded (exclusion wins over "
            "redaction, as in export).")
    if redact:
        notes.append("Totals are post-redaction, exactly as an export "
                     "with --redact would report them.")
    fit_block = None
    if fit_report is not None:
        fit_block = {
            "fit_tokens": fit_report["fit_tokens"],
            "before_tokens": fit_report["before_tokens"],
            "after_tokens": fit_report["after_tokens"],
            "fitted": fit_report["fitted"],
            "steps": fit_report["steps"],
            "downgraded_count": len(fit_report["downgraded"]),
        }
        if redact and after != fit_report["after_tokens"]:
            # Mirror build_bundle: the ladder judged pre-redaction
            # slices, so the manifest records the post-redaction
            # total alongside; the what-if does the same.
            fit_block["redacted_after_tokens"] = after
    return {
        "ok": True,
        "original_tokens": before,
        "sliced_tokens": after,
        "saved_tokens": before - after,
        "saved_pct": (round(100.0 * (before - after) / before, 1)
                      if before else 0.0),
        "baseline": {"original_tokens": b_before,
                     "sliced_tokens": b_after,
                     "saved_tokens": b_before - b_after},
        "delta_sliced_tokens": after - b_after,
        "mode_changes": len(changed),
        "changed_files": changed[:100],
        "changed_files_truncated": len(changed) > 100,
        "fit": fit_block,
        "fitted": (fit_report["fitted"] if fit_report is not None
                   else None),
        "notes": notes,
    }


def _validate_panel_options(body: dict) -> tuple[dict, str | None]:
    """Validate the shared what-if / export panel options from a
    request body. Returns (options, error): options carries only the
    keys the caller may pass on (mode/fit/exclude_secrets/redact/
    auto_shrink), with redact/auto_shrink left None when absent so
    the profile default applies — the same tri-state build_bundle
    uses."""
    options: dict = {}
    mode = body.get("mode")
    if mode is not None:
        if mode not in MODES:
            return {}, f"unknown mode: {mode}"
        options["mode"] = mode
    fit = body.get("fit")
    if fit is not None:
        if isinstance(fit, bool) or not isinstance(fit, int) or fit <= 0:
            return {}, "fit must be a positive integer token budget"
        options["fit"] = fit
    for key in ("exclude_secrets", "redact", "auto_shrink"):
        val = body.get(key)
        if val is not None:
            if not isinstance(val, bool):
                return {}, f"{key} must be a boolean"
            options[key] = val
    return options, None


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
                                 "duplicates": state.duplicates,
                                 "calls": state.calls_payload()})
            elif parsed.path == "/api/calls":
                # v1.0.6: one symbol's complete call lists — the
                # bulk graph payload's edge cap hides most of a
                # large project's relationships; this serves them
                # per symbol from the same memoised build.
                query = (qs.get("symbol") or [""])[0]
                if not query:
                    self._json(400, {"error": "missing symbol"})
                    return
                status, payload = state.symbol_calls(query)
                self._json(status, payload)
            elif parsed.path == "/api/secrets":
                self._json(200, {"findings": state.secrets, "count": len(state.secrets),
                                 "note": "values redacted to first 4 characters"})
            elif parsed.path == "/api/lint":
                self._json(200, state.lint)
            elif parsed.path == "/api/history":
                self._json(200, history_payload(state.root, state.profile))
            elif parsed.path == "/api/preview":
                rel = (qs.get("path") or [""])[0]
                mode = (qs.get("mode") or ["signatures"])[0]
                entry, err = state.preview_entry(rel)
                if entry is None:
                    self._json(err[0], {"error": err[1]})
                    return
                if mode not in MODES:
                    self._json(400, {"error": f"unknown mode: {mode}"})
                    return
                self._json(200, state.slice_result(entry, mode).to_dict())
            elif parsed.path == "/api/slice":
                # v0.22: side-by-side slice preview (original + slice).
                rel = (qs.get("path") or [""])[0]
                entry, err = state.preview_entry(rel)
                if entry is None:
                    self._json(err[0], {"error": err[1]})
                    return
                mode = (qs.get("mode") or [_default_mode(entry)])[0]
                if mode not in MODES:
                    self._json(400, {"error": f"unknown mode: {mode}"})
                    return
                source = _gs_read_text(entry.abspath)
                result = state.slice_result(entry, mode)
                original, orig_cut = _cap_text(source)
                sliced, slice_cut = _cap_text(result.text)
                truncated_sides = (["original"] if orig_cut else []) \
                    + (["sliced"] if slice_cut else [])
                self._json(200, {
                    "path": rel, "mode": mode, "language": entry.language,
                    "original": original, "sliced": sliced,
                    "original_tokens": result.original_tokens,
                    "sliced_tokens": result.sliced_tokens,
                    "saved_tokens": result.saved_tokens,
                    "saved_pct": (round(100.0 * result.saved_tokens
                                        / result.original_tokens, 1)
                                  if result.original_tokens else 0.0),
                    "truncated": bool(truncated_sides),
                    "truncated_sides": truncated_sides,
                    "note": ("Token counts are estimates for the full "
                             "file and slice; displayed text is capped "
                             f"at {SLICE_PREVIEW_CAP:,} characters per "
                             "side." if truncated_sides else
                             "Token counts are estimates."),
                })
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
            if not isinstance(body, dict):
                # v0.21: a JSON array/scalar body is a 400, not a
                # handler traceback on body.get.
                self._json(400, {"error": "JSON body must be an object"})
                return
            if parsed.path == "/api/whatif":
                # v0.22: would-be totals for the panel's options,
                # computed in memory — writes nothing, records no
                # history (see whatif_payload).
                selections = body.get("selections") or {}
                if not isinstance(selections, dict) or any(
                        not isinstance(k, str) or v not in MODES
                        for k, v in selections.items()):
                    self._json(400, {"error": "selections must map "
                                            "paths to known modes"})
                    return
                options, err = _validate_panel_options(body)
                if err:
                    self._json(400, {"error": err})
                    return
                options["selections"] = selections
                try:
                    payload = whatif_payload(state, options)
                except Exception as exc:  # surface, never traceback
                    self._json(200, {"ok": False, "error": str(exc)})
                    return
                self._json(200, payload)
            elif parsed.path == "/api/export":
                selections = body.get("selections") or {}
                if not isinstance(selections, dict) or any(
                        not isinstance(k, str) or v not in MODES
                        for k, v in selections.items()):
                    self._json(400, {"error": "selections must map "
                                            "paths to known modes"})
                    return
                # v0.22: the what-if panel's options ride along, so
                # what was previewed is what gets exported.
                options, err = _validate_panel_options(body)
                if err:
                    self._json(400, {"error": err})
                    return
                out_name = body.get("out") or ".claude_context"
                if not isinstance(out_name, str) or not out_name:
                    self._json(400, {"error": "out must be a path string"})
                    return
                # Local tool: bundle always lands inside the served
                # project — enforced, not just intended (audit G17
                # F6: "../escaped" previously wrote outside the root).
                out = (state.root / out_name).resolve()
                if not out.is_relative_to(state.root):
                    self._json(400, {"error": "out must stay inside "
                                            "the project"})
                    return
                try:
                    manifest = build_bundle(
                        state.root, out, selections=selections,
                        default_mode=options.get("mode"),
                        profile=state.profile,
                        fit=options.get("fit"),
                        exclude_secrets=bool(
                            options.get("exclude_secrets", False)),
                        redact=options.get("redact"),
                        auto_shrink=options.get("auto_shrink"))
                except Exception as exc:  # surface the error in the UI
                    self._json(200, {"ok": False, "error": str(exc)})
                    return
                resp = {
                    "ok": True, "bundle": str(out),
                    "total_original_tokens": manifest["total_original_tokens"],
                    "total_sliced_tokens": manifest["total_sliced_tokens"],
                }
                if manifest.get("fit") is not None:
                    resp["fit"] = manifest["fit"]
                if manifest.get("redaction") is not None:
                    resp["redaction"] = manifest["redaction"]
                if manifest.get("plugins") is not None:
                    resp["plugins"] = manifest["plugins"]
                if manifest.get("plugin_errors") is not None:
                    resp["plugin_errors"] = manifest["plugin_errors"]
                self._json(200, resp)
            else:
                self._json(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler), state


def serve(root: str, port: int = 8765, host: str = "127.0.0.1") -> None:
    server, state = make_server(root, port=port, host=host)
    # v1.0.3: warm the call-graph payload in the background while
    # the user opens the page, instead of charging the first
    # /api/graph request for the whole build.
    state.start_calls_warmup()
    print(f"GhostSlice dashboard: http://{host}:{server.server_address[1]}/  (project: {root})")
    print("Token counts are estimates. Prices come from local prices.json (not live). Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
