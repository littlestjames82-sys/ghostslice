"""v1.0.2 polish round 2: persistent cache for lint + calls,
call data in the dashboard graph API, configurable duplicate
floors.

The cache contract is byte-parity: cached (cold or warm) and
--no-cache output must be identical, because every cached value
is a pure function of its key dimensions — the same contract
test_v20 pins for exports. The plugin test pins the invalidation
half: editing a plugin changes its digest, which is the cache
namespace, so a stale plugin slice can never be served.

The floors contract is default-parity: unset profile keys resolve
to the historical constants (200 normalized chars / 500 estimated
tokens) everywhere, and a set key moves exactly the surface it
names.
"""
import json
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice import plugins as plugins_mod
from ghostslice.cache import ProjectCache, cache_stats
from ghostslice.callgraph import build_call_graph
from ghostslice.ci import DUP_FLOOR_TOKENS, duplicates_floor_for, run_ci
from ghostslice.cli import main as cli_main
from ghostslice.doctor import run_doctor
from ghostslice.duplicates import (NEAR_MIN_CHARS, find_duplicates,
                                   near_min_chars_for)
from ghostslice.graph import build_graph
from ghostslice.init_wizard import (analyze_project, assemble_profile,
                                    justification_lines)
from ghostslice.lint import lint_project
from ghostslice.profile import Profile, load_profile
from ghostslice.scanner import scan
from ghostslice.server import CALL_DEAD_CAP, CALL_EDGE_CAP, make_server


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
# Item A: cache for lint
# ---------------------------------------------------------------------------

def _big_py(n_funcs: int = 120) -> str:
    parts = []
    for i in range(n_funcs):
        parts.append(
            f"def func_{i}(x):\n"
            f"    total = x + {i}\n"
            "    total = total * 2\n"
            "    total = total - 1\n"
            "    total = total + 5\n"
            "    total = total * 3\n"
            "    return total\n\n")
    return "".join(parts)


@pytest.fixture()
def lint_proj(tmp_path):
    # Profile pins every Python file to full mode, so the lint
    # rules must price real slices (L002) — the derivations the
    # persistent cache serves.
    _write(tmp_path, "big.py", _big_py())
    _write(tmp_path, "small.py", "def tiny():\n    return 1\n")
    _write(tmp_path, ".ghostslice.json",
           json.dumps({"modes": {"**/*.py": "full"}}))
    return tmp_path


def test_lint_payload_parity_cache_off_cold_warm(lint_proj):
    profile = load_profile(lint_proj)
    off = lint_project(lint_proj, profile=profile)
    cold_cache = ProjectCache(lint_proj)
    cold = lint_project(lint_proj, profile=profile, cache=cold_cache)
    warm_cache = ProjectCache(lint_proj)
    warm = lint_project(lint_proj, profile=profile, cache=warm_cache)
    assert off == cold == warm
    # The run really used the cache: scan records and slice results
    # were stored cold, then hit warm.
    stats = cache_stats(lint_proj)
    assert stats["by_kind"]["scan"]["entries"] > 0
    assert stats["by_kind"]["slice"]["entries"] > 0
    assert warm_cache.hits > 0


def test_lint_cli_no_cache_parity_and_flag(lint_proj, capsys):
    code_off, out_off, _ = _cli(
        ["lint", str(lint_proj), "--json", "--no-cache"], capsys)
    assert not (lint_proj / ".ghostslice-cache").exists()
    code_cold, out_cold, _ = _cli(["lint", str(lint_proj), "--json"],
                                  capsys)
    assert (lint_proj / ".ghostslice-cache").is_dir()
    code_warm, out_warm, _ = _cli(["lint", str(lint_proj), "--json"],
                                  capsys)
    assert code_off == code_cold == code_warm
    assert json.loads(out_off) == json.loads(out_cold) \
        == json.loads(out_warm)
    findings = json.loads(out_off)["findings"]
    assert any(f["rule"] == "L002" and f["path"] == "big.py"
               for f in findings)


# ---------------------------------------------------------------------------
# Item A: cache for calls
# ---------------------------------------------------------------------------

@pytest.fixture()
def calls_proj(tmp_path):
    _write(tmp_path, "main.py",
           "from util import helper\n\n\n"
           "def main():\n    return helper()\n")
    _write(tmp_path, "util.py",
           "def helper():\n    return leaf()\n\n\n"
           "def leaf():\n    return 1\n\n\n"
           "def orphan():\n    return 2\n")
    return tmp_path


def test_calls_payload_parity_cache_off_cold_warm(calls_proj):
    result = scan(calls_proj)
    profile = load_profile(calls_proj)
    graph = build_graph(result)
    off = build_call_graph(result, profile, graph)
    cold_cache = ProjectCache(calls_proj)
    cold = build_call_graph(result, profile, graph, cache=cold_cache)
    warm_cache = ProjectCache(calls_proj)
    warm = build_call_graph(result, profile, graph, cache=warm_cache)
    assert off == cold == warm
    stats = cache_stats(calls_proj)
    assert stats["by_kind"]["outline"]["entries"] > 0
    assert warm_cache.hits > 0


def test_calls_cli_no_cache_parity_and_flag(calls_proj, capsys):
    code_off, out_off, _ = _cli(
        ["calls", str(calls_proj), "--json", "--no-cache"], capsys)
    assert not (calls_proj / ".ghostslice-cache").exists()
    code_cold, out_cold, _ = _cli(["calls", str(calls_proj), "--json"],
                                  capsys)
    assert (calls_proj / ".ghostslice-cache").is_dir()
    code_warm, out_warm, _ = _cli(["calls", str(calls_proj), "--json"],
                                  capsys)
    assert code_off == code_cold == code_warm == 0
    # Byte-for-byte: the CLI prints one deterministic JSON document.
    assert out_off == out_cold == out_warm


def test_calls_plugin_edit_moves_cache_namespace(tmp_path, capsys):
    # The calls CLI opens its cache under the active plugin
    # digest, exactly like lint: editing the plugin must move the
    # namespace (old entries orphaned, new ones stored), and the
    # output must stay byte-identical throughout (audit #2).
    _write(tmp_path, "tools/lua_slicer.py", PLUGIN_V1)
    _write(tmp_path, "main.py",
           "def main():\n    return helper()\n\n"
           "def helper():\n    return 1\n")
    _write(tmp_path, ".ghostslice.json", json.dumps(
        {"plugins": ["tools/lua_slicer.py"]}))
    _code, out1, _ = _cli(["calls", str(tmp_path), "--json"], capsys)
    n1 = cache_stats(tmp_path)["entries"]
    assert n1 > 0
    _write(tmp_path, "tools/lua_slicer.py",
           PLUGIN_V1 + "\n# byte change: new digest, new namespace\n")
    _code, out2, _ = _cli(["calls", str(tmp_path), "--json"], capsys)
    assert cache_stats(tmp_path)["entries"] > n1
    _code, out3, _ = _cli(
        ["calls", str(tmp_path), "--json", "--no-cache"], capsys)
    assert out1 == out2 == out3


def test_calls_unparseable_file_skipped_cold_and_warm(tmp_path):
    _write(tmp_path, "broken.py", "def broken(:\n    return\n")
    _write(tmp_path, "ok.py", "def ok():\n    return 1\n")
    result = scan(tmp_path)
    profile = load_profile(tmp_path)
    graph = build_graph(result)
    cold = build_call_graph(result, profile, graph,
                            cache=ProjectCache(tmp_path))
    warm = build_call_graph(result, profile, graph,
                            cache=ProjectCache(tmp_path))
    assert cold == warm
    assert cold["skipped_files"] == ["broken.py"]


def test_scan_dead_symbol_pass_reuses_open_cache(calls_proj, capsys):
    # Audit F1: the scan command already opens the cache for its
    # scan records; its dead-symbol pass (a full CallGraph build)
    # must reuse the outline kind through the same cache, with
    # byte-identical output.
    code_off, out_off, _ = _cli(
        ["scan", str(calls_proj), "--json", "--no-cache"], capsys)
    assert not (calls_proj / ".ghostslice-cache").exists()
    code_on, out_on, _ = _cli(["scan", str(calls_proj), "--json"],
                              capsys)
    assert code_off == code_on == 0
    assert out_off == out_on
    stats = cache_stats(calls_proj)
    assert stats["by_kind"]["outline"]["entries"] > 0
    recs = json.loads(out_on)["recommendations"]
    assert any(r.get("kind") == "dead-symbol" for r in recs)


# ---------------------------------------------------------------------------
# Item A: plugin edits invalidate lint's cached slices (digest = namespace)
# ---------------------------------------------------------------------------

PLUGIN_V1 = '''
LANGUAGE = "lua"
EXTENSIONS = [".lua"]


def slice_text(path, text, mode):
    if mode == "signatures":
        return "-- signatures only\\n"
    return text


def outline(path, text):
    return []
'''

PLUGIN_V2 = '''
LANGUAGE = "lua"
EXTENSIONS = [".lua"]


def slice_text(path, text, mode):
    return text


def outline(path, text):
    return []
'''


def _big_lua(n_funcs: int = 300) -> str:
    parts = []
    for i in range(n_funcs):
        parts.append(
            f"local function f{i}()\n"
            f"  local x = {i}\n"
            "  local y = x + 1\n"
            "  local z = y * 2\n"
            "  return z\n"
            "end\n\n")
    return "".join(parts)


def test_lint_plugin_edit_invalidates_cached_slices(tmp_path, capsys):
    _write(tmp_path, "tools/lua_slicer.py", PLUGIN_V1)
    _write(tmp_path, "big.lua", _big_lua())
    _write(tmp_path, ".ghostslice.json", json.dumps(
        {"plugins": ["tools/lua_slicer.py"],
         "modes": {"**/*.lua": "full"}}))

    def l002_paths(out: str) -> set:
        payload = json.loads(out)
        return {f["path"] for f in payload["findings"]
                if f["rule"] == "L002"}

    _, out_cold, _ = _cli(["lint", str(tmp_path), "--json"], capsys)
    assert l002_paths(out_cold) == {"big.lua"}
    _, out_warm, _ = _cli(["lint", str(tmp_path), "--json"], capsys)
    assert out_warm == out_cold

    # Edit the plugin: slices are now identity, so the L002 saving
    # vanishes. The plugin digest is the cache namespace, so the
    # warm cache from v1 must not serve its slices.
    _write(tmp_path, "tools/lua_slicer.py", PLUGIN_V2)
    _, out_v2, _ = _cli(["lint", str(tmp_path), "--json"], capsys)
    assert l002_paths(out_v2) == set()
    _, out_v2_off, _ = _cli(
        ["lint", str(tmp_path), "--json", "--no-cache"], capsys)
    assert out_v2 == out_v2_off


# ---------------------------------------------------------------------------
# Item B: call data in the dashboard graph API + UI
# ---------------------------------------------------------------------------

@pytest.fixture()
def dash(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _write(root, "main.py",
           "from util import helper\n\n\n"
           "def main():\n    return helper()\n\n\n"
           "if __name__ == '__main__':\n    main()\n")
    _write(root, "util.py",
           "def helper():\n    return leaf()\n\n\n"
           "def leaf():\n    return 1\n\n\n"
           "def orphan():\n    return 2\n")
    _write(root, "app.js", "function go() { return 1; }\n")
    _write(root, "evil<script>.py", "def sneaky():\n    return 0\n")
    server, state = make_server(str(root), port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    yield root, state, port
    server.shutdown()
    server.server_close()


def _get(port, path):
    with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=30) as r:
        return r.status, r.read().decode("utf-8")


def _get_json(port, path):
    status, body = _get(port, path)
    return status, json.loads(body)


def test_graph_api_carries_call_chain(dash):
    _root, _state, port = dash
    status, data = _get_json(port, "/api/graph")
    assert status == 200
    calls = data["calls"]
    pairs = {(e["caller"], e["callee"]) for e in calls["edges"]
             if e["kind"] != "reference"}
    assert ("main.py:main", "util.py:helper") in pairs
    assert ("util.py:helper", "util.py:leaf") in pairs
    assert calls["edges_truncated"] is False
    assert calls["edges_total"] == len(calls["edges"])
    assert "Python" in calls["scope"]


def test_graph_api_symbol_with_no_calls_and_dead(dash):
    _root, _state, port = dash
    _status, data = _get_json(port, "/api/graph")
    calls = data["calls"]
    outgoing = {e["caller"] for e in calls["edges"]
                if e["kind"] != "reference"}
    incoming = {e["callee"] for e in calls["edges"]
                if e["kind"] != "reference"}
    # leaf calls nothing; orphan is called by nothing and is a
    # dead candidate.
    assert "util.py:leaf" not in outgoing
    assert "util.py:leaf" in incoming
    assert "util.py:orphan" not in incoming
    assert "orphan" in {d["qualified"] for d in calls["dead"]}
    by_id = {s["id"]: s for s in calls["symbols"]}
    assert by_id["util.py:leaf"]["fan_in"] == 1
    assert by_id["util.py:orphan"]["fan_in"] == 0


def test_graph_api_non_python_and_xss_names(dash):
    _root, _state, port = dash
    _status, data = _get_json(port, "/api/graph")
    calls = data["calls"]
    # Non-Python files honestly contribute no symbols or edges.
    assert not any(s["path"] == "app.js" for s in calls["symbols"])
    assert not any("app.js" in e["caller"] or "app.js" in e["callee"]
                   for e in calls["edges"])
    # An HTML-shaped file name travels as inert JSON data; the UI
    # renders it with textContent (pinned by the page test below).
    assert "evil<script>.py:sneaky" in {s["id"] for s in calls["symbols"]}


def test_dashboard_page_renders_calls_textcontent_only(dash):
    _root, _state, port = dash
    status, body = _get(port, "/")
    assert status == 200
    # The v1.0.1 pin still holds with the call view added: no
    # innerHTML anywhere in the served page.
    assert ".innerHTML" not in body
    assert 'id="calls"' in body
    assert "renderCalls" in body
    assert "name.textContent = s.qualified" in body


def test_graph_api_concurrent_first_requests_agree(dash):
    # Audit #2 probe, pinned: the lazy build is double-checked
    # locked, so simultaneous first requests all serve the one
    # memoised payload.
    _root, state, port = dash
    bodies = []

    def hit():
        _status, body = _get(port, "/api/graph")
        bodies.append(body)

    threads = [threading.Thread(target=hit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(bodies) == 8 and len(set(bodies)) == 1
    assert state.calls_payload() is state.calls_payload()


def test_calls_payload_caps_edges_and_dead(tmp_path):
    # A 2,200-function chain: 2,199 call edges and every function
    # unreachable from a root, so both caps engage.
    n = CALL_EDGE_CAP + 200
    parts = []
    for i in range(n):
        nxt = f"f{i + 1}()" if i + 1 < n else "0"
        parts.append(f"def f{i}():\n    return {nxt}\n\n")
    _write(tmp_path, "chain.py", "".join(parts))
    _server, state = make_server(str(tmp_path), port=0)
    payload = state.calls_payload()
    assert payload["edges_total"] > CALL_EDGE_CAP
    assert len(payload["edges"]) == CALL_EDGE_CAP
    assert payload["edges_truncated"] is True
    assert payload["dead_total"] > CALL_DEAD_CAP
    assert len(payload["dead"]) == CALL_DEAD_CAP
    assert payload["dead_truncated"] is True
    # Memoised for the server run.
    assert state.calls_payload() is payload


# ---------------------------------------------------------------------------
# Item C: configurable duplicate floors
# ---------------------------------------------------------------------------

NEAR_A = "\n".join(f"alpha bravo {i}" for i in range(13)) + "\n"
NEAR_B = "\n".join([f"alpha bravo {i}" for i in range(12)]
                   + ["alpha bravo X"]) + "\n"


@pytest.fixture()
def near_proj(tmp_path):
    # 184 normalized chars, 13 distinct lines, similarity 0.857:
    # below the default 200-char floor, above a lowered one.
    _write(tmp_path, "a.txt", NEAR_A)
    _write(tmp_path, "b.txt", NEAR_B)
    return tmp_path


def test_find_duplicates_default_parity(near_proj):
    result = scan(near_proj)
    unset = find_duplicates(result)
    assert unset == find_duplicates(result, near_min_chars=NEAR_MIN_CHARS)
    assert unset == find_duplicates(
        result, near_min_chars=near_min_chars_for(None))
    assert unset == find_duplicates(
        result, near_min_chars=near_min_chars_for(Profile()))
    assert unset["near"] == []


def test_near_floor_lowered_and_raised(near_proj):
    result = scan(near_proj)
    lowered = find_duplicates(result, near_min_chars=100)
    assert len(lowered["near"]) == 1
    assert lowered["near"][0]["files"] == ["a.txt", "b.txt"]
    raised = find_duplicates(result, near_min_chars=500)
    assert raised["near"] == []
    # The exact comparison is not the near floor's business.
    assert raised["exact"] == lowered["exact"] == []


def test_profile_floor_sections_parse_and_resolve(tmp_path):
    _write(tmp_path, ".ghostslice.json", json.dumps(
        {"duplicates": {"near_min_chars": 100},
         "ci": {"duplicates_floor_tokens": 42}}))
    profile = load_profile(tmp_path)
    assert profile.duplicates == {"near_min_chars": 100}
    assert profile.ci == {"duplicates_floor_tokens": 42}
    assert near_min_chars_for(profile) == 100
    assert duplicates_floor_for(profile) == 42
    assert profile.to_dict()["duplicates"] == {"near_min_chars": 100}
    assert profile.to_dict()["ci"] == {"duplicates_floor_tokens": 42}
    plain = load_profile(tmp_path.parent)  # no profile file there
    assert near_min_chars_for(plain) == NEAR_MIN_CHARS == 200
    assert duplicates_floor_for(plain) == DUP_FLOOR_TOKENS == 500


def test_profile_floor_rejects_non_finite_numbers(tmp_path):
    # Python's json module accepts Infinity/NaN literals; a floor
    # must still be a finite positive whole number (audit #2).
    for raw in ('{"ci": {"duplicates_floor_tokens": Infinity}}',
                '{"duplicates": {"near_min_chars": NaN}}'):
        _write(tmp_path, ".ghostslice.json", raw)
        with pytest.raises(ValueError):
            load_profile(tmp_path)


def test_floors_at_extremes(tmp_path):
    # Floor 1 admits the small pair; floor 10^9 silences the
    # comparison without error (audit #2).
    _write(tmp_path, "a.txt", NEAR_A)
    _write(tmp_path, "b.txt", NEAR_B)
    result = scan(tmp_path)
    assert len(find_duplicates(result, near_min_chars=1)["near"]) == 1
    assert find_duplicates(result, near_min_chars=10**9)["near"] == []


@pytest.mark.parametrize("bad", [
    {"duplicates": {"near_min_char": 5}},          # typo'd key
    {"duplicates": {"near_min_chars": 0}},         # zero
    {"duplicates": {"near_min_chars": -3}},        # negative
    {"duplicates": {"near_min_chars": "100"}},     # string
    {"duplicates": {"near_min_chars": 12.5}},      # fractional
    {"duplicates": {"near_min_chars": True}},      # bool
    {"duplicates": [100]},                        # not an object
    {"ci": {"duplicates_floor_tokens": 0}},
    {"ci": {"duplicates_floor_tokens": -1}},
    {"ci": {"duplicates_floor_token": 5}},         # typo'd key
    {"ci": {"duplicates_floor_tokens": "500"}},
])
def test_profile_floor_validation_is_loud(tmp_path, bad):
    _write(tmp_path, ".ghostslice.json", json.dumps(bad))
    with pytest.raises(ValueError):
        load_profile(tmp_path)


def test_doctor_accepts_floors_and_flags_typo(tmp_path):
    _write(tmp_path, "main.py", "def main():\n    return 1\n")
    _write(tmp_path, ".ghostslice.json", json.dumps(
        {"duplicates": {"near_min_chars": 100},
         "ci": {"duplicates_floor_tokens": 42}}))
    payload = run_doctor(tmp_path)
    check = next(c for c in payload["checks"] if c["id"] == "profile")
    assert check["status"] == "ok"
    assert "duplicates" in check["detail"] and "ci" in check["detail"]

    _write(tmp_path, ".ghostslice.json", json.dumps(
        {"ci": {"duplicates_floor_token": 42}}))
    payload = run_doctor(tmp_path)
    check = next(c for c in payload["checks"] if c["id"] == "profile")
    assert check["status"] == "fail"
    assert "duplicates_floor_token" in check["detail"]


def test_lint_uses_profile_near_floor(near_proj):
    off = lint_project(near_proj)
    assert not any(f["rule"] == "L004" for f in off["findings"])
    _write(near_proj, ".ghostslice.json", json.dumps(
        {"duplicates": {"near_min_chars": 100}}))
    on = lint_project(near_proj)
    l004 = [f for f in on["findings"] if f["rule"] == "L004"]
    assert len(l004) == 1 and "near-duplicate" in l004[0]["message"]


def test_ci_duplicates_floor_from_profile(tmp_path):
    # Two identical files, ~321 estimated tokens each: the group's
    # recoverable tokens sit between the test floors (100 < 321
    # < 500 < 100000).
    text = ("# Notes\n\n" + "".join(
        f"Sentence number {i} about the project and its context.\n"
        for i in range(25)))
    _write(tmp_path, "one.md", text)
    _write(tmp_path, "two.md", text)

    def dup_check(payload):
        return next(c for c in payload["checks"]
                    if c["id"] == "duplicates")

    default = dup_check(run_ci(tmp_path))
    assert default["status"] == "pass"
    assert default["details"]["floor_tokens"] == 500

    _write(tmp_path, ".ghostslice.json", json.dumps(
        {"ci": {"duplicates_floor_tokens": 100}}))
    lowered = dup_check(run_ci(tmp_path))
    assert lowered["status"] == "warn"
    assert lowered["details"]["floor_tokens"] == 100
    assert lowered["details"]["groups"]

    _write(tmp_path, ".ghostslice.json", json.dumps(
        {"ci": {"duplicates_floor_tokens": 100000}}))
    raised = dup_check(run_ci(tmp_path))
    assert raised["status"] == "pass"
    assert raised["details"]["floor_tokens"] == 100000


def test_init_justifications_document_the_floors(tmp_path):
    _write(tmp_path, "main.py", "def main():\n    return 1\n")
    analysis = analyze_project(tmp_path)
    lines = justification_lines(analysis)
    dup_line = next(ln for ln in lines if ln.startswith("duplicates:"))
    ci_line = next(ln for ln in lines if ln.startswith("ci:"))
    assert "near_min_chars" in dup_line and "200" in dup_line
    assert "duplicates_floor_tokens" in ci_line and "500" in ci_line
    # Documented, not written: the generated profile stays at the
    # defaults, exactly like the lint section.
    data = assemble_profile(analysis)
    assert "duplicates" not in data and "ci" not in data
