"""v0.18 (G13): symbol-level slicing.

Fixtures: a Python project (two classes with methods, a nested
function, a decorated async method, an ambiguous bare name shared
by two files, a Markdown file with no outline), a TypeScript file
(interface + class + arrow functions), and a C++ file with
out-of-line definitions. The core promises under test: a requested
symbol ships WITH its body, its siblings collapse to signatures,
files with no requested symbol are excluded, ambiguity is reported
(never silently resolved), and an unknown name is a hard error
with near-miss suggestions.
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.cli import main as cli_main
from ghostslice.exporter import build_bundle, validate_bundle
from ghostslice.mcp_server import handle_message
from ghostslice.symslice import (UnknownSymbolError, outline_source,
                                 resolve_symbol_selection,
                                 slice_with_symbols)
from ghostslice.scanner import scan

AUTH_PY = '''"""Auth module."""
import hashlib

LIMIT = 5


def traced(fn):
    return fn


class Auth:
    """Auth class."""

    @traced
    def login(self, user):
        """Log in a user."""
        token = hashlib.sha256(user.encode()).hexdigest()
        return "LOGIN_BODY_" + token

    def refresh(self):
        return "REFRESH_BODY"

    async def logout(self):
        return "LOGOUT_BODY"


def outer(a, b):
    x = a + b
    def inner(c):
        return "INNER_BODY_" + str(c)
    return inner(x)


def hash_password(pw):
    return "HASH_BODY_" + pw
'''

DB_PY = '''class DB:
    def connect(self):
        return "CONNECT_BODY"


class Outer:
    class Inner:
        def deep(self):
            return "DEEP_BODY"


def login():
    return "DB_LOGIN_BODY"
'''

UTIL_PY = '''def unrelated():
    return "UNRELATED_BODY"
'''

NOTES_MD = "# Notes\n\nSome prose about login flows.\n"

APP_TS = '''import { readFile } from "fs";

export interface Shape {
  area(): number;
  name: string;
}

export function fetchData(url: string): string {
  const body = readFile(url);
  return "FETCHED:" + body;
}

export const helper = (x: number): number => {
  return x * 2;
};

export class Store {
  total(items: number[]): number {
    return items.reduce((a, b) => a + b, 0);
  }
  checkout(): string {
    return "CHECKOUT_BODY_MARKER";
  }
}
'''

STORE_CPP = '''#include <string>

class Store {
 public:
  int total();
  int checkout();
};

int Store::total() {
  return 42;
}

int Store::checkout() {
  return 7;
}
'''


def make_project(root: Path):
    (root / "auth.py").write_text(AUTH_PY, encoding="utf-8")
    (root / "db.py").write_text(DB_PY, encoding="utf-8")
    (root / "util.py").write_text(UTIL_PY, encoding="utf-8")
    (root / "notes.md").write_text(NOTES_MD, encoding="utf-8")
    (root / "app.ts").write_text(APP_TS, encoding="utf-8")
    (root / "store.cpp").write_text(STORE_CPP, encoding="utf-8")


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli_main(argv)
    return code, out.getvalue(), err.getvalue()


class OutlineTests(unittest.TestCase):
    def test_python_outline_exact(self):
        syms = outline_source(AUTH_PY, "python", "auth.py")
        by_q = {s.qualified: s for s in syms}
        self.assertIn("Auth.login", by_q)
        self.assertEqual(by_q["Auth.login"].kind, "method")
        self.assertEqual(by_q["LIMIT"].kind, "constant")
        self.assertEqual(by_q["outer.inner"].kind, "function")
        self.assertEqual(by_q["outer.inner"].parent, "outer")
        # Decorated method: the span starts at the decorator line.
        lines = AUTH_PY.splitlines()
        self.assertEqual(lines[by_q["Auth.login"].start], "    @traced")
        # 1-based lines via the CLI convention: start+1 is the @ line.
        login_line = next(i for i, l in enumerate(lines) if "def login" in l)
        self.assertEqual(by_q["Auth.login"].decl, login_line)

    def test_no_outline_languages(self):
        self.assertIsNone(outline_source(NOTES_MD, "markdown", "notes.md"))
        self.assertIsNone(outline_source("{}", "json", "x.json"))
        self.assertIsNone(outline_source("cells", "notebook", "x.ipynb"))

    def test_ts_outline(self):
        syms = outline_source(APP_TS, "typescript", "app.ts")
        by_q = {s.qualified: s for s in syms}
        self.assertEqual(by_q["Shape"].kind, "type")
        self.assertEqual(by_q["Shape.area"].kind, "method")
        self.assertEqual(by_q["Store.total"].kind, "method")
        self.assertEqual(by_q["helper"].kind, "function")
        self.assertEqual(by_q["fetchData"].kind, "function")

    def test_cpp_outline_qualified(self):
        syms = outline_source(STORE_CPP, "cpp", "store.cpp")
        quals = {s.qualified for s in syms}
        self.assertIn("Store::total", quals)       # out-of-line definition
        self.assertIn("Store::checkout", quals)
        self.assertIn("Store", quals)              # the class itself

    def test_extra_language_property_symbols(self):
        # Audit G13 F2: kotlin/swift properties and PHP fields are
        # symbols (signatures keeps them, task selection counts them).
        kt = ('val VERSION = "1.0"\n\nclass Store {\n    val limit: Int = 5\n'
              '    fun total(): Int {\n        return limit\n    }\n}\n')
        quals = {s.qualified for s in outline_source(kt, "kotlin", "c.kt")}
        self.assertIn("VERSION", quals)
        self.assertIn("Store.limit", quals)
        php = ('<?php\nclass Store {\n    private int $count = 0;\n'
               '    public function total(): int {\n'
               '        return $this->count;\n    }\n}\n')
        quals = {s.qualified for s in outline_source(php, "php", "s.php")}
        self.assertIn("Store.count", quals)
        out = slice_with_symbols("s.php", php, {"Store.total"})
        self.assertIn("$count = 0;", out)  # field is shell context

    def test_go_rust_java_ruby_scala_php_kotlin_swift_outlines(self):
        cases = {
            "go": ('package p\n\nfunc (s *Store) Total() int {\n'
                   ' return 1\n}\n', "Store.Total"),
            "rust": ('impl Store {\n pub fn total(&self) -> i32 {\n'
                     '  1\n }\n}\n', "Store.total"),
            "java": ('public class Store {\n public int total() {\n'
                     '  return 1;\n }\n}\n', "Store.total"),
            "csharp": ('public class Store {\n public int Total() {\n'
                       '  return 1;\n }\n}\n', "Store.Total"),
            "ruby": ('class Store\n def total\n  1\n end\nend\n',
                     "Store.total"),
            "scala": ('class Store {\n def total: Int = {\n  1\n }\n}\n',
                      "Store.total"),
            "php": ('<?php\nclass Store {\n public function total(): int {\n'
                    '  return 1;\n }\n}\n', "Store.total"),
            "kotlin": ('class Store {\n fun total(): Int {\n  return 1\n'
                       ' }\n}\n', "Store.total"),
            "swift": ('struct Store {\n func total() -> Int {\n'
                      '  return 1\n }\n}\n', "Store.total"),
        }
        for lang, (src, want) in cases.items():
            with self.subTest(lang=lang):
                syms = outline_source(src, lang, f"x.{lang}")
                self.assertIn(want, {s.qualified for s in syms})


class SliceRenderTests(unittest.TestCase):
    def test_python_keep_body_collapse_sibling(self):
        out = slice_with_symbols("auth.py", AUTH_PY, {"Auth.login"})
        self.assertIn("LOGIN_BODY_", out)          # kept body
        self.assertNotIn("REFRESH_BODY", out)      # sibling body gone
        self.assertIn("def refresh(self): ...", out)  # sibling signature
        self.assertNotIn("LOGOUT_BODY", out)
        self.assertIn("import hashlib", out)       # always-context
        self.assertIn('"""Auth module."""', out)    # module docstring line
        self.assertIn("def login(self, user):", out)
        self.assertIn("@traced", out)              # decorator kept

    def test_python_class_kept_whole(self):
        out = slice_with_symbols("auth.py", AUTH_PY, {"Auth"})
        self.assertIn("LOGIN_BODY_", out)
        self.assertIn("REFRESH_BODY", out)
        self.assertIn("LOGOUT_BODY", out)

    def test_python_nested_function(self):
        out = slice_with_symbols("auth.py", AUTH_PY, {"outer.inner"})
        self.assertIn("INNER_BODY_", out)
        self.assertIn("def outer(a, b):", out)     # shell head
        self.assertNotIn("x = a + b", out)         # outer's own body gone
        self.assertNotIn("return inner(x)", out)

    def test_python_two_classes_no_leak(self):
        src = ('class A:\n    def keep_me(self):\n        return "A_KEEP"\n\n'
               'class B:\n    def secret_body(self):\n'
               '        return "B_BODY_MARKER"\n')
        out = slice_with_symbols("x.py", src, {"A.keep_me"})
        self.assertIn("A_KEEP", out)
        self.assertNotIn("B_BODY_MARKER", out)
        self.assertIn("def secret_body(self): ...", out)

    def test_ts_keep_body_and_interface_whole(self):
        out = slice_with_symbols("app.ts", APP_TS, {"Store.total"})
        self.assertIn("items.reduce", out)               # kept body
        self.assertNotIn("CHECKOUT_BODY_MARKER", out)    # sibling body
        self.assertIn("checkout(): string { /* ... */ }", out)
        self.assertIn("area(): number;", out)            # interface whole
        self.assertIn("fetchData(url: string): string { /* ... */ }", out)
        self.assertIn('import { readFile } from "fs";', out)

    def test_conditional_definitions_render(self):
        # Audit G13 F1: defs inside module-level if/else are in the
        # outline; the renderer must not silently drop them.
        src = ('import sys\nif sys.version_info > (3, 0):\n'
               '    def go():\n        return "NEW_GO"\nelse:\n'
               '    def go():\n        return "OLD_GO"\n')
        out = slice_with_symbols("dup.py", src, {"go"})
        self.assertIn("NEW_GO", out)
        self.assertIn("OLD_GO", out)
        out2 = slice_with_symbols(
            "dup.py", src + '\ndef top():\n    return "TOP"\n', {"top"})
        self.assertNotIn("NEW_GO", out2)       # not kept: no bodies
        self.assertIn("def go():", out2)       # but signposted

    def test_type_checking_method_in_class_shell(self):
        src = ('from typing import TYPE_CHECKING\n\nclass M:\n'
               '    if TYPE_CHECKING:\n'
               '        def typed(self):\n'
               '            return "TYPED_BODY"\n'
               '    def plain(self):\n'
               '        return "PLAIN_BODY"\n')
        out = slice_with_symbols("m.py", src, {"M.typed"})
        self.assertIn("TYPED_BODY", out)
        self.assertNotIn("PLAIN_BODY", out)

    def test_cpp_out_of_line_body(self):
        out = slice_with_symbols("store.cpp", STORE_CPP, {"Store::total"})
        self.assertIn("return 42;", out)
        self.assertNotIn("return 7;", out)
        self.assertIn("int Store::checkout() { /* ... */ }", out)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "proj"
        self.root.mkdir()
        make_project(self.root)
        self.out = Path(self._tmp.name) / "bundle"

    def manifest_entry(self, manifest, path):
        return next(f for f in manifest["files"] if f["path"] == path)

    def test_export_symbols_end_to_end(self):
        manifest = build_bundle(self.root, self.out, symbols="Auth.login")
        entry = self.manifest_entry(manifest, "auth.py")
        self.assertEqual(entry["mode"], "symbols")
        self.assertEqual(entry["symbols_included"], ["Auth.login"])
        self.assertEqual(self.manifest_entry(manifest, "db.py")["mode"],
                         "exclude")
        self.assertFalse((self.out / "files" / "db.py").exists())
        text = (self.out / "files" / "auth.py").read_text(encoding="utf-8")
        self.assertIn("LOGIN_BODY_", text)
        self.assertNotIn("REFRESH_BODY", text)
        prompt = (self.out / "PROMPT.md").read_text(encoding="utf-8")
        self.assertIn("# File: auth.py (mode: symbols: Auth.login)", prompt)
        self.assertTrue(validate_bundle(self.out)["ok"])
        rep = manifest["symbols"]
        self.assertEqual(rep["requested"], ["Auth.login"])
        self.assertEqual(rep["matches"]["Auth.login"],
                         [{"path": "auth.py", "symbol": "Auth.login"}])
        self.assertEqual(rep["ambiguous"], [])

    def test_ambiguity_includes_all_and_reports(self):
        manifest = build_bundle(self.root, self.out, symbols=["login"])
        self.assertEqual(manifest["symbols"]["ambiguous"], ["login"])
        auth = (self.out / "files" / "auth.py").read_text(encoding="utf-8")
        db = (self.out / "files" / "db.py").read_text(encoding="utf-8")
        self.assertIn("LOGIN_BODY_", auth)
        self.assertIn("DB_LOGIN_BODY", db)
        code, stdout, _ = run_cli(
            ["export", str(self.root), "-o", str(self.out) + "2",
             "--symbols", "login"])
        self.assertEqual(code, 0)
        self.assertIn("matched in 2 files", stdout)
        self.assertIn("all matches included", stdout)

    def test_file_scoped_and_suffix_match(self):
        manifest = build_bundle(self.root, self.out, symbols="db.py:login")
        self.assertEqual(manifest["symbols"]["files"], {"db.py": ["login"]})
        self.assertFalse((self.out / "files" / "auth.py").exists())
        # Suffix match: Inner.deep reaches Outer.Inner.deep.
        manifest2 = build_bundle(self.root, str(self.out) + "b",
                                 symbols="Inner.deep")
        self.assertEqual(manifest2["symbols"]["files"],
                         {"db.py": ["Outer.Inner.deep"]})
        text = (Path(str(self.out) + "b") / "files" / "db.py").read_text(
            encoding="utf-8")
        self.assertIn("DEEP_BODY", text)

    def test_glob_selection(self):
        manifest = build_bundle(self.root, self.out, symbols="hash_*")
        self.assertEqual(manifest["symbols"]["files"],
                         {"auth.py": ["hash_password"]})
        manifest2 = build_bundle(self.root, str(self.out) + "g",
                                 symbols="*.refresh")
        self.assertEqual(manifest2["symbols"]["files"],
                         {"auth.py": ["Auth.refresh"]})

    def test_unknown_symbol_hard_error(self):
        with self.assertRaises(UnknownSymbolError) as ctx:
            build_bundle(self.root, self.out, symbols="logn")
        self.assertIn("login", str(ctx.exception))
        self.assertFalse(self.out.exists())  # nothing written
        code, _stdout, stderr = run_cli(
            ["export", str(self.root), "-o", str(self.out),
             "--symbols", "logn"])
        self.assertEqual(code, 2)
        self.assertIn("did you mean", stderr)
        # A file-scoped unknown in a no-outline file is unknown too.
        with self.assertRaises(UnknownSymbolError):
            build_bundle(self.root, self.out, symbols="notes.md:Intro")

    def test_totals_ordering(self):
        sym = build_bundle(self.root, str(self.out) + "s",
                           symbols="Auth.login")
        sig = build_bundle(self.root, str(self.out) + "g")
        full = build_bundle(self.root, str(self.out) + "f",
                            default_mode="full")
        self.assertLess(sym["total_sliced_tokens"],
                        sig["total_sliced_tokens"])
        self.assertLess(sig["total_sliced_tokens"],
                        full["total_sliced_tokens"])

    def test_symbols_fit_rejected(self):
        with self.assertRaises(ValueError):
            build_bundle(self.root, self.out, symbols="Auth.login", fit=1000)
        code, _o, stderr = run_cli(
            ["export", str(self.root), "-o", str(self.out),
             "--symbols", "Auth.login", "--fit", "1000"])
        self.assertEqual(code, 2)
        self.assertIn("--fit", stderr)

    def test_entry_points_keep_their_mode(self):
        (self.root / "main.py").write_text(
            'def main():\n    return "MAIN_BODY"\n', encoding="utf-8")
        (self.root / ".ghostslice.json").write_text(json.dumps(
            {"entry_points": ["main.py"]}), encoding="utf-8")
        from ghostslice.profile import load_profile
        profile = load_profile(self.root)
        manifest = build_bundle(self.root, self.out, profile=profile,
                                symbols="Auth.login")
        main_entry = self.manifest_entry(manifest, "main.py")
        self.assertEqual(main_entry["mode"], "signatures")  # not symbols
        self.assertTrue((self.out / "files" / "main.py").exists())
        self.assertEqual(self.manifest_entry(manifest, "util.py")["mode"],
                         "exclude")

    def test_redact_composition(self):
        key = "AKIA" + "1234567890ABCDEF"  # assembled: see test_v17 note
        (self.root / "leaky.py").write_text(
            f'def connect():\n    return "{key}"\n', encoding="utf-8")
        manifest = build_bundle(self.root, self.out,
                                symbols="leaky.py:connect", redact=True)
        self.assertEqual(manifest["symbols"]["files"],
                         {"leaky.py": ["connect"]})
        blob = b"".join(p.read_bytes() for p in sorted(self.out.rglob("*"))
                        if p.is_file())
        self.assertNotIn(key.encode(), blob)
        self.assertIn(b"[REDACTED:aws-access-key:", blob)
        self.assertTrue(validate_bundle(self.out)["ok"])

    def test_preset_wrappers_carry_symbol_slices(self):
        manifest = build_bundle(self.root, self.out, symbols="Auth.login",
                                preset="json")
        payload = json.loads((self.out / "context.json").read_text(
            encoding="utf-8"))
        files = {f["path"]: f for f in payload["files"]}
        self.assertEqual(files["auth.py"]["mode"], "symbols")
        self.assertIn("LOGIN_BODY_", files["auth.py"]["content"])
        self.assertNotIn("REFRESH_BODY", files["auth.py"]["content"])
        self.assertTrue(validate_bundle(self.out)["ok"])
        self.assertEqual(manifest["symbols"]["requested"], ["Auth.login"])


class CliSymbolsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "proj"
        self.root.mkdir()
        make_project(self.root)

    def test_symbols_listing(self):
        code, stdout, _ = run_cli(["symbols", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("Auth.login", stdout)
        self.assertIn("method", stdout)
        self.assertIn("Outer.Inner.deep", stdout)
        self.assertIn("no symbol outline", stdout)  # notes.md counted
        self.assertIn("token counts are estimates", stdout)

    def test_symbols_single_file_and_json(self):
        code, stdout, _ = run_cli(["symbols", str(self.root), "auth.py"])
        self.assertEqual(code, 0)
        self.assertIn("Auth.refresh", stdout)
        self.assertNotIn("DB.connect", stdout)
        code, stdout, _ = run_cli(
            ["symbols", str(self.root), "notes.md"])
        self.assertEqual(code, 0)
        self.assertIn("no symbol outline for this language", stdout)
        code, stdout, _ = run_cli(["symbols", str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        auth = next(f for f in payload["files"] if f["path"] == "auth.py")
        quals = {s["qualified"] for s in auth["symbols"]}
        self.assertIn("Auth.login", quals)
        notes = next(f for f in payload["files"] if f["path"] == "notes.md")
        self.assertIsNone(notes["symbols"])
        self.assertIn("notes.md", payload["no_outline_files"])

    def test_symbols_missing_file(self):
        code, _o, stderr = run_cli(["symbols", str(self.root), "nope.py"])
        self.assertEqual(code, 2)
        self.assertIn("not in the scan", stderr)


class McpSymbolsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "proj"
        self.root.mkdir()
        make_project(self.root)
        self.out = Path(self._tmp.name) / "bundle"

    def _call(self, name, arguments):
        resp = handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}})
        return resp["result"]

    def test_schema_and_call(self):
        resp = handle_message({"jsonrpc": "2.0", "id": 1,
                               "method": "tools/list"})
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        props = tools["export_bundle"]["inputSchema"]["properties"]
        self.assertIn("symbols", props)
        result = self._call("export_bundle", {
            "path": str(self.root), "out": str(self.out),
            "symbols": ["Auth.login"]})
        self.assertFalse(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["symbols"]["files"],
                         {"auth.py": ["Auth.login"]})
        self.assertLess(payload["total_sliced_tokens"],
                        payload["total_original_tokens"])

    def test_unknown_symbol_is_error(self):
        result = self._call("export_bundle", {
            "path": str(self.root), "out": str(self.out),
            "symbols": ["logn"]})
        self.assertTrue(result["isError"])
        self.assertIn("did you mean", result["content"][0]["text"])


class ResolutionUnitTests(unittest.TestCase):
    def test_resolve_direct(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_project(root)
            result = scan(root)
            sources = {e.path: Path(e.abspath).read_text(
                encoding="utf-8", errors="replace") for e in result.files}
            symbol_map, report, _outlines = resolve_symbol_selection(
                result, "login, db.py:connect", sources)
            self.assertEqual(set(symbol_map), {"auth.py", "db.py"})
            self.assertEqual(report["ambiguous"], ["login"])
            self.assertEqual(symbol_map["db.py"], {"login", "DB.connect"})


if __name__ == "__main__":
    unittest.main()
