"""v1.0.3 polish round 3: dashboard call-graph warm-up, graph
command cache parity, history filters + percentiles, watch
profile reload.

Contracts:
- Warm-up is a pure optimisation: the payload a warm-started
  server serves is identical to the lazy one, concurrent requests
  during the build all receive the same final payload object, and
  a build failure is recorded and re-raised on the graph request
  (never swallowed) while the server keeps serving.
- The graph command joins scan/lint/calls on the content cache:
  --no-cache / cold / warm output is byte-identical, and a plugin
  edit moves the cache namespace (new entries, no stale reads).
- History filters compose and describe exactly the runs shown;
  percentiles are hand-computed on a known ledger; the unfiltered
  default output keeps its pre-v1.0.3 shape (the filter block is
  additive and absent without flags).
- Watch reloads a changed profile by content hash (a touch is not
  a change): valid applies, invalid keeps last-good with one
  report per distinct bad content, fixing recovers, deleting
  reverts to defaults.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice import callgraph as callgraph_mod
from ghostslice import plugins as plugins_mod
from ghostslice import server as server_mod
from ghostslice.cache import cache_stats
from ghostslice.cli import main as cli_main
from ghostslice.ledger import analytics, parse_since
from ghostslice.profile import load_profile, load_profile_file
from ghostslice.server import make_server
from ghostslice.watch import run_watch


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _cli(argv, capsys):
    code = cli_main(argv)
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture(autouse=True)
def _reset_plugins():
    yield
    plugins_mod.reset()


# ---------------------------------------------------------------------------
# Item A: dashboard call-graph warm-up
# ---------------------------------------------------------------------------

def _py_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _write(root, "main.py",
           "from util import helper\n\n\n"
           "def main():\n    return helper()\n")
    _write(root, "util.py",
           "def helper():\n    return 1\n\n\n"
           "def orphan():\n    return 2\n")
    return root


def test_make_server_alone_does_not_warm(tmp_path):
    # The seam is serve(), not construction: tests and embedders
    # that build a _State without serving must not pay for (or be
    # surprised by) a background build.
    _py_project(tmp_path)
    server, state = make_server(str(tmp_path), port=0)
    try:
        assert state._calls_thread is None
        assert state._calls_payload is None
    finally:
        server.server_close()


def test_warm_started_payload_identical_to_lazy(tmp_path):
    _py_project(tmp_path)
    s1, lazy_state = make_server(str(tmp_path), port=0)
    s2, warm_state = make_server(str(tmp_path), port=0)
    try:
        lazy = lazy_state.calls_payload()
        warm_state.start_calls_warmup()
        warm_state._calls_thread.join(30)
        warmed = warm_state.calls_payload()
        assert warmed == lazy
        # Memoised: the same object is served for the server run.
        assert warm_state.calls_payload() is warmed
        # Idempotent: a second warm-up call starts nothing new.
        thread = warm_state._calls_thread
        warm_state.start_calls_warmup()
        assert warm_state._calls_thread is thread
    finally:
        s1.server_close()
        s2.server_close()


def test_concurrent_requests_during_build_share_final_payload(
        tmp_path, monkeypatch):
    _py_project(tmp_path)
    real_build = callgraph_mod.build_call_graph
    started = threading.Event()
    gate = threading.Event()

    def slow_build(*args, **kwargs):
        started.set()
        gate.wait(30)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(callgraph_mod, "build_call_graph", slow_build)
    server, state = make_server(str(tmp_path), port=0)
    try:
        state.start_calls_warmup()
        assert started.wait(30)
        results: list = []

        def ask():
            results.append(state.calls_payload())

        threads = [threading.Thread(target=ask) for _ in range(4)]
        for t in threads:
            t.start()
        # All four requests are queued behind the in-flight build;
        # none can have returned yet (payload is not built).
        time.sleep(0.2)
        assert results == []
        gate.set()
        for t in threads:
            t.join(30)
        assert len(results) == 4
        assert all(r is results[0] for r in results)
        assert results[0]["counts"]["symbols"] >= 3
    finally:
        gate.set()
        server.server_close()


def test_warmup_failure_surfaces_and_server_keeps_serving(
        tmp_path, monkeypatch):
    _py_project(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("boom-build")

    monkeypatch.setattr(callgraph_mod, "build_call_graph", boom)
    server, state = make_server(str(tmp_path), port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        state.start_calls_warmup()
        state._calls_thread.join(30)
        # The failure is reported on the payload path, not swallowed
        # by the warm-up thread...
        with pytest.raises(RuntimeError, match="boom-build"):
            state.calls_payload()
        # ...and it matches what the lazy path raises.
        s2, lazy_state = make_server(str(tmp_path), port=0)
        try:
            with pytest.raises(RuntimeError, match="boom-build"):
                lazy_state.calls_payload()
        finally:
            s2.server_close()
        # Other endpoints keep serving throughout.
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/scan", timeout=30) as r:
            assert r.status == 200
            assert json.loads(r.read())["file_count"] == 2
    finally:
        server.shutdown()
        server.server_close()


def test_shutdown_during_warmup_build_does_not_hang(
        tmp_path, monkeypatch):
    # The warm-up thread is a daemon and holds no server resource:
    # shutdown + close complete while its build is still gated,
    # and releasing the build afterwards harms nothing.
    _py_project(tmp_path)
    real_build = callgraph_mod.build_call_graph
    started = threading.Event()
    gate = threading.Event()

    def slow_build(*args, **kwargs):
        started.set()
        gate.wait(30)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(callgraph_mod, "build_call_graph", slow_build)
    server, state = make_server(str(tmp_path), port=0)
    serve_thread = threading.Thread(target=server.serve_forever,
                                    daemon=True)
    serve_thread.start()
    try:
        state.start_calls_warmup()
        assert started.wait(30)
        server.shutdown()
        server.server_close()
        serve_thread.join(30)
        assert not serve_thread.is_alive()
    finally:
        gate.set()
        state._calls_thread.join(30)


def test_warmup_on_project_without_python(tmp_path):
    _write(tmp_path, "notes.md", "# hi\n")
    server, state = make_server(str(tmp_path), port=0)
    try:
        state.start_calls_warmup()
        state._calls_thread.join(30)
        payload = state.calls_payload()
        assert payload["symbols"] == []
        assert payload["edges"] == []
        assert "Python files only" in payload["scope"]
    finally:
        server.server_close()


def test_serve_starts_the_warmup(tmp_path, monkeypatch):
    _py_project(tmp_path)
    warmed: list = []
    monkeypatch.setattr(server_mod._State, "start_calls_warmup",
                        lambda self: warmed.append(True))
    monkeypatch.setattr(server_mod.ThreadingHTTPServer,
                        "serve_forever", lambda self, *a, **k: None)
    server_mod.serve(str(tmp_path), port=0)
    assert warmed == [True]


# ---------------------------------------------------------------------------
# Item B: graph command cache parity
# ---------------------------------------------------------------------------

def _graph_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _write(root, "main.py",
           "from util import helper\n\n\n"
           "def main():\n    return helper()\n")
    _write(root, "util.py", "def helper():\n    return 1\n")
    _write(root, "dead.py", "def unused():\n    return 0\n")
    return root


def _graph_json(root: Path, capsys, *extra: str) -> str:
    code, out, _err = _cli(["graph", str(root), "--json", *extra],
                           capsys)
    assert code == 0
    return out


def test_graph_cache_parity_fixture(tmp_path, capsys):
    _graph_project(tmp_path)
    no_cache = _graph_json(tmp_path, capsys, "--no-cache")
    cold = _graph_json(tmp_path, capsys)
    warm = _graph_json(tmp_path, capsys)
    assert cold == no_cache
    assert warm == no_cache
    # The cache was really consulted and filled (not silently off).
    assert cache_stats(tmp_path)["entries"] > 0
    payload = json.loads(warm)
    assert any(r.get("kind") == "dead-symbol"
               for r in payload["recommendations"])


def test_graph_cache_parity_this_repo(capsys):
    repo = Path(__file__).resolve().parents[1]
    no_cache = _graph_json(repo, capsys, "--no-cache")
    warm = _graph_json(repo, capsys)
    assert warm == no_cache


GRAPH_PLUGIN_V1 = '''
LANGUAGE = "lua"
EXTENSIONS = [".lua"]


def slice_text(path, text, mode):
    return text


def outline(path, text):
    return []
'''

GRAPH_PLUGIN_V2 = '''
LANGUAGE = "lua"
EXTENSIONS = [".lua"]


def slice_text(path, text, mode):
    if mode == "signatures":
        return "-- v2 signatures\\n"
    return text


def outline(path, text):
    return []
'''


def _big_lua(n_funcs: int = 60) -> str:
    parts = []
    for i in range(n_funcs):
        parts.append(f"local function f{i}()\n  return {i}\nend\n\n")
    return "".join(parts)


def test_graph_plugin_edit_moves_cache_namespace(tmp_path, capsys):
    _write(tmp_path, "tools/lua_slicer.py", GRAPH_PLUGIN_V1)
    _write(tmp_path, "big.lua", _big_lua())
    _write(tmp_path, ".ghostslice.json", json.dumps(
        {"plugins": ["tools/lua_slicer.py"]}))
    cold = _graph_json(tmp_path, capsys)
    assert _graph_json(tmp_path, capsys) == cold
    entries_v1 = cache_stats(tmp_path)["entries"]
    assert entries_v1 > 0
    # Editing the plugin changes its digest, which is the cache
    # namespace: the next cached run fills a NEW namespace (entry
    # count grows) and its output still equals --no-cache exactly.
    _write(tmp_path, "tools/lua_slicer.py", GRAPH_PLUGIN_V2)
    after = _graph_json(tmp_path, capsys)
    assert cache_stats(tmp_path)["entries"] > entries_v1
    assert after == _graph_json(tmp_path, capsys, "--no-cache")


# ---------------------------------------------------------------------------
# Item C: history filters + percentiles
# ---------------------------------------------------------------------------

HIST_RUNS = [
    {"at": "2026-10-01T10:00:00+00:00", "kind": "export", "bundle": "b1",
     "before_tokens": 1000, "after_tokens": 600, "saved_tokens": 400,
     "estimator": "v2"},
    {"at": "2026-10-08T10:00:00+00:00", "kind": "export", "bundle": "b2",
     "before_tokens": 1200, "after_tokens": 600, "saved_tokens": 600,
     "estimator": "v2"},
    {"at": "2026-10-15T10:00:00+00:00", "kind": "export", "bundle": "b3",
     "before_tokens": 900, "after_tokens": 450, "saved_tokens": 450,
     "estimator": "v2"},
]


def _hist_project(root: Path, records=HIST_RUNS) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _write(root, "a.py", "x = 1\n")
    lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
    _write(root, ".ghostslice-history.jsonl",
           "\n".join(lines) + ("\n" if lines else ""))
    return root


def test_percentiles_hand_computed(tmp_path):
    _hist_project(tmp_path)
    pct = analytics(tmp_path)["aggregates"]["percentiles"]
    # before sorted [900, 1000, 1200]: p50 = 1000; p90 rank 1.8 ->
    # 1000 + 0.8 * 200 = 1160. after sorted [450, 600, 600]:
    # p50 = 600, p90 = 600. saved sorted [400, 450, 600]:
    # p50 = 450; p90 -> 450 + 0.8 * 150 = 570.
    assert pct["before_tokens"] == {"p50": 1000.0, "p90": 1160.0}
    assert pct["after_tokens"] == {"p50": 600.0, "p90": 600.0}
    assert pct["saved_tokens"] == {"p50": 450.0, "p90": 570.0}


def test_percentiles_single_and_two_runs(tmp_path):
    _hist_project(tmp_path, HIST_RUNS[:1])
    pct = analytics(tmp_path)["aggregates"]["percentiles"]
    assert pct["saved_tokens"] == {"p50": 400.0, "p90": 400.0}
    two = [dict(HIST_RUNS[0], saved_tokens=100, before_tokens=200,
                after_tokens=100),
           dict(HIST_RUNS[1], saved_tokens=300, before_tokens=400,
                after_tokens=100)]
    _hist_project(tmp_path, two)
    pct = analytics(tmp_path)["aggregates"]["percentiles"]
    # n=2: rank = pct/100 * 1 -> p50 = 100 + 0.5*200, p90 = 100 + 0.9*200
    assert pct["saved_tokens"] == {"p50": 200.0, "p90": 280.0}


def test_percentiles_empty_ledger_are_none_not_zero(tmp_path):
    _hist_project(tmp_path, [])
    pct = analytics(tmp_path)["aggregates"]["percentiles"]
    assert pct == {"before_tokens": None, "after_tokens": None,
                   "saved_tokens": None}


def test_parse_since_forms():
    assert parse_since("2026-10-01") == datetime(
        2026, 10, 1, tzinfo=timezone.utc).timestamp()
    assert parse_since("2026-10-01T12:30:00+00:00") == datetime(
        2026, 10, 1, 12, 30, tzinfo=timezone.utc).timestamp()
    # A naive datetime is read as UTC (the _parse_ts convention).
    assert parse_since("2026-10-01 06:00:00") == datetime(
        2026, 10, 1, 6, 0, tzinfo=timezone.utc).timestamp()
    base = 1_800_000_000.0
    assert parse_since("7d", now=base) == base - 7 * 86400
    assert parse_since("0d", now=base) == base
    for bad in ("7w", "tomorrow", "", "2026-13-01", "-3d", "d"):
        with pytest.raises(ValueError):
            parse_since(bad)


def test_history_top_filter(tmp_path):
    _hist_project(tmp_path)
    data = analytics(tmp_path, top=1)
    assert data["runs"] == 1
    assert data["total_saved_tokens"] == 600
    assert [r["saved_tokens"] for r in data["runs_detail"]] == [600]
    assert len(data["records"]) == 1
    f = data["filter"]
    assert f["top"] == 1 and f["since"] is None
    assert f["runs_total"] == 3 and f["runs_shown"] == 1
    assert f["undated_excluded"] == 0


def test_history_since_filter(tmp_path):
    _hist_project(tmp_path)
    data = analytics(tmp_path, since=parse_since("2026-10-05"))
    assert data["runs"] == 2
    assert data["total_before_tokens"] == 2100
    assert data["filter"]["runs_total"] == 3
    assert data["filter"]["runs_shown"] == 2


def test_history_filters_compose(tmp_path):
    _hist_project(tmp_path)
    data = analytics(tmp_path, since=parse_since("2026-10-05"), top=1)
    # In range: runs 2 (saved 600) and 3 (saved 450); top 1 -> run 2.
    assert data["runs"] == 1
    assert data["runs_detail"][0]["bundle"] == "b2"


def test_history_since_excludes_and_counts_undated(tmp_path):
    undated = {"kind": "export", "bundle": "bx", "before_tokens": 500,
               "after_tokens": 100, "saved_tokens": 400,
               "estimator": "v2"}
    _hist_project(tmp_path, [*HIST_RUNS, undated])
    data = analytics(tmp_path, since=parse_since("2026-10-05"))
    assert data["runs"] == 2
    assert data["filter"]["runs_total"] == 4
    assert data["filter"]["undated_excluded"] == 1
    # Without the filter the undated run is still counted.
    assert analytics(tmp_path)["runs"] == 4


def test_history_top_must_be_positive(tmp_path):
    _hist_project(tmp_path)
    with pytest.raises(ValueError):
        analytics(tmp_path, top=0)


def test_history_since_boundary_is_inclusive(tmp_path):
    _hist_project(tmp_path)
    # A run timestamped exactly at the cutoff is in range.
    data = analytics(
        tmp_path, since=parse_since("2026-10-08T10:00:00+00:00"))
    assert data["runs"] == 2
    assert data["runs_detail"][0]["bundle"] == "b2"


def test_graph_env_no_cache_parity(tmp_path, capsys, monkeypatch):
    # GHOSTSLICE_NO_CACHE=1 must give graph the same output too:
    # open_cache returns None and the command runs uncached.
    _graph_project(tmp_path)
    monkeypatch.setenv("GHOSTSLICE_NO_CACHE", "1")
    env_off = _graph_json(tmp_path, capsys)
    monkeypatch.delenv("GHOSTSLICE_NO_CACHE")
    assert env_off == _graph_json(tmp_path, capsys, "--no-cache")


def test_history_no_filter_no_filter_block(tmp_path):
    _hist_project(tmp_path)
    data = analytics(tmp_path)
    assert "filter" not in data
    assert data["runs"] == 3


def test_cli_history_filters_text(tmp_path, capsys):
    _hist_project(tmp_path)
    code, out, _ = _cli(["history", str(tmp_path), "--top", "1"], capsys)
    assert code == 0
    assert f"Savings ledger for {tmp_path}: 1 recorded run(s)" in out
    assert "saved: 600 estimated tokens" in out
    assert "Filter: top 1 by tokens saved" in out
    assert "showing 1 of 3 recorded run(s)" in out


def test_cli_history_since_text_and_empty_range(tmp_path, capsys):
    _hist_project(tmp_path)
    code, out, _ = _cli(
        ["history", str(tmp_path), "--since", "2027-01-01"], capsys)
    assert code == 0
    assert "0 recorded run(s)" in out
    assert "showing 0 of 3 recorded run(s)" in out
    code, out, _ = _cli(
        ["history", str(tmp_path), "--since", "2027-01-01", "--trend"],
        capsys)
    assert code == 0
    assert "No runs match the active filter" in out


def test_cli_history_bad_flags_exit_2(tmp_path, capsys):
    _hist_project(tmp_path)
    code, _, err = _cli(
        ["history", str(tmp_path), "--since", "bogus"], capsys)
    assert code == 2
    assert "--since" in err
    code, _, err = _cli(["history", str(tmp_path), "--top", "0"], capsys)
    assert code == 2
    assert "--top" in err


def test_cli_history_trend_percentile_line(tmp_path, capsys):
    _hist_project(tmp_path)
    code, out, _ = _cli(["history", str(tmp_path), "--trend"], capsys)
    assert code == 0
    assert "oldest first" in out
    assert ("Per-run percentiles (estimated tokens): saved p50 450, "
            "p90 570; export total (after) p50 600, p90 600") in out
    code, out, _ = _cli(
        ["history", str(tmp_path), "--trend", "--top", "2"], capsys)
    assert code == 0
    assert "largest savings first" in out


def test_cli_history_json_filter_block_is_additive(tmp_path, capsys):
    _hist_project(tmp_path)
    code, out, _ = _cli(["history", str(tmp_path), "--json"], capsys)
    assert code == 0
    plain = json.loads(out)
    assert "filter" not in plain
    assert plain["aggregates"]["percentiles"]["saved_tokens"] == {
        "p50": 450.0, "p90": 570.0}
    code, out, _ = _cli(
        ["history", str(tmp_path), "--json", "--since", "2026-10-05"],
        capsys)
    filtered = json.loads(out)
    assert filtered["filter"]["runs_shown"] == 2
    assert filtered["runs"] == 2


# ---------------------------------------------------------------------------
# Item D: watch profile reload
# ---------------------------------------------------------------------------

W_MAIN = "def main():\n    return 1\n"
W_MAIN_V2 = "def main():\n    return 1234567890  # a longer body line\n"
W_UTIL = "def helper():\n    return 2\n"
PROFILE_V1 = json.dumps({"modes": {"**/*.py": "signatures"}})
PROFILE_V2_IGNORE_UTIL = json.dumps({"ignore": ["util.py"]})


class ScriptedSleep:
    """Same driver as test_v06_watch: scripted actions per sleep
    call, KeyboardInterrupt to end the session."""

    def __init__(self, actions=None, ki_at=None):
        self.actions = actions or {}
        self.calls = 0
        self.ki_at = ki_at

    def __call__(self, seconds):
        self.calls += 1
        if self.ki_at is not None and self.calls >= self.ki_at:
            raise KeyboardInterrupt
        action = self.actions.get(self.calls)
        if action is not None:
            action()


def _watch_project(root: Path, profile_text: str = PROFILE_V1) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _write(root, "main.py", W_MAIN)
    _write(root, "util.py", W_UTIL)
    if profile_text is not None:
        _write(root, ".ghostslice.json", profile_text)
    return root


def _manifest_paths(bundle: Path) -> list:
    manifest = json.loads(
        (bundle / "manifest.json").read_text(encoding="utf-8"))
    return [f["path"] for f in manifest["files"]]


def _run_watch_captured(proj, capsys, **kwargs):
    summary = run_watch(proj, **kwargs)
    out = capsys.readouterr().out
    return summary, out


def test_watch_valid_profile_edit_applies(tmp_path, capsys):
    proj = _watch_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    sleep = ScriptedSleep(actions={
        1: lambda: _write(proj, ".ghostslice.json",
                          PROFILE_V2_IGNORE_UTIL),
        3: lambda: _write(proj, "main.py", W_MAIN_V2),
    }, ki_at=5)
    summary, out = _run_watch_captured(
        proj, capsys, out=bundle, export=True, debounce=0,
        sleep=sleep, profile=load_profile(proj))
    assert summary["profile_reloads"] == 1
    assert "profile reloaded" in out
    # The reload landed before the settle in the same cycle, so the
    # exports from then on exclude util.py.
    assert "util.py" not in _manifest_paths(bundle)
    assert summary["exports"] >= 2


def test_watch_invalid_profile_keeps_last_good_reports_once(
        tmp_path, capsys):
    proj = _watch_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    bad = "{not json at all"
    sleep = ScriptedSleep(actions={
        1: lambda: _write(proj, ".ghostslice.json", bad),
        # Same bad content saved again: no second report.
        2: lambda: _write(proj, ".ghostslice.json", bad),
        3: lambda: _write(proj, "main.py", W_MAIN_V2),
    }, ki_at=5)
    summary, out = _run_watch_captured(
        proj, capsys, out=bundle, export=True, debounce=0,
        sleep=sleep, profile=load_profile(proj))
    assert out.count("profile reload failed") == 1
    assert summary["profile_reloads"] == 0
    # Last-good profile kept serving: util.py is still exported.
    assert "util.py" in _manifest_paths(bundle)


def test_watch_profile_fix_recovers(tmp_path, capsys):
    proj = _watch_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    sleep = ScriptedSleep(actions={
        1: lambda: _write(proj, ".ghostslice.json", "{broken"),
        2: lambda: _write(proj, ".ghostslice.json",
                          PROFILE_V2_IGNORE_UTIL),
        3: lambda: _write(proj, "main.py", W_MAIN_V2),
    }, ki_at=5)
    summary, out = _run_watch_captured(
        proj, capsys, out=bundle, export=True, debounce=0,
        sleep=sleep, profile=load_profile(proj))
    assert out.count("profile reload failed") == 1
    assert "profile reloaded" in out
    assert "recovered" in out
    assert summary["profile_reloads"] == 1
    assert "util.py" not in _manifest_paths(bundle)


def test_watch_profile_touch_is_not_a_reload(tmp_path, capsys):
    proj = _watch_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    sleep = ScriptedSleep(actions={
        # Identical bytes, fresh mtime: the hash says no change.
        1: lambda: _write(proj, ".ghostslice.json", PROFILE_V1),
        2: lambda: _write(proj, "main.py", W_MAIN_V2),
    }, ki_at=4)
    summary, out = _run_watch_captured(
        proj, capsys, out=bundle, export=True, debounce=0,
        sleep=sleep, profile=load_profile(proj))
    assert summary["profile_reloads"] == 0
    assert "profile reloaded" not in out
    assert "profile reload failed" not in out
    assert "util.py" in _manifest_paths(bundle)


def test_watch_profile_deleted_reverts_to_defaults(tmp_path, capsys):
    proj = _watch_project(
        tmp_path / "proj",
        profile_text=json.dumps({"ignore": ["util.py"]}))
    bundle = tmp_path / "bundle"
    profile_path = proj / ".ghostslice.json"
    sleep = ScriptedSleep(actions={
        1: profile_path.unlink,
        2: lambda: _write(proj, "main.py", W_MAIN_V2),
    }, ki_at=4)
    summary, out = _run_watch_captured(
        proj, capsys, out=bundle, export=True, debounce=0,
        sleep=sleep, profile=load_profile(proj))
    assert "profile removed" in out
    assert summary["profile_reloads"] == 1
    # Defaults know no ignore list: util.py is back in the bundle.
    assert "util.py" in _manifest_paths(bundle)


def test_watch_profile_created_mid_watch_applies(tmp_path, capsys):
    # Session starts with no profile at all; creating
    # .ghostslice.json mid-watch is the limiting case of an edit
    # and takes effect the same way (audit F1).
    proj = _watch_project(tmp_path / "proj", profile_text=None)
    bundle = tmp_path / "bundle"
    sleep = ScriptedSleep(actions={
        1: lambda: _write(proj, ".ghostslice.json",
                          PROFILE_V2_IGNORE_UTIL),
        2: lambda: _write(proj, "main.py", W_MAIN_V2),
    }, ki_at=4)
    summary, out = _run_watch_captured(
        proj, capsys, out=bundle, export=True, debounce=0,
        sleep=sleep, profile=load_profile(proj))
    assert summary["profile_reloads"] == 1
    assert "profile reloaded" in out
    assert "util.py" not in _manifest_paths(bundle)


class FakeClock:
    """Advances a fixed step per call so debounce windows elapse
    deterministically without real waiting."""

    def __init__(self, step: float = 10.0):
        self.t = 0.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


def test_watch_reload_during_debounce_window_applies(tmp_path, capsys):
    # A file change is pending (debounce window open) when the
    # profile is edited: the reload check runs at the next poll
    # top, before the pending change settles, so the settle's
    # export already uses the new profile — a reload can never
    # land halfway through an export, because exports run inside
    # settle() and the check never runs inside one.
    proj = _watch_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    sleep = ScriptedSleep(actions={
        1: lambda: _write(proj, "main.py", W_MAIN_V2),
        2: lambda: _write(proj, ".ghostslice.json",
                          PROFILE_V2_IGNORE_UTIL),
    }, ki_at=6)
    summary, out = _run_watch_captured(
        proj, capsys, out=bundle, export=True, debounce=1.0,
        interval=0.5, sleep=sleep, clock=FakeClock(),
        profile=load_profile(proj))
    assert summary["profile_reloads"] == 1
    assert summary["events"] >= 1
    assert "util.py" not in _manifest_paths(bundle)


def test_watch_external_profile_file_reloads(tmp_path, capsys):
    # The file the profile was loaded from may live outside the
    # project (run_watch watches profile.path, wherever it points).
    proj = _watch_project(tmp_path / "proj", profile_text=None)
    ext = _write(tmp_path, "elsewhere.json", PROFILE_V1)
    bundle = tmp_path / "bundle"
    sleep = ScriptedSleep(actions={
        1: lambda: _write(tmp_path, "elsewhere.json",
                          PROFILE_V2_IGNORE_UTIL),
        2: lambda: _write(proj, "main.py", W_MAIN_V2),
    }, ki_at=4)
    summary, out = _run_watch_captured(
        proj, capsys, out=bundle, export=True, debounce=0,
        sleep=sleep, profile=load_profile_file(ext))
    assert summary["profile_reloads"] == 1
    assert "profile reloaded" in out
    assert "util.py" not in _manifest_paths(bundle)
