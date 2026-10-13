"""v0.19 (G14): Python call graph + dead-function candidates.

The fixture package exercises every resolution class (exact via
import alias / module alias / self / class, heuristic by name,
attribute by name) and every exemption class (framework decorator,
external-base protocol class, __all__, [project.scripts], entry
file, conftest, dunder, property attribute access, callback by
reference, direct self-recursion). The one deliberate miss —
getattr string dispatch — must be flagged, with the honesty line
attached: the caveat is pinned, not the miss forgiven.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.callgraph import build_call_graph, dead_symbol_recommendations
from ghostslice.cli import main as cli_main
from ghostslice.graph import build_graph, recommendations
from ghostslice.profile import load_profile
from ghostslice.scanner import scan

UTIL = '''
def util_fn(x):
    return x + 1


def dead_util_fn(x):
    return x * 99


def callback_fn():
    return "cb"


HANDLERS = {"cb": callback_fn}

CALLBACKS = [callback_fn]


def register(fn):
    return fn


via_register = register(callback_fn)

doubler = lambda n: n * 2

orphan_lambda = lambda n: n - 1


def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)


def ping(n):
    return pong(n - 1) if n else 0


def pong(n):
    return ping(n - 1) if n else 0
'''

CORE = '''
class Engine:
    def __init__(self):
        self._setup()

    def _setup(self):
        self.ready = True

    @property
    def label(self):
        return "engine"

    def start(self):
        return self.helper()

    def helper(self):
        return 42

    def __str__(self):
        return "Engine"

    @classmethod
    def build(cls):
        return cls()

    @staticmethod
    def version():
        return "1.0"

    def dead_method(self):
        return -1


def make_engine():
    e = Engine.build()
    return e.start()


def read_label(e):
    return (e.label, Engine.version())
'''

APP = '''
from http.server import BaseHTTPRequestHandler

from fakeframework import App
from pkg.core import Engine, make_engine, read_label
from pkg.util import doubler, util_fn as uf
import pkg.util as u

app = App()


@app.route("/home")
def home_handler():
    return "home"


def script_entry():
    eng = make_engine()
    run_dispatch(eng)
    calls_unimported()
    use_module_alias()
    compute()
    read_label(eng)
    return uf(eng)


def calls_unimported():
    return util_fn(1)


def use_module_alias():
    return u.util_fn(5)


def compute():
    return doubler(21)


def dispatched():
    return "via getattr"


def run_dispatch(mod):
    return getattr(mod, "dispatched")()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        return None


HANDLER_CLS = Handler
'''

MAIN = '''
from pkg.app import script_entry


def bootstrap():
    return script_entry()


if __name__ == "__main__":
    bootstrap()
'''

CONFTEST = '''
def a_fixture_helper():
    return 1
'''

TEST_APP = '''
from pkg.util import util_fn


def test_util():
    assert util_fn(1) == 2


def test_other():
    pass
'''

PYPROJECT = '''
[project]
name = "fixture"
version = "0.1.0"

[project.scripts]
mycmd = "pkg.app:script_entry"
'''


def make_project(root: Path) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "util.py").write_text(UTIL)
    (root / "pkg" / "core.py").write_text(CORE)
    (root / "pkg" / "app.py").write_text(APP)
    (root / "main.py").write_text(MAIN)
    (root / "conftest.py").write_text(CONFTEST)
    (root / "tests" / "test_app.py").write_text(TEST_APP)
    return root


def dead_set(payload) -> set:
    return {(d["path"], d["qualified"]) for d in payload["dead"]}


def edge_set(payload) -> set:
    return {(e["caller"], e["callee"], e["kind"]) for e in payload["edges"]}


class TestCallGraph(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_project(Path(self.tmp.name))
        self.result = scan(self.root)
        self.profile = load_profile(self.root)
        self.payload = build_call_graph(self.result, self.profile,
                                        build_graph(self.result))

    def tearDown(self):
        self.tmp.cleanup()

    def test_json_shape(self):
        p = self.payload
        for key in ("root", "symbols", "edges", "dead", "counts",
                    "skipped_files", "token_method", "note"):
            self.assertIn(key, p)
        for key in ("calls", "exact", "heuristic", "attribute",
                    "references", "unresolved", "external",
                    "symbols", "files"):
            self.assertIn(key, p["counts"])
        sym = next(s for s in p["symbols"] if s["qualified"] == "util_fn")
        for key in ("id", "path", "name", "qualified", "kind",
                    "start_line", "end_line", "tokens", "fan_in",
                    "references"):
            self.assertIn(key, sym)
        self.assertIn("getattr", p["note"])

    def test_import_alias_resolves_exact(self):
        # `from pkg.util import util_fn as uf`, called as uf(...)
        self.assertIn(("pkg/app.py:script_entry", "pkg/util.py:util_fn",
                       "exact"), edge_set(self.payload))

    def test_module_alias_resolves_exact(self):
        # `import pkg.util as u`, called as u.util_fn(...)
        self.assertIn(("pkg/app.py:use_module_alias", "pkg/util.py:util_fn",
                       "exact"), edge_set(self.payload))

    def test_bare_unimported_name_is_heuristic(self):
        # app.py binds only `uf`; a bare util_fn(...) call has no
        # import evidence, so the edge must be labelled heuristic.
        self.assertIn(("pkg/app.py:calls_unimported", "pkg/util.py:util_fn",
                       "heuristic"), edge_set(self.payload))

    def test_self_method_edge_exact(self):
        self.assertIn(("pkg/core.py:Engine.start",
                       "pkg/core.py:Engine.helper", "exact"),
                      edge_set(self.payload))

    def test_classmethod_called_on_class_exact(self):
        self.assertIn(("pkg/core.py:make_engine", "pkg/core.py:Engine.build",
                       "exact"), edge_set(self.payload))
        self.assertIn(("pkg/core.py:read_label", "pkg/core.py:Engine.version",
                       "exact"), edge_set(self.payload))

    def test_instantiation_reaches_init_chain(self):
        # Engine.build() -> cls() -> Engine.__init__ -> self._setup():
        # without the instantiation->__init__ edge the whole subtree
        # would look dead (audit G14 F1).
        dead = dead_set(self.payload)
        self.assertNotIn(("pkg/core.py", "Engine._setup"), dead)
        self.assertNotIn(("pkg/core.py", "Engine.__init__"), dead)
        self.assertIn(("pkg/core.py:Engine.build", "pkg/core.py:Engine",
                       "exact"), edge_set(self.payload))

    def test_dead_set_is_exactly_the_genuinely_dead(self):
        self.assertEqual(dead_set(self.payload), {
            ("pkg/util.py", "dead_util_fn"),
            ("pkg/util.py", "orphan_lambda"),
            ("pkg/util.py", "ping"),
            ("pkg/util.py", "pong"),
            ("pkg/core.py", "Engine.dead_method"),
            ("pkg/app.py", "dispatched"),
        })

    def test_dead_candidate_fields(self):
        d = next(d for d in self.payload["dead"]
                 if d["qualified"] == "dead_util_fn")
        self.assertEqual(d["path"], "pkg/util.py")
        self.assertGreater(d["tokens"], 0)
        self.assertGreater(d["end_line"], d["start_line"])
        lam = next(d for d in self.payload["dead"]
                   if d["qualified"] == "orphan_lambda")
        self.assertEqual(lam["kind"], "function")  # lambda, not "constant"

    def test_callback_by_reference_not_flagged(self):
        dead = dead_set(self.payload)
        self.assertNotIn(("pkg/util.py", "callback_fn"), dead)
        refs = {(e["caller"], e["callee"]) for e in self.payload["edges"]
                if e["kind"] == "reference"}
        self.assertIn(("pkg/util.py:<module>", "pkg/util.py:callback_fn"),
                      refs)

    def test_framework_decorator_not_flagged(self):
        self.assertNotIn(("pkg/app.py", "home_handler"),
                         dead_set(self.payload))

    def test_external_base_protocol_methods_not_flagged(self):
        self.assertNotIn(("pkg/app.py", "Handler.do_GET"),
                         dead_set(self.payload))

    def test_project_scripts_target_not_flagged(self):
        self.assertNotIn(("pkg/app.py", "script_entry"),
                         dead_set(self.payload))

    def test_dunder_never_flagged(self):
        self.assertNotIn(("pkg/core.py", "Engine.__str__"),
                         dead_set(self.payload))

    def test_property_attribute_access_not_flagged(self):
        # read_label does e.label (a load, never a call).
        self.assertNotIn(("pkg/core.py", "Engine.label"),
                         dead_set(self.payload))

    def test_getattr_dispatch_flagged_with_caveat(self):
        self.assertIn(("pkg/app.py", "dispatched"), dead_set(self.payload))
        self.assertIn("recommendations to review", self.payload["note"])

    def test_test_functions_not_flagged(self):
        dead = dead_set(self.payload)
        self.assertNotIn(("tests/test_app.py", "test_util"), dead)
        self.assertNotIn(("tests/test_app.py", "test_other"), dead)
        self.assertNotIn(("conftest.py", "a_fixture_helper"), dead)

    def test_self_recursion_is_alive_but_cluster_is_not(self):
        dead = dead_set(self.payload)
        self.assertNotIn(("pkg/util.py", "fib"), dead)
        # Mutual recursion with no root caller is still dead code:
        # reachability decides, only the direct self-edge is a pass.
        self.assertIn(("pkg/util.py", "ping"), dead)
        self.assertIn(("pkg/util.py", "pong"), dead)

    def test_entry_file_functions_rooted(self):
        self.assertNotIn(("main.py", "bootstrap"), dead_set(self.payload))

    def test_called_lambda_not_flagged(self):
        self.assertNotIn(("pkg/util.py", "doubler"), dead_set(self.payload))

    def test_fan_in_ranking(self):
        by_q = {}
        for s in self.payload["symbols"]:
            by_q.setdefault((s["path"], s["qualified"]), s)
        util = by_q[("pkg/util.py", "util_fn")]
        helper = by_q[("pkg/core.py", "Engine.helper")]
        dead = by_q[("pkg/util.py", "dead_util_fn")]
        # script_entry (alias) + use_module_alias + calls_unimported
        # (heuristic) + the test: 4 incoming call edges.
        self.assertEqual(util["fan_in"], 4)
        self.assertEqual(helper["fan_in"], 1)
        self.assertEqual(dead["fan_in"], 0)
        ranked = sorted((s for s in self.payload["symbols"] if s["fan_in"]),
                          key=lambda s: -s["fan_in"])
        self.assertEqual(ranked[0]["qualified"], "util_fn")


class TestRecommendations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_project(Path(self.tmp.name))
        self.result = scan(self.root)
        self.profile = load_profile(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dead_symbol_recommendations_shape(self):
        recs = dead_symbol_recommendations(self.result, self.profile)
        self.assertTrue(recs)
        for r in recs:
            self.assertEqual(r["kind"], "dead-symbol")
            self.assertIn("symbol", r)
            self.assertIn("lines", r)
            self.assertEqual(r["tokens"], r["potential_savings"])
            self.assertIn("recommendations to review", r["detail"])
        syms = {(r["path"], r["symbol"]) for r in recs}
        self.assertIn(("pkg/app.py", "dispatched"), syms)

    def test_graph_recommendations_unchanged(self):
        # The shared function (and lint, which consumes it) gains
        # nothing: dead symbols merge only at the CLI surface.
        recs = recommendations(self.result, build_graph(self.result),
                                 self.profile)
        self.assertTrue(all(r.get("kind") != "dead-symbol" for r in recs))


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_project(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli_main(argv)
        return code, buf.getvalue()

    def test_calls_dead_text(self):
        code, out = self.run_cli(["calls", str(self.root), "--dead"])
        self.assertEqual(code, 0)
        self.assertIn("Dead-function candidates (6)", out)
        self.assertIn("dispatched", out)
        self.assertIn("recommendations to review, not instructions", out)

    def test_calls_json(self):
        code, out = self.run_cli(["calls", str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIn("dead", payload)
        self.assertIn("edges", payload)

    def test_calls_single_file(self):
        code, out = self.run_cli(["calls", str(self.root), "pkg/core.py"])
        self.assertEqual(code, 0)
        self.assertIn("Engine.helper", out)
        self.assertIn("called by", out)

    def test_graph_cli_includes_dead_symbols(self):
        code, out = self.run_cli(["graph", str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        kinds = {r.get("kind") for r in payload["recommendations"]}
        self.assertIn("dead-symbol", kinds)


PROBE_BASE = '''
class Base:
    def start(self):
        return "base"

    def inherited_only(self):
        return "inherited"


class Sub(Base):
    def start(self):
        return super().start()

    def run(self):
        return self.inherited_only()


class Template:
    def __init__(self):
        self.hook()

    def hook(self):
        return None


class Impl(Template):
    def hook(self):
        return "impl"


class Widget:
    @property
    def title(self):
        return self._t

    @title.setter
    def title(self, v):
        self._t = v


def sub_flow():
    s = Sub()
    return s.start(), s.run()


def widget_flow():
    w = Widget()
    w.title = "x"
    return w.title


def impl_flow():
    return Impl()


async def fetch():
    return 1


async def amain():
    return await fetch()
'''

PROBE_SIGNALS = '''
import functools


class Bus:
    def connect(self, fn):
        return fn

    def on_ready(self):
        return "ready"


def emit(bus):
    bus.connect(Bus().on_ready)
    return functools.partial(Bus().on_ready)


def local_decorator(fn):
    return fn


@local_decorator
def decorated_but_unused():
    return 1


def get_bus():
    return Bus()


def chained():
    return get_bus().connect(None)
'''

PROBE_MAIN = '''
import asyncio

from base import amain, impl_flow, sub_flow, widget_flow
from signals import chained, emit, get_bus


def main():
    sub_flow()
    widget_flow()
    impl_flow()
    chained()
    asyncio.run(amain())
    return emit(get_bus())


if __name__ == "__main__":
    main()
'''


class TestDispatchPatterns(unittest.TestCase):
    """The Audit #2 battery, pinned: super() chains, the
    template-method override (F6), property pairs, signal/partial
    references, local decorators, async and chained calls."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "base.py").write_text(PROBE_BASE)
        (root / "signals.py").write_text(PROBE_SIGNALS)
        (root / "main.py").write_text(PROBE_MAIN)
        self.result = scan(root)
        self.payload = build_call_graph(self.result, load_profile(root),
                                        build_graph(self.result))

    def tearDown(self):
        self.tmp.cleanup()

    def test_super_edge_exact(self):
        self.assertIn(("base.py:Sub.start", "base.py:Base.start", "exact"),
                      edge_set(self.payload))

    def test_template_method_override_not_flagged(self):
        # Template.__init__ calls self.hook(); Impl.hook is a
        # polymorphic dispatch target, not dead (audit G14 F6).
        dead = dead_set(self.payload)
        self.assertNotIn(("base.py", "Template.hook"), dead)
        self.assertNotIn(("base.py", "Impl.hook"), dead)
        self.assertIn(("base.py:Template.__init__", "base.py:Impl.hook",
                       "attribute"), edge_set(self.payload))

    def test_inherited_method_via_subclass_self(self):
        self.assertNotIn(("base.py", "Base.inherited_only"),
                         dead_set(self.payload))

    def test_property_pair_not_flagged(self):
        self.assertNotIn(("base.py", "Widget.title"),
                         dead_set(self.payload))

    def test_reference_handoff_not_flagged(self):
        dead = dead_set(self.payload)
        self.assertNotIn(("signals.py", "Bus.on_ready"), dead)
        self.assertNotIn(("signals.py", "Bus.connect"), dead)

    def test_local_decorator_does_not_root(self):
        dead = dead_set(self.payload)
        self.assertIn(("signals.py", "decorated_but_unused"), dead)
        self.assertNotIn(("signals.py", "local_decorator"), dead)

    def test_async_chain_not_flagged(self):
        dead = dead_set(self.payload)
        self.assertNotIn(("base.py", "fetch"), dead)
        self.assertNotIn(("base.py", "amain"), dead)


class TestUnparseable(unittest.TestCase):
    def test_broken_file_skipped_not_judged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "bad.py").write_text("def nope(:\n    pass\n")
            (root / "good.py").write_text(
                "def unused_fn():\n    return 1\n")
            result = scan(root)
            payload = build_call_graph(result, load_profile(root))
            self.assertIn("bad.py", payload["skipped_files"])
            self.assertIn(("good.py", "unused_fn"), dead_set(payload))


if __name__ == "__main__":
    unittest.main()
