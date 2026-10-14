"""v0.23 (G18): plugin system for user slicers.

Both contract styles (register(api) and module attributes), the
opt-in loading points (profile "plugins" with project containment,
CLI --plugin), the override rule for built-in languages, the
failure discipline (load failure = exit 2 before writes; per-file
failure = full text + manifest plugin_errors), cache invalidation
on plugin byte changes, and the shipped Lua example running the
full pipeline.

The activation registry is process-global, so an autouse fixture
resets it around every test.
"""
import json
import shutil
from pathlib import Path

import pytest

from ghostslice import plugins
from ghostslice.cli import main as cli_main
from ghostslice.exporter import build_bundle
from ghostslice.mcp_server import handle_message
from ghostslice.scanner import scan
from ghostslice.slicer import slice_text

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "plugins"


@pytest.fixture(autouse=True)
def _reset_plugins():
    plugins.reset()
    yield
    plugins.reset()


# -- plugin sources ------------------------------------------------

ATTR_PLUGIN = '''
NAME = "Wibble (test plugin)"
LANGUAGE = "wibble"
EXTENSIONS = [".wib"]


def slice_text(path, text, mode):
    if mode == "signatures":
        keep = [l for l in text.split("\\n")
                if l.startswith("def ") or l == ""]
        return "\\n".join(keep) + "\\n"
    if mode == "interfaces":
        keep = [l for l in text.split("\\n") if l.startswith("def ")]
        return "\\n".join(keep) + "\\n"
    return text


def outline(path, text):
    rows = []
    for i, line in enumerate(text.split("\\n")):
        if line.startswith("def "):
            name = line[4:].split("(")[0].strip()
            rows.append({"name": name, "kind": "function",
                         "start": i, "end": i})
    return rows
'''

REGISTER_PLUGIN = '''
NAME = "Reggie (test plugin)"


def register(api):
    assert api.estimate_tokens("some words here") > 0
    assert "signatures" in api.MODES

    def sl(path, text, mode):
        if mode == "signatures":
            return "REG-SLICED\\n"
        return text

    api.register_slicer("reglang", [".reg"], sl)
'''

BOOM_PLUGIN = '''
LANGUAGE = "boomlang"
EXTENSIONS = [".boom"]


def slice_text(path, text, mode):
    if "BOOM" in text:
        raise RuntimeError("boom on purpose")
    if mode == "signatures":
        return "calm slice\\n"
    return text
'''

BYTES_PLUGIN = '''
LANGUAGE = "bytelang"
EXTENSIONS = [".byt"]


def slice_text(path, text, mode):
    if mode == "signatures":
        return "bytes result\\n".encode("utf-8")
    return text
'''

NONE_PLUGIN = '''
LANGUAGE = "nonelang"
EXTENSIONS = [".non"]


def slice_text(path, text, mode):
    return None
'''

PY_OVERRIDE_PLUGIN = '''
LANGUAGE = "python"
EXTENSIONS = [".py"]


def slice_text(path, text, mode):
    if mode == "signatures":
        return "PY-BY-PLUGIN\\n"
    return text
'''

PY_EXT_CLAIM_PLUGIN = '''
LANGUAGE = "pylike"
EXTENSIONS = [".py"]


def slice_text(path, text, mode):
    return text
'''

DUP_PLUGIN_A = '''
LANGUAGE = "duplang"
EXTENSIONS = [".dup"]


def slice_text(path, text, mode):
    return "FROM-A\\n" if mode == "signatures" else text
'''

DUP_PLUGIN_B = '''
LANGUAGE = "duplang"
EXTENSIONS = [".dup"]


def slice_text(path, text, mode):
    return "FROM-B\\n" if mode == "signatures" else text
'''

NO_OUTLINE_PLUGIN = '''
LANGUAGE = "barelang"
EXTENSIONS = [".bare"]


def slice_text(path, text, mode):
    if mode == "signatures":
        return "bare slice\\n"
    return text
'''

BROKEN_PLUGIN = "def broken(:\n    pass\n"
EMPTY_PLUGIN = "# just a comment, no contract here\n"

WIB_TEXT = "def alpha(x):\n    body one\n    body two\n\ndef beta(y):\n    body three\n"
PY_TEXT = "def real():\n    return 1\n"


def _load(tmp_path: Path, *files: Path, allow_override: bool = False):
    """Load plugin files as CLI --plugin paths (used as given)."""
    return plugins.load_for_project(
        tmp_path, extra_paths=[str(f) for f in files],
        allow_override=allow_override)


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _project(tmp_path: Path, plugin_src: str = ATTR_PLUGIN,
             plugin_rel: str = "tools/wib.py",
             files: dict | None = None) -> Path:
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    _write(root, plugin_rel, plugin_src)
    _write(root, ".ghostslice.json",
           json.dumps({"plugins": ["./" + plugin_rel]}))
    for rel, text in (files or {"a.wib": WIB_TEXT}).items():
        _write(root, rel, text)
    return root


# -- contract styles ------------------------------------------------

def test_attribute_style_contract(tmp_path):
    f = _write(tmp_path, "wib.py", ATTR_PLUGIN)
    pset = _load(tmp_path, f)
    assert [p.language for p in pset.plugins] == ["wibble"]
    reg = pset.by_language["wibble"]
    assert reg.name == "Wibble (test plugin)"
    assert reg.extensions == (".wib",)
    assert reg.outline is not None
    with plugins.activated(pset):
        out = slice_text("a.wib", WIB_TEXT, "signatures")
    assert "def alpha(x):" in out.text
    assert "body one" not in out.text


def test_register_style_contract(tmp_path):
    f = _write(tmp_path, "reg.py", REGISTER_PLUGIN)
    pset = _load(tmp_path, f)
    assert [p.language for p in pset.plugins] == ["reglang"]
    reg = pset.by_language["reglang"]
    assert reg.name == "Reggie (test plugin)"
    with plugins.activated(pset):
        out = slice_text("a.reg", "anything\n", "signatures")
    assert out.text == "REG-SLICED\n"


def test_register_style_name_defaults_to_file_stem(tmp_path):
    src = REGISTER_PLUGIN.replace('NAME = "Reggie (test plugin)"\n', "")
    f = _write(tmp_path, "myplug.py", src)
    pset = _load(tmp_path, f)
    assert pset.by_language["reglang"].name == "myplug"


def test_missing_contract_rejected(tmp_path):
    f = _write(tmp_path, "empty.py", EMPTY_PLUGIN)
    with pytest.raises(plugins.PluginError, match="contract"):
        _load(tmp_path, f)


def test_syntax_error_rejected(tmp_path):
    f = _write(tmp_path, "broken.py", BROKEN_PLUGIN)
    with pytest.raises(plugins.PluginError, match="failed to load"):
        _load(tmp_path, f)


def test_register_raising_rejected(tmp_path):
    f = _write(tmp_path, "angry.py",
               "def register(api):\n    raise ValueError('nope')\n")
    with pytest.raises(plugins.PluginError, match="register\\(\\) raised"):
        _load(tmp_path, f)


def test_bad_language_name_rejected(tmp_path):
    src = ATTR_PLUGIN.replace('"wibble"', '"Bad Lang!"')
    f = _write(tmp_path, "bad.py", src)
    with pytest.raises(plugins.PluginError, match="invalid language"):
        _load(tmp_path, f)


def test_bad_extension_rejected(tmp_path):
    src = ATTR_PLUGIN.replace('".wib"', '"wib"')
    f = _write(tmp_path, "badext.py", src)
    # "wib" normalises to ".wib" (a missing dot is forgiven)...
    pset = _load(tmp_path, f)
    assert pset.by_language["wibble"].extensions == (".wib",)
    src2 = ATTR_PLUGIN.replace('".wib"', '".."')
    f2 = _write(tmp_path, "badext2.py", src2)
    with pytest.raises(plugins.PluginError, match="invalid extension"):
        _load(tmp_path, f2)


def test_reserved_core_language_rejected(tmp_path):
    src = ATTR_PLUGIN.replace('"wibble"', '"config"')
    f = _write(tmp_path, "cfg.py", src)
    with pytest.raises(plugins.PluginError, match="built in"):
        _load(tmp_path, f)


# -- duplicates and overrides ---------------------------------------

def test_duplicate_new_language_last_wins(tmp_path):
    a = _write(tmp_path, "a.py", DUP_PLUGIN_A)
    b = _write(tmp_path, "b.py", DUP_PLUGIN_B)
    pset = _load(tmp_path, a, b)
    assert [p.language for p in pset.plugins] == ["duplang"]
    assert any("last loaded wins" in n for n in pset.notes)
    with plugins.activated(pset):
        out = slice_text("x.dup", "body\n", "signatures")
    assert out.text == "FROM-B\n"


def test_builtin_override_refused_without_flag(tmp_path):
    f = _write(tmp_path, "pyplug.py", PY_OVERRIDE_PLUGIN)
    with pytest.raises(plugins.PluginError, match="built in"):
        _load(tmp_path, f)


def test_builtin_override_allowed_with_flag(tmp_path):
    f = _write(tmp_path, "pyplug.py", PY_OVERRIDE_PLUGIN)
    pset = _load(tmp_path, f, allow_override=True)
    with plugins.activated(pset):
        out = slice_text("m.py", PY_TEXT, "signatures")
    assert out.text == "PY-BY-PLUGIN\n"


def test_builtin_extension_claim_refused(tmp_path):
    f = _write(tmp_path, "claim.py", PY_EXT_CLAIM_PLUGIN)
    with pytest.raises(plugins.PluginError, match="already belongs to"):
        _load(tmp_path, f)
    pset = _load(tmp_path, f, allow_override=True)
    assert "pylike" in pset.by_language


# -- runtime failure discipline --------------------------------------

def _activated(src: str, tmp_path: Path, name: str = "p.py"):
    f = _write(tmp_path, name, src)
    pset = _load(tmp_path, f)
    return pset


def test_per_file_exception_falls_back(tmp_path):
    pset = _activated(BOOM_PLUGIN, tmp_path)
    with plugins.activated(pset):
        bad = slice_text("x.boom", "has a BOOM inside\n", "signatures")
        good = slice_text("y.boom", "calm content\n", "signatures")
    assert bad.text == "has a BOOM inside\n"  # full text fallback
    assert good.text == "calm slice\n"
    assert len(pset.errors) == 1
    assert pset.errors[0]["kind"] == "slice"
    assert pset.errors[0]["path"] == "x.boom"


def test_bytes_return_is_decoded(tmp_path):
    pset = _activated(BYTES_PLUGIN, tmp_path)
    with plugins.activated(pset):
        out = slice_text("x.byt", "body\n", "signatures")
    assert out.text == "bytes result\n"
    assert pset.errors == []


def test_none_return_falls_back_with_error(tmp_path):
    pset = _activated(NONE_PLUGIN, tmp_path)
    with plugins.activated(pset):
        out = slice_text("x.non", "keep me\n", "signatures")
    assert out.text == "keep me\n"
    assert len(pset.errors) == 1
    assert "NoneType" in pset.errors[0]["error"]


def test_outline_exception_and_bad_rows(tmp_path):
    src = '''
LANGUAGE = "outlang"
EXTENSIONS = [".out"]


def slice_text(path, text, mode):
    return text


def outline(path, text):
    if "BOOM" in text:
        raise RuntimeError("outline boom")
    return [
        {"name": "ok", "kind": "function", "start": 0, "end": 0},
        {"name": "bad", "kind": "function", "start": "x", "end": 0},
        {"name": "neg", "kind": "function", "start": -3, "end": 99},
        "not-a-dict",
    ]
'''
    pset = _activated(src, tmp_path)
    from ghostslice.symslice import outline_source
    with plugins.activated(pset):
        assert outline_source("BOOM\n", "outlang", "x.out") is None
        rows = outline_source("one\ntwo\n", "outlang", "x.out")
    assert [r.name for r in rows] == ["ok", "neg"]
    assert rows[1].start == 0 and rows[1].end == 1  # clamped
    assert [e["kind"] for e in pset.errors] == ["outline"] * 3
    skipped = [e for e in pset.errors if "row skipped" in e["error"]]
    assert len(skipped) == 2


def test_digest_tracks_plugin_bytes(tmp_path):
    f = _write(tmp_path, "wib.py", ATTR_PLUGIN)
    d1 = _load(tmp_path, f).digest
    assert d1
    _write(tmp_path, "wib.py", ATTR_PLUGIN + "\n# a comment edit\n")
    d2 = _load(tmp_path, f).digest
    assert d1 != d2
    assert plugins.PluginSet().digest == ""


# -- profile loading and containment --------------------------------

def test_profile_loading_and_scan(tmp_path):
    root = _project(tmp_path)
    pset = plugins.load_for_project(root)
    assert [p.language for p in pset.plugins] == ["wibble"]
    assert pset.plugins[0].source_label == "./tools/wib.py"
    assert len(pset.plugins[0].sha256) == 64
    with plugins.activated(pset):
        result = scan(root)
    by_path = {f.path: f for f in result.files}
    assert by_path["a.wib"].language == "wibble"
    assert by_path["a.wib"].tokens > 0


def test_profile_containment_parent_path_rejected(tmp_path):
    root = _project(tmp_path)
    _write(root, ".ghostslice.json",
           json.dumps({"plugins": ["../outside.py"]}))
    _write(tmp_path, "outside.py", ATTR_PLUGIN)
    with pytest.raises(plugins.PluginError, match="outside the project root"):
        plugins.load_for_project(root)


def test_profile_containment_absolute_rejected(tmp_path):
    root = _project(tmp_path)
    outside = _write(tmp_path, "abs.py", ATTR_PLUGIN)
    _write(root, ".ghostslice.json",
           json.dumps({"plugins": [str(outside)]}))
    with pytest.raises(plugins.PluginError, match="must be relative"):
        plugins.load_for_project(root)


def test_profile_containment_symlink_rejected(tmp_path):
    root = _project(tmp_path)
    outside = _write(tmp_path, "real.py", ATTR_PLUGIN)
    link = root / "tools" / "link.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    _write(root, ".ghostslice.json",
           json.dumps({"plugins": ["./tools/link.py"]}))
    with pytest.raises(plugins.PluginError, match="outside the project root"):
        plugins.load_for_project(root)


def test_profile_missing_plugin_file_rejected(tmp_path):
    root = _project(tmp_path)
    _write(root, ".ghostslice.json",
           json.dumps({"plugins": ["./tools/nope.py"]}))
    with pytest.raises(plugins.PluginError, match="no such file"):
        plugins.load_for_project(root)


def test_no_profile_means_no_plugins(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    _write(root, "a.py", PY_TEXT)
    pset = plugins.load_for_project(root)
    assert pset.plugins == []
    assert pset.digest == ""


def test_nothing_loads_without_being_named(tmp_path):
    # A plugin file sitting in the project is NOT loaded unless the
    # profile or a flag names it: no auto-discovery, ever.
    root = tmp_path / "proj"
    root.mkdir()
    _write(root, "tools/wib.py", ATTR_PLUGIN)
    _write(root, "a.wib", WIB_TEXT)
    pset = plugins.load_for_project(root)
    assert pset.plugins == []
    with plugins.activated(pset):
        result = scan(root)
    assert all(f.language != "wibble" for f in result.files)


# -- CLI --------------------------------------------------------------

def test_cli_plugin_flag_export(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    plugin = _write(root, "tools/wib.py", ATTR_PLUGIN)
    _write(root, "a.wib", WIB_TEXT)
    out = tmp_path / "bundle"
    rc = cli_main(["export", str(root), "-o", str(out),
                   "--plugin", str(plugin)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "Wibble (test plugin)" in err
    assert "language wibble" in err
    assert "full privileges" in err  # the trust warning, every load
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["plugins"][0]["language"] == "wibble"
    bundle_text = (out / "files" / "a.wib").read_text()
    assert "def alpha(x):" in bundle_text
    assert "body one" not in bundle_text


def test_cli_slice_single_file_with_plugin(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    plugin = _write(root, "wib.py", ATTR_PLUGIN)
    target = _write(root, "a.wib", WIB_TEXT)
    out = tmp_path / "sliced"
    rc = cli_main(["slice", str(target), "-o", str(out),
                   "--plugin", str(plugin)])
    assert rc == 0
    assert "body one" not in (out / "a.wib").read_text()


def test_cli_load_failure_exit2_before_writes(tmp_path, capsys):
    root = _project(tmp_path)
    _write(root, "tools/wib.py", BROKEN_PLUGIN)
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    out = tmp_path / "bundle"
    rc = cli_main(["export", str(root), "-o", str(out)])
    assert rc == 2
    assert not out.exists()  # nothing written
    after = sorted(p.relative_to(root) for p in root.rglob("*"))
    assert before == after
    assert "failed to load" in capsys.readouterr().err


def test_cli_profile_load_failure_exit2_scan(tmp_path, capsys):
    root = _project(tmp_path)
    _write(root, "tools/wib.py", BROKEN_PLUGIN)
    rc = cli_main(["scan", str(root)])
    assert rc == 2
    assert "failed to load" in capsys.readouterr().err


def test_cli_per_file_failure_falls_back(tmp_path, capsys):
    root = _project(tmp_path, plugin_src=BOOM_PLUGIN,
                    plugin_rel="tools/boom.py",
                    files={"bad.boom": "this has a BOOM inside\n",
                           "good.boom": "calm content\n"})
    out = tmp_path / "bundle"
    rc = cli_main(["export", str(root), "-o", str(out)])
    assert rc == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest["plugin_errors"]) == 1
    assert manifest["plugin_errors"][0]["path"] == "bad.boom"
    assert (out / "files" / "bad.boom").read_text() == \
        "this has a BOOM inside\n"  # full text, not a slice
    assert (out / "files" / "good.boom").read_text() == "calm slice\n"
    assert "plugin" in capsys.readouterr().err.lower()


def test_cli_override_refused_then_allowed(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    plugin = _write(root, "pyplug.py", PY_OVERRIDE_PLUGIN)
    _write(root, "m.py", PY_TEXT)
    out = tmp_path / "bundle"
    rc = cli_main(["export", str(root), "-o", str(out),
                   "--plugin", str(plugin)])
    assert rc == 2
    assert "refusing to replace its slicer" in capsys.readouterr().err
    assert not out.exists()
    rc = cli_main(["export", str(root), "-o", str(out),
                   "--plugin", str(plugin), "--allow-plugin-override"])
    assert rc == 0
    assert (out / "files" / "m.py").read_text() == "PY-BY-PLUGIN\n"


def test_cli_lint_does_not_crash(tmp_path, capsys):
    root = _project(tmp_path)
    rc = cli_main(["lint", str(root), "--json"])
    assert rc in (0, 1)
    payload = json.loads(capsys.readouterr().out)
    assert "findings" in payload


# -- pipeline integration --------------------------------------------

def test_whatif_with_plugin_language(tmp_path):
    # The dashboard what-if runs the exporter's own machinery over
    # the startup scan (plugins active from the profile): its totals
    # must equal a real build's, plugin language included.
    from ghostslice.server import _State, whatif_payload
    root = _project(tmp_path)
    state = _State(str(root))
    payload = whatif_payload(state, {})
    assert payload["ok"] is True
    assert payload["sliced_tokens"] < payload["original_tokens"]
    manifest = build_bundle(root, tmp_path / "b")
    assert payload["sliced_tokens"] == manifest["total_sliced_tokens"]
    assert payload["original_tokens"] == manifest["total_original_tokens"]


FIT_PLUGIN = '''
LANGUAGE = "fitlang"
EXTENSIONS = [".fit"]


def slice_text(path, text, mode):
    lines = text.split("\\n")
    if mode == "signatures":
        return "\\n".join(
            l for l in lines if not l.startswith("deep")) + "\\n"
    if mode == "interfaces":
        return "\\n".join(
            l for l in lines if l.startswith("def ")) + "\\n"
    return text
'''

FIT_TEXT = ("def a():\n"
            "    shallow body words here\n"
            "    deep padding one two three four five\n"
            "    deep padding six seven eight nine ten\n"
            "def b():\n"
            "    shallow body words here too\n")


def test_fit_ladder_reaches_plugin_language(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    plugin = _write(tmp_path, "fit.py", FIT_PLUGIN)
    _write(root, "a.fit", FIT_TEXT)
    plain = build_bundle(root, tmp_path / "b1", plugins=[str(plugin)])
    entry = plain["files"][0]
    assert entry["mode"] == "signatures"
    sig_tokens = entry["sliced_tokens"]
    from ghostslice.tokens import estimate_tokens
    iface_tokens = estimate_tokens("def a():\ndef b():\n", "fitlang")
    assert iface_tokens < sig_tokens
    fitted = build_bundle(root, tmp_path / "b2", plugins=[str(plugin)],
                          fit=iface_tokens)
    assert fitted["fit"]["fitted"] is True
    assert fitted["files"][0]["mode"] == "interfaces"


def test_cache_invalidated_by_plugin_byte_change(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    plugin = _write(root, "wib.py", ATTR_PLUGIN)
    _write(root, "a.wib", WIB_TEXT)
    m1 = build_bundle(root, tmp_path / "b1", plugins=[str(plugin)])
    assert (root / ".ghostslice-cache").is_dir()
    t1 = m1["total_sliced_tokens"]
    # Same project, same sources: the plugin's CODE changes (a
    # longer signatures rendering). Content+mode+version are all
    # unchanged, so only the plugin digest can save us from serving
    # the stale cached slice.
    _write(root, "wib.py", ATTR_PLUGIN.replace(
        'if mode == "signatures":',
        'if mode == "signatures":\n'
        '        return text + "\\n".join('
        '"extra padding line %d" % i for i in range(40)) + "\\n"'))
    m2 = build_bundle(root, tmp_path / "b2", plugins=[str(plugin)])
    assert m2["total_sliced_tokens"] > t1
    assert (tmp_path / "b2" / "files" / "a.wib").read_text() != \
        (tmp_path / "b1" / "files" / "a.wib").read_text()


def test_dashboard_state_loads_profile_plugins(tmp_path):
    from ghostslice.server import _State
    root = _project(tmp_path)
    state = _State(str(root))
    langs = {f.path: f.language for f in state.scan.files}
    assert langs.get("a.wib") == "wibble"


# -- the shipped Lua example, end to end ------------------------------

LUA_TEXT = """-- a tiny game module
local M = {}

local function clamp(x, lo, hi)
    if x < lo then
        return lo
    end
    return x
end

function M.spawn(name, hp)
    local s = "function fake() end"
    --[[
    function ghost() end
    ]]
    for i = 1, 3 do
        print(name, i)
    end
    return clamp(hp, 1, 100)
end

function M.reset()
    print("reset")
end

return M
"""


def _lua_project(tmp_path: Path) -> Path:
    root = tmp_path / "luaproj"
    root.mkdir()
    tools = root / "tools"
    tools.mkdir()
    shutil.copy(EXAMPLES / "lua_slicer.py", tools / "lua_slicer.py")
    _write(root, ".ghostslice.json",
           json.dumps({"plugins": ["./tools/lua_slicer.py"]}))
    _write(root, "game.lua", LUA_TEXT)
    return root


def test_example_lua_plugin_end_to_end(tmp_path, capsys):
    root = _lua_project(tmp_path)
    out = tmp_path / "bundle"
    rc = cli_main(["export", str(root), "-o", str(out)])
    assert rc == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["plugins"][0]["language"] == "lua"
    entry = {f["path"]: f for f in manifest["files"]}["game.lua"]
    assert entry["language"] == "lua"
    assert entry["mode"] == "signatures"
    assert entry["sliced_tokens"] < entry["original_tokens"]
    sliced = (out / "files" / "game.lua").read_text()
    assert "local function clamp(x, lo, hi)" in sliced
    assert "function M.spawn(name, hp)" in sliced
    assert "-- ..." in sliced
    assert "return clamp(hp, 1, 100)" not in sliced  # body dropped
    # The string/comment traps did not break block matching:
    # clamp's real span still closed before M.spawn's def line.
    assert sliced.index("clamp") < sliced.index("M.spawn")


def test_example_lua_symbols_and_symbol_slicing(tmp_path, capsys):
    root = _lua_project(tmp_path)
    rc = cli_main(["symbols", str(root)])
    assert rc == 0
    out_text = capsys.readouterr().out
    assert "game.lua (lua)" in out_text
    assert "M.spawn" in out_text
    assert "clamp" in out_text
    # Symbol-level slicing keeps the requested body only.
    out = tmp_path / "bundle"
    rc = cli_main(["export", str(root), "-o", str(out),
                   "--symbols", "M.spawn"])
    assert rc == 0
    sliced = (out / "files" / "game.lua").read_text()
    assert "return clamp(hp, 1, 100)" in sliced  # spawn body kept
    assert 'print("reset")' not in sliced        # reset body dropped


def test_symbols_without_outline_is_honest(tmp_path, capsys):
    root = _project(tmp_path, plugin_src=NO_OUTLINE_PLUGIN,
                    plugin_rel="tools/bare.py",
                    files={"x.bare": "some content\nmore\n"})
    rc = cli_main(["symbols", str(root)])
    assert rc == 0
    out_text = capsys.readouterr().out
    assert "no symbol outline" in out_text
    assert "bare slice" not in out_text


def test_mcp_with_profile_plugins(tmp_path):
    root = _lua_project(tmp_path)
    resp = handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "scan_project",
                   "arguments": {"path": str(root)}}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    langs = {f["path"]: f["language"] for f in payload["files"]}
    assert langs.get("game.lua") == "lua"
    out = tmp_path / "mcpbundle"
    resp = handle_message({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "export_bundle",
                   "arguments": {"path": str(root), "out": str(out)}}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["plugins"][0]["language"] == "lua"
    sliced = (out / "files" / "game.lua").read_text()
    assert "return clamp(hp, 1, 100)" not in sliced
    resp = handle_message({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "slice_file",
                   "arguments": {"path": str(root), "file": "game.lua",
                                 "mode": "interfaces"}}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "function M.spawn(name, hp)" in payload["text"]
    assert "local function clamp" not in payload["text"]


# -- audit round 1 regressions (F1-F4) --------------------------------

SYSEXIT_LOAD_PLUGIN = "import sys\nsys.exit(3)\n"
SYSEXIT_SLICE_PLUGIN = '''
import sys

LANGUAGE = "exitlang"
EXTENSIONS = [".exit"]


def slice_text(path, text, mode):
    sys.exit(3)
'''


def test_sysexit_at_load_is_a_plugin_error(tmp_path):
    # F1: sys.exit() at import time is a load failure with a
    # message, never a silent exit with the plugin's code.
    f = _write(tmp_path, "exit.py", SYSEXIT_LOAD_PLUGIN)
    with pytest.raises(plugins.PluginError, match="SystemExit"):
        _load(tmp_path, f)


def test_sysexit_in_slicer_falls_back(tmp_path):
    # F1: sys.exit() while slicing one file falls back for that
    # file and records the failure; the run survives.
    pset = _activated(SYSEXIT_SLICE_PLUGIN, tmp_path)
    with plugins.activated(pset):
        out = slice_text("x.exit", "keep me\n", "signatures")
    assert out.text == "keep me\n"
    assert len(pset.errors) == 1
    assert "SystemExit" in pset.errors[0]["error"]


def test_cli_slice_reports_plugin_failure(tmp_path, capsys):
    # F2: the single-file slice surface must not fall back silently.
    root = _project(tmp_path, plugin_src=BOOM_PLUGIN,
                    plugin_rel="tools/boom.py",
                    files={"bad.boom": "this has a BOOM inside\n"})
    target = root / "bad.boom"
    out = tmp_path / "sliced"
    rc = cli_main(["slice", str(target), "-o", str(out)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "full text used instead" in err
    assert (out / "bad.boom").read_text() == "this has a BOOM inside\n"


def test_cli_symbols_reports_outline_failure(tmp_path, capsys):
    # F2: an exploding outline is reported, not folded silently
    # into the "no outline" bucket.
    src = NO_OUTLINE_PLUGIN.replace(
        'LANGUAGE = "barelang"', 'LANGUAGE = "ob"').replace(
        'EXTENSIONS = [".bare"]', 'EXTENSIONS = [".ob"]') + '''

def outline(path, text):
    raise RuntimeError("outline exploded")
'''
    root = _project(tmp_path, plugin_src=src, plugin_rel="tools/ob.py",
                    files={"x.ob": "stuff\n"})
    rc = cli_main(["symbols", str(root)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "outline exploded" in err
    assert "treated as no outline" in err


def test_extension_reclaim_records_a_note(tmp_path):
    # F3: a later plugin claiming an extension another plugin
    # already claimed (different language) is announced, and wins.
    a = _write(tmp_path, "a.py", DUP_PLUGIN_A.replace(
        '"duplang"', '"alfa"').replace('".dup"', '".zz"'))
    b = _write(tmp_path, "b.py", DUP_PLUGIN_B.replace(
        '"duplang"', '"beta"').replace('".dup"', '".zz"'))
    pset = _load(tmp_path, a, b)
    assert any("already claimed" in n and ".zz" in n
               for n in pset.notes)
    assert pset.by_ext[".zz"] == "beta"


def test_plugin_directory_message(tmp_path):
    # F4: a directory named as a plugin says "not a file".
    with pytest.raises(plugins.PluginError, match="not a file"):
        plugins.load_for_project(tmp_path, extra_paths=[str(tmp_path)])


# -- audit round 2 regressions (F5-F7) --------------------------------

def test_dashboard_export_surfaces_plugin_errors(tmp_path):
    # F5: /api/export mirrors the manifest's plugin blocks, like
    # it already does for fit and redaction.
    import threading
    import urllib.request
    from ghostslice.server import make_server
    root = _project(tmp_path, plugin_src=BOOM_PLUGIN,
                    plugin_rel="tools/boom.py",
                    files={"bad.boom": "this has a BOOM inside\n"})
    server, _state = make_server(str(root), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/export",
            data=json.dumps({"out": ".claude_context"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read())
    finally:
        server.shutdown()
        server.server_close()
    assert payload["ok"] is True
    assert payload["plugins"][0]["language"] == "boomlang"
    assert len(payload["plugin_errors"]) == 1
    assert payload["plugin_errors"][0]["path"] == "bad.boom"


def test_mcp_slice_file_surfaces_plugin_errors(tmp_path):
    # F6: a plugin failure inside MCP slice_file is reported in
    # the result, not folded into a silent full-text return.
    root = _project(tmp_path, plugin_src=BOOM_PLUGIN,
                    plugin_rel="tools/boom.py",
                    files={"bad.boom": "this has a BOOM inside\n"})
    resp = handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "slice_file",
                   "arguments": {"path": str(root), "file": "bad.boom",
                                 "mode": "signatures"}}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["text"] == "this has a BOOM inside\n"
    assert len(payload["plugin_errors"]) == 1
    assert "boom on purpose" in payload["plugin_errors"][0]["error"]


def test_init_summary_mentions_plugins(tmp_path):
    # F7: refusing to overwrite an existing profile names its
    # plugins, so a --force regeneration is an informed choice.
    import io
    from ghostslice.init_wizard import run_init
    root = _project(tmp_path)
    err = io.StringIO()
    code, _payload = run_init(root, out=io.StringIO(), err=err)
    assert code == 2
    assert "1 plugin(s)" in err.getvalue()
