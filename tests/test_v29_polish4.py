"""v1.0.4 polish round 4: cyclic-symlink sweep for the unswept
surfaces, Go + Rust symbol depth, watch plugin reload.

Contracts:
- The scanner has never descended into directory symlinks; the
  dashboard, workspace detection, a workspace-scoped command,
  watch, CI, and the MCP loader all terminate on cyclic trees
  and never serve or claim content outside the project root.
  Workspace detection (the one surface that was NOT safe)
  reports no package for a member reached through a directory
  symlink (escape or ancestor alias) and warns about each.
- Go outlines name generic functions, attribute methods on
  multi-parameter generic receivers to the base type, and
  enumerate generic interface methods. Rust outlines name the
  real type for impl headers with nested generics (associated
  type bindings closed by '>>') and treat a multi-line
  where-clause impl as a region, so its methods are attributed
  to the implementing type.
- Watch re-applies plugin changes at poll tops when the session
  manages plugins: a changed list applies, a byte edit applies
  (under the new set's cache namespace — exports after the swap
  equal a fresh load's output), a failed load keeps the last-good
  set with one report per distinct bad content, and an unchanged
  session is silent.
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice import plugins as plugins_mod
from ghostslice.ci import run_ci
from ghostslice.cli import main as cli_main
from ghostslice.exporter import build_bundle
from ghostslice.mcp_server import handle_message
from ghostslice.profile import load_profile
from ghostslice.scanner import scan
from ghostslice.server import make_server
from ghostslice.slicer import slice_text
from ghostslice.symslice import outline_source, slice_with_symbols
from ghostslice.watch import run_watch
from ghostslice.workspaces import detect_workspaces


@pytest.fixture(autouse=True)
def _reset_plugins():
    plugins_mod.reset()
    yield
    plugins_mod.reset()


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _symlink(target, link: Path) -> None:
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symlinks not permitted")


# ---------------------------------------------------------------------------
# Item A: cyclic symlinks through dashboard / workspaces / watch / ci / MCP
# ---------------------------------------------------------------------------

OUTSIDE_MARKER = "outside-content-marker"


def _cyclic_project(base: Path) -> Path:
    """A project laced with directory cycles and escapes.

    sub/loop -> .. (cycle), sub/self -> . , a_link <-> b_link
    (dangling loop), outside_link -> a dir OUTSIDE the root,
    pkgs/linkd -> ../pkgs (symlinked member aliasing an ancestor
    of the real member pkgs/one), pkgs/ext -> outside (symlinked
    member escaping the root), escape.py -> an outside FILE
    (file symlinks are followed by design; its content must
    still never be SERVED by the dashboard).
    """
    outside = base / "outside"
    outside.mkdir(parents=True)
    _write(outside, "secret.py", f"TOKEN = '{OUTSIDE_MARKER}'\n")
    _write(outside, "package.json", '{"name": "outside"}\n')
    root = base / "proj"
    _write(root, "app.py", "def main():\n    return 1\n")
    _write(root, "sub/mod.py", "def mod():\n    return 2\n")
    _write(root, "package.json", json.dumps(
        {"name": "r",
         "workspaces": ["pkgs/*", "pkgs/linkd", "pkgs/ext"]}))
    _write(root, "pkgs/one/package.json", '{"name": "one"}')
    _write(root, "pkgs/one/index.py", "X = 1\n")
    _symlink("..", root / "sub" / "loop")
    _symlink(".", root / "sub" / "self")
    _symlink("b_link", root / "a_link")
    _symlink("a_link", root / "b_link")
    _symlink(str(outside), root / "outside_link")
    _symlink("../pkgs", root / "pkgs" / "linkd")
    _symlink(str(outside), root / "pkgs" / "ext")
    _symlink(str(outside / "secret.py"), root / "escape.py")
    return root


def test_scan_terminates_and_stays_inside_on_cycles(tmp_path):
    root = _cyclic_project(tmp_path)
    paths = sorted(f.path for f in scan(root).files)
    assert paths == ["app.py", "escape.py", "package.json",
                     "pkgs/one/index.py", "pkgs/one/package.json",
                     "sub/mod.py"]


def test_workspace_detection_skips_symlinked_members(tmp_path):
    root = _cyclic_project(tmp_path)
    info = detect_workspaces(root)
    assert [p.path for p in info.packages] == ["", "pkgs/one"]
    assert info.missing == []
    warned = " ".join(info.warnings)
    assert "pkgs/linkd" in warned and "pkgs/ext" in warned
    assert "symbolic link" in warned
    # The real member is unaffected.
    assert info.package_for("pkgs/one/index.py") == "pkgs/one"


def test_workspace_glob_through_symlinked_prefix_warns(tmp_path):
    root = tmp_path / "proj"
    _write(root, "pkgs/one/package.json", '{"name": "one"}')
    _write(root, "pkgs/one/index.py", "X = 1\n")
    _write(root, "package.json", json.dumps(
        {"name": "r", "workspaces": ["links/*"]}))
    _symlink("pkgs", root / "links")
    info = detect_workspaces(root)
    # The glob matched nothing real: not a package, and reported
    # as symlink-skipped rather than "missing" (Improve #2).
    assert [p.path for p in info.packages] == [""]
    assert info.missing == []
    assert any("links/*" in w and "symbolic link" in w
               for w in info.warnings)


def test_workspace_fallback_ignores_symlinked_children(tmp_path):
    root = tmp_path / "proj"
    _write(root, "real/package.json", '{"name": "real"}')
    _write(root, "real/index.py", "X = 1\n")
    _write(root, "top.py", "Y = 2\n")
    _symlink("real", root / "alink")
    _symlink(".", root / "selflink")
    info = detect_workspaces(root)
    # Before the fix, 'alink' and 'selflink/real' appeared as
    # phantom detected packages; after it, only the real dir.
    assert [p.path for p in info.packages] == ["", "real"]


def _serve(root: Path):
    server, state = make_server(str(root), port=0)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    return server, server.server_address[1]


def _get(port: int, path: str):
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}", timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def test_dashboard_answers_and_never_serves_outside_content(tmp_path):
    root = _cyclic_project(tmp_path)
    server, port = _serve(root)
    try:
        code, body = _get(port, "/api/scan")
        assert code == 200
        payload = json.loads(body)
        assert sorted(f["path"] for f in payload["files"]) == [
            "app.py", "escape.py", "package.json", "pkgs/one/index.py",
            "pkgs/one/package.json", "sub/mod.py"]
        code, body = _get(port, "/api/graph")
        assert code == 200 and "calls" in json.loads(body)
        # The escaping FILE symlink is scanned (documented) but
        # its content is never served.
        for ep in ("/api/preview?path=escape.py",
                   "/api/slice?path=escape.py"):
            code, body = _get(port, ep)
            assert code == 403, ep
            assert OUTSIDE_MARKER not in body
        code, body = _get(port, "/api/preview?path=../outside/secret.py")
        assert code == 400 and OUTSIDE_MARKER not in body
        code, body = _get(port, "/api/preview?path=sub/mod.py")
        assert code == 200 and OUTSIDE_MARKER not in body
    finally:
        server.shutdown()
        server.server_close()


def test_ci_terminates_on_cyclic_project(tmp_path):
    root = _cyclic_project(tmp_path)
    payload = run_ci(root, budget=100000)
    assert {c["id"] for c in payload["checks"]} == {
        "budget", "lint", "secrets", "fit", "duplicates"}
    assert payload["exit_code"] in (0, 1)


def test_mcp_scan_project_on_cyclic_project(tmp_path):
    root = _cyclic_project(tmp_path)
    resp = handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "scan_project",
                   "arguments": {"path": str(root)}}})
    assert isinstance(resp, dict) and "result" in resp


class _Script:
    """Scripted sleep: run actions per call, then KeyboardInterrupt."""

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


def test_watch_survives_cycle_introduced_mid_run(tmp_path):
    root = tmp_path / "proj"
    _write(root, "a.py", "A = 1\n")
    _write(root, "sub/b.py", "B = 2\n")
    outside = tmp_path / "outside"
    _write(outside, "secret.py", f"TOKEN = '{OUTSIDE_MARKER}'\n")

    def introduce():
        _symlink("..", root / "sub" / "loop")
        _symlink(str(outside), root / "escape_dir")
        _write(root, "c.py", "C = 3\n")

    stream = io.StringIO()
    summary = run_watch(root, interval=0.01, debounce=0, max_events=1,
                        sleep=_Script(actions={1: introduce}),
                        stream=stream)
    assert summary["events"] == 1
    out = stream.getvalue()
    assert "c.py" in out
    assert "loop" not in out and "escape_dir" not in out
    assert OUTSIDE_MARKER not in out


# ---------------------------------------------------------------------------
# Item B: Go + Rust symbol depth
# ---------------------------------------------------------------------------

GO_SRC = '''package stack

// Stack is a generic LIFO stack.
type Stack[T any] struct {
\titems []T
}

func (s *Stack[T]) Push(v T) {
\ts.items = append(s.items, v)
}

func (s *Stack[T]) Pop() (T, bool) {
\tvar zero T
\tif len(s.items) == 0 {
\t\treturn zero, false
\t}
\ttop := s.items[len(s.items)-1]
\ts.items = s.items[:len(s.items)-1]
\treturn top, true
}

// Map applies f to every element.
func Map[T any, U any](in []T, f func(T) U) []U {
\tout := make([]U, len(in))
\tfor i, v := range in {
\t\tout[i] = f(v)
\t}
\treturn out
}

func Min[T Ordered](a, b T) T {
\tif a < b {
\t\treturn a
\t}
\treturn b
}

// Pair is a generic two-tuple.
type Pair[K comparable, V any] struct {
\tKey   K
\tValue V
}

func (p Pair[K, V]) Swap() Pair[V, K] {
\treturn Pair[V, K]{Key: p.Value, Value: p.Key}
}

// Ordered is a generic interface.
type Ordered[T any] interface {
\tCompare(T) int
\tRank() int
}

func helper() int { return 42 }
'''

RS_SRC = '''use std::fmt;

pub struct Stack<T> {
    items: Vec<T>,
}

impl<T> Stack<T> {
    pub fn new() -> Self {
        Stack { items: Vec::new() }
    }

    pub fn push(&mut self, v: T) {
        self.items.push(v);
    }
}

impl<T: Clone> Stack<T> {
    pub fn cloned_top(&self) -> Option<T> {
        self.items.last().cloned()
    }
}

impl<T> fmt::Display for Stack<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Stack({} items)", self.items.len())
    }
}

impl<T> Iterator for Pair<T>
where
    T: Clone,
{
    type Item = T;

    fn next(&mut self) -> Option<Self::Item> {
        self.first.clone()
    }
}

pub struct Pair<T> {
    first: Option<T>,
}

impl<I: Iterator<Item = u8>> Wrapper<I> {
    pub fn total(&self) -> u64 {
        self.iter.by_ref().sum::<u64>() as u64
    }
}

pub struct Wrapper<I> {
    iter: I,
}

fn free_fn() -> i32 { 42 }
'''


def _by_qualified(symbols):
    return {s.qualified: s for s in symbols}


def test_go_generic_functions_are_outlined():
    syms = _by_qualified(outline_source(GO_SRC, "go", "stack.go"))
    assert syms["Map"].kind == "function"
    assert syms["Min"].kind == "function"
    # Spans cover the bodies, like plain functions.
    span = GO_SRC.splitlines()[syms["Map"].start:syms["Map"].end + 1]
    assert any("return out" in line for line in span)


def test_go_generic_receiver_methods_parent_to_base_type():
    syms = _by_qualified(outline_source(GO_SRC, "go", "stack.go"))
    assert syms["Pair.Swap"].parent == "Pair"
    assert syms["Stack.Push"].parent == "Stack"
    assert syms["Stack.Pop"].parent == "Stack"
    # No garbage parents from a whitespace split of the type args.
    assert not any("]" in (s.parent or "") for s in syms.values())


def test_go_generic_interface_methods_enumerated():
    syms = _by_qualified(outline_source(GO_SRC, "go", "stack.go"))
    assert syms["Ordered"].kind == "type"
    assert syms["Ordered.Compare"].parent == "Ordered"
    assert syms["Ordered.Rank"].parent == "Ordered"


def test_go_selection_keeps_generic_symbols():
    out = slice_with_symbols("stack.go", GO_SRC, {"Pair.Swap", "Map"})
    assert "return Pair[V, K]{Key: p.Value, Value: p.Key}" in out
    assert "out[i] = f(v)" in out
    # Unselected generic bodies are stubbed, not dropped silently.
    assert "{ /* ... */ }" in out


def test_go_signatures_mode_includes_generics():
    text = slice_text("stack.go", GO_SRC, "signatures").text
    assert "func Map[T any, U any](in []T, f func(T) U) []U" in text
    assert "func Min[T Ordered](a, b T) T" in text
    assert "type Stack[T any] struct" in text
    assert "type Pair[K comparable, V any] struct" in text
    assert "type Ordered[T any] interface" in text


def test_rust_nested_generic_impl_names_the_type():
    syms = outline_source(RS_SRC, "rust", "stack.rs")
    by_q = _by_qualified(syms)
    assert "Wrapper" in by_q and by_q["Wrapper"].kind in ("impl", "type")
    impls = [s for s in syms if s.kind == "impl"]
    assert {s.name for s in impls} == {"Stack", "Pair", "Wrapper"}
    assert by_q["Wrapper.total"].parent == "Wrapper"
    assert not any(s.name == ">" or (s.parent or "") == ">"
                   for s in syms)


def test_rust_where_clause_impl_is_a_region():
    syms = outline_source(RS_SRC, "rust", "stack.rs")
    by_q = _by_qualified(syms)
    impl = next(s for s in syms
                if s.kind == "impl" and s.name == "Pair")
    next_sym = by_q["Pair.next"]
    assert next_sym.parent == "Pair"
    assert impl.start < next_sym.start <= impl.end
    # Not a parentless free function (the pre-fix shape).
    assert not any(s.qualified == "next" for s in syms)


def test_rust_multiple_impl_blocks_stay_separate():
    syms = outline_source(RS_SRC, "rust", "stack.rs")
    by_q = _by_qualified(syms)
    stack_impls = [s for s in syms
                   if s.kind == "impl" and s.name == "Stack"]
    assert len(stack_impls) == 3
    spans = {(s.start, s.end) for s in stack_impls}
    assert len(spans) == 3
    for q in ("Stack.new", "Stack.push", "Stack.cloned_top",
              "Stack.fmt"):
        assert by_q[q].parent == "Stack"


def test_rust_selection_keeps_where_and_nested_impl_methods():
    out = slice_with_symbols("stack.rs", RS_SRC,
                             {"Wrapper.total", "Pair.next"})
    assert "self.iter.by_ref().sum::<u64>() as u64" in out
    assert "self.first.clone()" in out


# ---------------------------------------------------------------------------
# Item C: watch plugin reload
# ---------------------------------------------------------------------------

WIB_SRC = "def alpha():\nbody one\nkeep this line\ndef beta():\nbody two\n"

WIB_PLUGIN_V1 = '''NAME = "Wibble"
LANGUAGE = "wibble"
EXTENSIONS = [".wib"]

def slice_text(path, text, mode):
    if mode == "signatures":
        return "\\n".join(
            l for l in text.split("\\n") if l.startswith("def ")) + "\\n"
    return text
'''

WIB_PLUGIN_V2 = '''NAME = "Wibble"
LANGUAGE = "wibble"
EXTENSIONS = [".wib"]

def slice_text(path, text, mode):
    if mode == "signatures":
        return "\\n".join(
            l for l in text.split("\\n")
            if l.startswith("def ") or l.startswith("keep")) + "\\n"
    return text
'''

WIB_PLUGIN_BAD = "LANGUAGE = 'wibble'\ndef broken(:\n"


def _wib_project(root: Path, *, with_plugin: bool = True) -> Path:
    _write(root, "a.wib", WIB_SRC)
    _write(root, "tools/wib.py", WIB_PLUGIN_V1)
    profile = {"modes": {"**/*.wib": "signatures"}}
    if with_plugin:
        profile["plugins"] = ["tools/wib.py"]
    _write(root, ".ghostslice.json", json.dumps(profile))
    return root


def _activate_startup(proj: Path):
    """Mirror the CLI: load the startup set and activate it."""
    profile = load_profile(proj)
    pset = plugins_mod.load_for_project(proj, profile=profile)
    plugins_mod.activate(pset)
    return profile


def _wib_bundle_text(bundle: Path) -> str:
    return (bundle / "files" / "a.wib").read_text(encoding="utf-8")


def test_watch_plugin_byte_edit_applies_and_matches_fresh(tmp_path):
    proj = _wib_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    profile = _activate_startup(proj)
    stream = io.StringIO()
    sleep = _Script(actions={
        1: lambda: _write(proj, "tools/wib.py", WIB_PLUGIN_V2),
    }, ki_at=4)
    summary = run_watch(proj, out=bundle, export=True, debounce=0,
                        sleep=sleep, profile=profile,
                        manage_plugins=True, stream=stream)
    assert summary["plugin_reloads"] == 1
    out = stream.getvalue()
    assert "plugins reloaded" in out
    assert "only load plugins you trust" in out  # trust warning
    # The settled export after the swap used V2...
    sliced = _wib_bundle_text(bundle)
    assert "keep this line" in sliced
    # ...and equals what a fresh load of V2 produces through the
    # same (persisted) cache — no stale V1 derivation leaked.
    fresh_bundle = tmp_path / "fresh"
    manifest = build_bundle(proj, fresh_bundle, profile=load_profile(proj))
    assert _wib_bundle_text(fresh_bundle) == sliced
    assert manifest["total_sliced_tokens"] > 0


def test_watch_plugin_list_change_applies(tmp_path):
    proj = _wib_project(tmp_path / "proj", with_plugin=False)
    bundle = tmp_path / "bundle"
    profile = _activate_startup(proj)  # no plugins at startup
    stream = io.StringIO()

    def add_plugin_to_profile():
        _write(proj, ".ghostslice.json", json.dumps(
            {"modes": {"**/*.wib": "signatures"},
             "plugins": ["tools/wib.py"]}))

    sleep = _Script(actions={1: add_plugin_to_profile}, ki_at=4)
    summary = run_watch(proj, out=bundle, export=True, debounce=0,
                        sleep=sleep, profile=profile,
                        manage_plugins=True, stream=stream)
    assert summary["profile_reloads"] == 1
    assert summary["plugin_reloads"] == 1
    out = stream.getvalue()
    assert "plugins reloaded" in out
    assert "only load plugins you trust" in out
    sliced = _wib_bundle_text(bundle)
    assert "def alpha():" in sliced
    assert "body one" not in sliced  # the plugin now slices .wib


def test_watch_bad_plugin_keeps_last_good_reports_once(tmp_path):
    proj = _wib_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    profile = _activate_startup(proj)
    stream = io.StringIO()
    sleep = _Script(actions={
        1: lambda: _write(proj, "tools/wib.py", WIB_PLUGIN_BAD),
        # Same bad bytes saved again: same content, new mtime —
        # must stay silent (report is per distinct bad content).
        2: lambda: _write(proj, "tools/wib.py", WIB_PLUGIN_BAD),
        3: lambda: _write(proj, "a.wib", WIB_SRC + "def gamma():\nx\n"),
    }, ki_at=6)
    summary = run_watch(proj, out=bundle, export=True, debounce=0,
                        sleep=sleep, profile=profile,
                        manage_plugins=True, stream=stream)
    out = stream.getvalue()
    assert out.count("plugin reload failed") == 1
    assert summary["plugin_reloads"] == 0
    # The last-good set kept serving: exports still slice via V1.
    assert plugins_mod.active_set() is not None
    assert plugins_mod.has_slicer("wibble")
    sliced = _wib_bundle_text(bundle)
    assert "def gamma():" in sliced and "body one" not in sliced


def test_watch_plugin_recovers_when_fixed(tmp_path):
    proj = _wib_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    profile = _activate_startup(proj)
    stream = io.StringIO()
    sleep = _Script(actions={
        1: lambda: _write(proj, "tools/wib.py", WIB_PLUGIN_BAD),
        2: lambda: _write(proj, "tools/wib.py", WIB_PLUGIN_V2),
    }, ki_at=5)
    summary = run_watch(proj, out=bundle, export=True, debounce=0,
                        sleep=sleep, profile=profile,
                        manage_plugins=True, stream=stream)
    out = stream.getvalue()
    assert out.count("plugin reload failed") == 1
    assert summary["plugin_reloads"] == 1
    assert "recovered" in out
    assert "keep this line" in _wib_bundle_text(bundle)


def test_watch_plugin_unchanged_session_is_silent(tmp_path):
    proj = _wib_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    profile = _activate_startup(proj)
    stream = io.StringIO()
    sleep = _Script(actions={
        2: lambda: _write(proj, "a.wib", WIB_SRC + "def gamma():\nx\n"),
    }, ki_at=5)
    summary = run_watch(proj, out=bundle, export=True, debounce=0,
                        sleep=sleep, profile=profile,
                        manage_plugins=True, stream=stream)
    out = stream.getvalue()
    assert summary["plugin_reloads"] == 0
    assert "plugins reloaded" not in out
    assert "plugin reload failed" not in out


def test_watch_plugin_removal_clears_the_set(tmp_path):
    proj = _wib_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    profile = _activate_startup(proj)
    stream = io.StringIO()

    def drop_plugin_from_profile():
        _write(proj, ".ghostslice.json", json.dumps(
            {"modes": {"**/*.wib": "signatures"}}))

    sleep = _Script(actions={1: drop_plugin_from_profile}, ki_at=4)
    summary = run_watch(proj, out=bundle, export=True, debounce=0,
                        sleep=sleep, profile=profile,
                        manage_plugins=True, stream=stream)
    assert summary["plugin_reloads"] == 1
    assert "no plugins are active now" in stream.getvalue()
    assert not plugins_mod.has_slicer("wibble")
    # Without the plugin, .wib ships in full.
    assert "body one" in _wib_bundle_text(bundle)


def test_watch_profile_deletion_clears_plugins(tmp_path):
    proj = _wib_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    profile = _activate_startup(proj)
    stream = io.StringIO()
    sleep = _Script(actions={
        1: lambda: (proj / ".ghostslice.json").unlink(),
    }, ki_at=4)
    summary = run_watch(proj, out=bundle, export=True, debounce=0,
                        sleep=sleep, profile=profile,
                        manage_plugins=True, stream=stream)
    # Deleting the profile reverts to defaults (round 3), and the
    # defaults name no plugins, so the set clears with it.
    assert summary["profile_reloads"] == 1
    assert summary["plugin_reloads"] == 1
    assert "no plugins are active now" in stream.getvalue()
    assert not plugins_mod.has_slicer("wibble")


def test_watch_cli_manages_plugins(tmp_path, capsys):
    proj = _wib_project(tmp_path / "proj")
    code = cli_main(["watch", str(proj), "--once"])
    assert code == 0


# ---------------------------------------------------------------------------
# Audit #2 pins: adversarial formatting + the settle-window race
# ---------------------------------------------------------------------------

GO_ADVERSARIAL = '''package p

type S struct{ x int }

func (s *S) Tricky() string {
\ta := "}"
\t// } a brace in a comment
\tb := `}`
\t_ = a
\t_ = b
\treturn a
}

func After() int { return 1 }
'''

RS_ADVERSARIAL = '''pub struct S;

impl S {
    pub fn tricky(&self) -> &'static str {
        let a = "}";
        let b = '{';
        let c = '}';
        // } brace in a comment
        a
    }

    pub fn after(&self) -> i32 { 2 }
}

impl S {
    pub fn second(&self) -> i32 { 3 }
}
'''


def test_go_braces_in_strings_and_comments_do_not_move_spans():
    by_q = _by_qualified(outline_source(
        GO_ADVERSARIAL, "go", "x.go"))
    lines = GO_ADVERSARIAL.splitlines()
    assert lines[by_q["S.Tricky"].end] == "}"
    assert by_q["After"].start == 13


def test_rust_braces_in_strings_chars_and_comments_do_not_move_spans():
    syms = outline_source(RS_ADVERSARIAL, "rust", "x.rs")
    by_q = _by_qualified(syms)
    lines = RS_ADVERSARIAL.splitlines()
    assert lines[by_q["S.tricky"].end] == "    }"
    assert by_q["S.after"].parent == "S"
    assert by_q["S.second"].parent == "S"
    impls = [s for s in syms if s.kind == "impl"]
    assert len(impls) == 2 and impls[0].end < impls[1].start


class _ClockScript:
    """Scripted sleep that also advances a fake clock by 1s per
    call, so debounce windows elapse deterministically."""

    def __init__(self, actions=None, ki_at=None):
        self.actions = actions or {}
        self.calls = 0
        self.ki_at = ki_at
        self.t = 0.0

    def sleep(self, seconds):
        self.calls += 1
        self.t += 1.0
        if self.ki_at is not None and self.calls >= self.ki_at:
            raise KeyboardInterrupt
        action = self.actions.get(self.calls)
        if action is not None:
            action()

    def clock(self):
        return self.t


def test_watch_plugin_swap_during_debounce_governs_pending_export(
        tmp_path):
    proj = _wib_project(tmp_path / "proj")
    bundle = tmp_path / "bundle"
    profile = _activate_startup(proj)
    stream = io.StringIO()
    script = _ClockScript(actions={
        # Poll 1: a change lands and starts its debounce window.
        1: lambda: _write(proj, "a.wib", WIB_SRC + "def gamma():\nx\n"),
        # Poll 2 (inside the window): the plugin bytes change.
        2: lambda: _write(proj, "tools/wib.py", WIB_PLUGIN_V2),
    }, ki_at=5)
    summary = run_watch(proj, out=bundle, export=True, interval=1.0,
                        debounce=2.0, sleep=script.sleep,
                        clock=script.clock, profile=profile,
                        manage_plugins=True, stream=stream)
    # The swap landed at a poll top while the settle was pending,
    # so the pending export ran under the NEW set.
    assert summary["plugin_reloads"] == 1
    assert summary["events"] == 1
    sliced = _wib_bundle_text(bundle)
    assert "keep this line" in sliced  # V2-only behaviour
    out = stream.getvalue()
    assert out.index("plugins reloaded") < out.rindex(
        "bundle rewritten")
