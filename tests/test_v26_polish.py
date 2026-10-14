"""v1.0.1 polish round: plugin-contract call-graph roots, __all__
class surfaces, the single price table, and the dashboard's
textContent-only rendering.

The call-graph fixtures pin both directions of the new root rules:
a plugin module's contract functions (and everything they reach)
are alive because the LOADER calls them, while a genuinely dead
function in the same plugin file still flags — presenting the
contract does not bless dead code. Likewise a class named in
__all__ exposes its methods as public API, while a non-exported
class's unused method still flags.
"""
import sys
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice import textio
from ghostslice.callgraph import build_call_graph
from ghostslice.graph import build_graph
from ghostslice.pricing import load_prices
from ghostslice.profile import load_profile
from ghostslice.scanner import scan
from ghostslice.server import make_server

REPO = Path(__file__).resolve().parents[1]


def _write_project(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def _dead_qualified(root: Path) -> set:
    result = scan(root)
    payload = build_call_graph(result, load_profile(root),
                               build_graph(result))
    return {d["qualified"] for d in payload["dead"]}


PLUGIN_ATTR = '''
LANGUAGE = "lua"
EXTENSIONS = [".lua"]


def _helper(text):
    return text.upper()


def slice_text(path, text, mode):
    return _helper(text)


def outline(path, text):
    return []


def dead_helper(x):
    return x * 3
'''

PLUGIN_REGISTER = '''
def _slicer(path, text, mode):
    return text


def register(api):
    api.register_slicer("lua", [".lua"], _slicer)


def dead_fn():
    return 1
'''

PARTIAL_CONTRACT = '''
LANGUAGE = "lua"


def slice_text(path, text, mode):
    return text
'''

EXPORTED_API = '''
__all__ = ["Api"]


class Api:
    def serve(self):
        return 1

    def helper(self):
        return 2


class Internal:
    def unused_method(self):
        return 3


def dead_fn():
    return 4
'''


# ---------------------------------------------------------------------------
# Call-graph roots: plugin contract + __all__ surfaces
# ---------------------------------------------------------------------------

def test_plugin_attribute_style_roots_contract_only(tmp_path):
    root = _write_project(tmp_path, {"tools/lua_slicer.py": PLUGIN_ATTR})
    # slice_text/outline are roots (the loader calls them) and
    # _helper is reachable through slice_text; dead_helper is not
    # touched by any contract function and still flags.
    assert _dead_qualified(root) == {"dead_helper"}


def test_plugin_register_style_roots_register_and_its_slicer(tmp_path):
    root = _write_project(tmp_path, {"tools/reg_slicer.py": PLUGIN_REGISTER})
    # register is a root; _slicer is referenced by it as the
    # register_slicer argument. dead_fn still flags.
    assert _dead_qualified(root) == {"dead_fn"}


def test_partial_contract_is_not_a_plugin_module(tmp_path):
    root = _write_project(tmp_path, {"tools/almost.py": PARTIAL_CONTRACT})
    # LANGUAGE alone (no EXTENSIONS, no register) is not the
    # contract the loader accepts, so nothing is rooted and the
    # unreferenced slice_text flags like any dead function.
    assert _dead_qualified(root) == {"slice_text"}


def test_exported_class_methods_are_public_api(tmp_path):
    root = _write_project(tmp_path, {"api.py": EXPORTED_API})
    dead = _dead_qualified(root)
    assert "Api.serve" not in dead and "Api.helper" not in dead
    assert "Internal.unused_method" in dead
    assert "dead_fn" in dead


def test_repo_has_no_dead_candidates():
    # Dogfood pin for this round's headline: the Lua example's
    # functions, the PluginAPI surface, and textio's public read
    # helper were the 10 false positives; all are rooted now.
    assert _dead_qualified(REPO) == set()


# ---------------------------------------------------------------------------
# textio public API
# ---------------------------------------------------------------------------

def test_read_text_with_encoding_labels(tmp_path):
    wide = tmp_path / "wide.py"
    wide.write_bytes("x = 1\n".encode("utf-16"))
    text, label = textio.read_text_with_encoding(wide)
    assert text == "x = 1\n" and label.startswith("utf-16")

    latin = tmp_path / "latin.py"
    latin.write_bytes(b"# caf\xe9\n")
    text, label = textio.read_text_with_encoding(latin)
    assert text == "# café\n" and label == "latin-1"

    plain = tmp_path / "plain.py"
    plain.write_bytes(b"y = 2\n")
    text, label = textio.read_text_with_encoding(plain)
    assert text == "y = 2\n" and label == "utf-8"


# ---------------------------------------------------------------------------
# The single price table (L004 dedupe)
# ---------------------------------------------------------------------------

def test_single_price_table(monkeypatch, tmp_path):
    # The pre-1.0.1 repo-root duplicate is gone; the packaged copy
    # is the one source of truth and the loader finds it from any
    # working directory without a prices.json of its own.
    assert not (REPO / "prices.json").exists()
    monkeypatch.chdir(tmp_path)
    prices = load_prices()
    assert prices["as_of"] == "2026-10-12"
    assert Path(prices["_path"]) == \
        REPO / "src" / "ghostslice" / "prices.json"
    # Pretty-printed for hand-editing: no giant lines (the L006
    # shape the compact one-liner had by construction).
    lines = (REPO / "src" / "ghostslice" / "prices.json") \
        .read_text(encoding="utf-8").splitlines()
    assert len(lines) > 10
    assert max(len(line) for line in lines) < 400


# ---------------------------------------------------------------------------
# Dashboard: paths render via textContent, never innerHTML
# ---------------------------------------------------------------------------

def test_dashboard_page_has_no_innerhtml_interpolation(tmp_path):
    _write_project(tmp_path, {"app.py": "x = 1\n"})
    server, _state = make_server(str(tmp_path), port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/", timeout=10) as resp:
            body = resp.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
    # Untrusted strings (file paths, recommendation paths/reasons,
    # file content) are assigned via textContent only; no innerHTML
    # property is touched anywhere in the page any more.
    assert ".innerHTML" not in body
    assert "pathSpan.textContent = f.path" in body
    assert "p.textContent = r.path" in body
    assert "${f.path}" not in body and "${r.path}" not in body


# Audit #2 precision pins: the root rules must not over-reach.
# (These began as scratch probes in audits/POLISH_101_audit.md.)

PLUGIN_WITH_CLASS_METHOD = '''
LANGUAGE = "x"
EXTENSIONS = [".x"]


def slice_text(path, text, mode):
    return text


class Helper:
    def slice_text(self):
        return 1
'''

ASSIGNED_REGISTER = '''
def _reg(api):
    return None


register = _reg


def dead_fn():
    return 1
'''


def test_contract_names_on_methods_are_not_roots(tmp_path):
    # Only top-level defs present the contract. A method that
    # happens to be named slice_text is not a loader entry point
    # and still flags (its class flags with it, both unreachable).
    root = _write_project(tmp_path,
                          {"plug.py": PLUGIN_WITH_CLASS_METHOD})
    dead = _dead_qualified(root)
    assert "Helper.slice_text" in dead and "Helper" in dead
    assert "slice_text" not in dead


def test_plugin_roots_are_scoped_per_file(tmp_path):
    # A plugin module's contract does not root the same names in
    # an unrelated module.
    root = _write_project(tmp_path, {
        "plug.py": PLUGIN_WITH_CLASS_METHOD,
        "plain.py": "def outline():\n    return 1\n",
    })
    assert "outline" in _dead_qualified(root)


def test_assigned_register_keeps_its_target_alive(tmp_path):
    # The loader accepts an assigned register (callable attribute);
    # the assignment itself references _reg, so _reg is reachable
    # through the module root even though nothing is "rooted".
    root = _write_project(tmp_path, {"plug.py": ASSIGNED_REGISTER})
    assert _dead_qualified(root) == {"dead_fn"}
