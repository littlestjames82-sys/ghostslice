"""v1.0.6 (Polish Round 6) — completeness + developer experience.

Item A: Kotlin primary-constructor properties are nameable
symbols. Before this round they were invisible in outlines
(single-line heads) or leaked as parentless top-level constants
(multi-line heads, whose class span also truncated to one line);
`slice --symbols User.name` matched nothing. The contract now:
val/var constructor parameters are `attribute` symbols of their
class — for data classes and plain classes alike, because that is
Kotlin's rule — with spans inside the head, so rendering ships
them exactly once, via the head.

Item B: GET /api/calls?symbol=<id|qualified> serves one symbol's
complete call lists from the same memoised call graph the bulk
/api/graph payload is capped from.

Item C is test-infrastructure only (serve poll interval, big-tree
size) and carries no tests of its own; see
audits/POLISH_106_audit.md for the duration evidence.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from ghostslice import callgraph as callgraph_mod
from ghostslice import server as server_mod
from ghostslice.selection import symbols_for_source
from ghostslice.server import make_server
from ghostslice.slicer import slice_text
from ghostslice.symslice import outline_source, slice_with_symbols


def _write(root: Path, name: str, text: str) -> None:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Item A: Kotlin constructor properties
# ---------------------------------------------------------------------------

KT_BASIC = """\
package demo

data class User(val name: String, var age: Int) {
    fun label(): String {
        return name
    }
}

class Repo(private val db: Database, val cacheSize: Int = 10) {
    fun find(id: Int): User? {
        return null
    }
}

class Plain(val kept: Int, dropped: Int)
"""

KT_MULTI = """\
package demo

data class Order(
    val id: Long,
    val note: String = "a, b (c)",
    @Deprecated("old") val legacy: Boolean = false,
    private val secret: String
) {
    fun total(): Int {
        return 1
    }
}
"""

KT_ADV = """\
package demo

data class Cfg(
    val pattern: String =
        "default ${fmt(1, 2)}",
    val handler: (Int) -> Int = { it * 2 },
    val lookup: Map<String, List<Int>> = emptyMap(),
    val plain: Int = 3
)

enum class Color(val rgb: Int) {
    RED(0xFF0000);

    fun hex(): String {
        return "x"
    }
}

class Generic<T : Comparable<T>>(val v: T, val rest: List<T>)

class Child(val x: Int) : Parent(x), Iface {
    fun go(): Int {
        return x
    }
}
"""


def _quals(src, lang="kotlin", path="x.kt"):
    return {s.qualified: s for s in outline_source(src, lang, path)}


class TestKotlinCtorOutline:
    def test_single_line_data_class_props(self):
        q = _quals(KT_BASIC)
        for want in ("User.name", "User.age"):
            assert want in q
            assert q[want].kind == "attribute"
            assert q[want].parent == "User"

    def test_plain_class_props_and_plain_param_absent(self):
        q = _quals(KT_BASIC)
        # Non-data classes get the same treatment: val/var in the
        # primary constructor IS a property in Kotlin; a parameter
        # without val/var is not a member at all.
        assert "Repo.db" in q and "Repo.cacheSize" in q
        assert "Plain.kept" in q
        assert "Plain.dropped" not in q
        assert "dropped" not in q

    def test_multi_line_ctor_class_span_and_parents(self):
        q = _quals(KT_MULTI)
        order = q["Order"]
        assert order.start == 2 and order.end == 11  # whole class
        assert order.head_end == 7                   # the `) {` line
        for want in ("Order.id", "Order.note", "Order.legacy",
                     "Order.secret"):
            assert want in q, want
            assert q[want].parent == "Order"
            assert q[want].kind == "attribute"
        assert q["Order.total"].parent == "Order"
        # Nothing leaks to the top level any more.
        for leaked in ("id", "note", "legacy", "secret", "total"):
            assert leaked not in q

    def test_awkward_forms(self):
        q = _quals(KT_ADV)
        # Default that wraps, with a template holding parens/commas.
        assert q["Cfg.pattern"].start == 3
        assert q["Cfg.pattern"].end == 4
        # Lambda default and a generic type with a comma inside <>.
        assert "Cfg.handler" in q
        assert "Cfg.lookup" in q
        assert "Cfg.plain" in q
        # Enum class property + bounded generics on the class.
        assert q["Color.rgb"].parent == "Color"
        assert "Generic.v" in q and "Generic.rest" in q
        # Supertypes after the constructor.
        assert "Child.x" in q
        assert q["Child.go"].parent == "Child"


KT_BODYLESS = """\
package demo

data class Marker

interface Callback

class WithInit(val x: Int) {
    fun get(): Int {
        return x
    }
}
"""


class TestKotlinBodylessHeads:
    """Audit #2 find (F-A2): a body-less Kotlin head stole the
    NEXT declaration's brace under the 3-line window search, so
    `data class Marker` swallowed the following class whole.
    Pre-existing at v1.0.5; the declaration-stop guard fixes it."""

    def test_bodyless_class_does_not_swallow_next(self):
        q = _quals(KT_BODYLESS)
        assert q["Marker"].start == q["Marker"].end == 2
        assert q["Callback"].start == q["Callback"].end == 4
        assert "Marker.WithInit" not in q
        assert q["WithInit"].parent is None
        assert q["WithInit.get"].parent == "WithInit"
        assert "WithInit.x" in q

    def test_bodyless_declarations_render_in_signatures(self):
        text = slice_text("x.kt", KT_BODYLESS, "signatures").text
        assert "data class Marker" in text
        assert "interface Callback" in text
        assert "class WithInit(val x: Int) {" in text


class TestKotlinCtorSelection:
    def test_props_resolve_and_render_once(self):
        out = slice_with_symbols("x.kt", KT_MULTI, {"Order.note"})
        assert out.count('val note: String = "a, b (c)"') == 1
        out = slice_with_symbols("x.kt", KT_BASIC, {"User.name"})
        assert out.count("val name: String") == 1

    def test_selecting_a_method_ships_head_once(self):
        out = slice_with_symbols("x.kt", KT_MULTI, {"Order.total"})
        assert "return 1" in out                    # kept body
        for line in ('val id: Long,', 'val note: String = "a, b (c)",',
                     "private val secret: String"):
            assert out.count(line) == 1, line       # head ships once

    def test_selection_names_include_annotated_prop(self):
        names = symbols_for_source("kotlin", KT_MULTI, "x.kt")
        # Before the fix the @Deprecated property was invisible to
        # every surface, task selection included.
        assert "legacy" in names
        assert "note" in names and "secret" in names


class TestKotlinCtorSignatures:
    def test_multi_line_head_renders_whole(self):
        text = slice_text("x.kt", KT_MULTI, "signatures").text
        assert "data class Order(" in text
        assert 'val note: String = "a, b (c)",' in text
        assert "private val secret: String" in text
        assert ") {" in text
        assert "fun total(): Int { /* ... */ }" in text
        # The parameter lines are NOT floating orphans: they sit
        # between the declaration line and the closing brace line.
        i_decl = text.index("data class Order(")
        i_note = text.index("val note")
        i_close = text.index(") {")
        assert i_decl < i_note < i_close

    def test_bodyless_multi_line_ctor_renders_head(self):
        src = ("data class Pair2(\n    val a: Int,\n"
               "    val b: String\n)\n")
        text = slice_text("x.kt", src, "signatures").text
        assert "data class Pair2(" in text
        assert "val a: Int," in text
        assert text.rstrip().endswith(")")

    def test_interfaces_mode_keeps_ctor_class(self):
        text = slice_text("x.kt", KT_MULTI, "interfaces").text
        assert "data class Order(" in text
        assert "fun total(): Int { /* ... */ }" in text


# ---------------------------------------------------------------------------
# Item B: /api/calls per-symbol endpoint
# ---------------------------------------------------------------------------

@pytest.fixture()
def dash(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _write(root, "main.py",
           "from util import helper\n\n\n"
           "def main():\n    return helper()\n")
    _write(root, "util.py",
           "def helper():\n    return leaf()\n\n\n"
           "def leaf():\n    return 1\n\n\n"
           "def orphan():\n    return 2\n")
    _write(root, "other.py", "def helper():\n    return 99\n")
    _write(root, "evil<script>.py", "def sneaky():\n    return 0\n")
    server, state = make_server(str(root), port=0)
    port = server.server_address[1]
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.02),
        daemon=True)
    thread.start()
    yield root, state, port
    server.shutdown()
    server.server_close()


def _get(port, path):
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}", timeout=30) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def _get_json(port, path):
    status, body = _get(port, path)
    return status, json.loads(body)


def _calls_url(query):
    return "/api/calls?symbol=" + urllib.parse.quote(query)


class TestSymbolCallsEndpoint:
    def test_by_id_returns_chain_lists(self, dash):
        _root, _state, port = dash
        status, d = _get_json(port, _calls_url("util.py:helper"))
        assert status == 200
        assert d["symbol"]["qualified"] == "helper"
        assert [r["id"] for r in d["callers"]] == ["main.py:main"]
        assert [r["id"] for r in d["callees"]] == ["util.py:leaf"]
        assert d["callers_total"] == 1 and d["callees_total"] == 1
        assert d["callers_truncated"] is False
        assert d["list_cap"] == server_mod.CALL_LIST_CAP
        assert d["dead"] is False

    def test_unique_qualified_name_resolves(self, dash):
        _root, _state, port = dash
        status, d = _get_json(port, _calls_url("leaf"))
        assert status == 200
        assert d["symbol"]["id"] == "util.py:leaf"
        assert [r["id"] for r in d["callers"]] == ["util.py:helper"]

    def test_ambiguous_qualified_name_lists_matches(self, dash):
        _root, _state, port = dash
        status, d = _get_json(port, _calls_url("helper"))
        assert status == 200
        assert d["ambiguous"] is True
        assert {m["id"] for m in d["matches"]} == {
            "util.py:helper", "other.py:helper"}
        # ...and an id picks one, unambiguously.
        status, d = _get_json(port, _calls_url("other.py:helper"))
        assert status == 200 and "ambiguous" not in d
        assert d["symbol"]["path"] == "other.py"

    def test_unknown_symbol_and_missing_param(self, dash):
        _root, _state, port = dash
        status, d = _get_json(port, _calls_url("nope"))
        assert status == 404 and "no such symbol" in d["error"]
        status, d = _get_json(port, "/api/calls")
        assert status == 400 and "missing symbol" in d["error"]

    def test_zero_call_symbol(self, dash):
        _root, _state, port = dash
        status, d = _get_json(port, _calls_url("util.py:orphan"))
        assert status == 200
        assert d["callers"] == [] and d["callees"] == []
        assert d["referenced_by"] == []
        assert d["dead"] is True  # no callers, no references

    def test_html_shaped_names_are_inert_json(self, dash):
        _root, _state, port = dash
        status, d = _get_json(port, _calls_url("evil<script>.py:sneaky"))
        assert status == 200
        assert d["symbol"]["path"] == "evil<script>.py"
        status, d = _get_json(port, _calls_url("x<script>:y"))
        assert status == 404 and "<script>" in d["error"]

    def test_page_wires_fetch_and_stays_textcontent_only(self, dash):
        _root, _state, port = dash
        status, body = _get(port, "/")
        assert status == 200
        assert ".innerHTML" not in body
        assert "fetchSymbolCalls" in body
        assert "/api/calls?symbol=" in body
        assert "complete lists" in body

    def test_bulk_truncated_symbol_reachable_in_full(
            self, tmp_path, monkeypatch):
        # The point of the endpoint: with the bulk cap forced to 1,
        # the z.py:zz -> z.py:target edge (last in sorted order)
        # is past the cut — /api/calls still serves target's
        # complete lists from the same build.
        root = tmp_path / "proj"
        root.mkdir()
        _write(root, "z.py",
               "def a():\n    return b()\n\n\n"
               "def b():\n    return 1\n\n\n"
               "def zz():\n    return target()\n\n\n"
               "def target():\n    return 2\n")
        monkeypatch.setattr(server_mod, "CALL_EDGE_CAP", 1)
        server, state = make_server(str(root), port=0)
        port = server.server_address[1]
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.02),
            daemon=True)
        thread.start()
        try:
            _status, data = _get_json(port, "/api/graph")
            calls = data["calls"]
            assert calls["edges_truncated"] is True
            assert calls["edges_total"] > 1
            bulk_pairs = {(e["caller"], e["callee"])
                          for e in calls["edges"]}
            assert ("z.py:zz", "z.py:target") not in bulk_pairs
            status, d = _get_json(port, _calls_url("z.py:target"))
            assert status == 200
            assert [r["id"] for r in d["callers"]] == ["z.py:zz"]
        finally:
            server.shutdown()
            server.server_close()

    def test_per_list_cap_reports_totals(self, tmp_path, monkeypatch):
        root = tmp_path / "hub"
        root.mkdir()
        callers = "\n".join(
            f"def c{i}():\n    return center()\n" for i in range(5))
        _write(root, "hub.py", "def center():\n    return 1\n\n" + callers)
        monkeypatch.setattr(server_mod, "CALL_LIST_CAP", 2)
        server, state = make_server(str(root), port=0)
        port = server.server_address[1]
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.02),
            daemon=True)
        thread.start()
        try:
            status, d = _get_json(port, _calls_url("hub.py:center"))
            assert status == 200
            assert d["callers_total"] == 5
            assert len(d["callers"]) == 2
            assert d["callers_truncated"] is True
            assert d["list_cap"] == 2
        finally:
            server.shutdown()
            server.server_close()

    def test_endpoint_waits_for_in_flight_build(
            self, tmp_path, monkeypatch):
        # Warm-up interplay: a request during the build waits on
        # the same lock as /api/graph and receives the final lists.
        root = tmp_path / "proj"
        root.mkdir()
        _write(root, "a.py", "def a():\n    return b()\n\n"
               "def b():\n    return 1\n")
        real_build = callgraph_mod.build_call_graph
        started = threading.Event()
        gate = threading.Event()

        def slow_build(*args, **kwargs):
            started.set()
            gate.wait(30)
            return real_build(*args, **kwargs)

        monkeypatch.setattr(callgraph_mod, "build_call_graph", slow_build)
        server, state = make_server(str(root), port=0)
        port = server.server_address[1]
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.02),
            daemon=True)
        thread.start()
        try:
            state.start_calls_warmup()
            assert started.wait(30)
            results = []
            rt = threading.Thread(
                target=lambda: results.append(
                    _get_json(port, _calls_url("a.py:a"))))
            rt.start()
            import time
            time.sleep(0.3)
            assert results == []  # still waiting on the build
            gate.set()
            rt.join(30)
            assert len(results) == 1
            status, d = results[0]
            assert status == 200
            assert [r["id"] for r in d["callees"]] == ["a.py:b"]
        finally:
            gate.set()
            server.shutdown()
            server.server_close()

    def test_build_failure_surfaces_like_graph(self, tmp_path,
                                               monkeypatch):
        root = tmp_path / "proj"
        root.mkdir()
        _write(root, "a.py", "def a():\n    return 1\n")

        def boom(*args, **kwargs):
            raise RuntimeError("boom-build")

        monkeypatch.setattr(callgraph_mod, "build_call_graph", boom)
        server, state = make_server(str(root), port=0)
        port = server.server_address[1]
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.02),
            daemon=True)
        thread.start()
        try:
            with pytest.raises(RuntimeError, match="boom-build"):
                state.symbol_calls("a.py:a")
            # Other endpoints keep serving.
            status, _body = _get(port, "/api/scan")
            assert status == 200
        finally:
            server.shutdown()
            server.server_close()
