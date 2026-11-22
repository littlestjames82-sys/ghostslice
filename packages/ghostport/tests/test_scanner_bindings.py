"""Binding-aware scanning: existing patterns in their other idiomatic forms.

Before this change the scanner matched literal spellings only, so a
pattern missed when the code reached the same removed API through an
import alias (``import ssl as s; s.wrap_socket``), through the module
(``import collections; collections.Mapping``), or through a direct
from-import that was never used again (``from inspect import
getargspec``). These tests pin the widened coverage AND the
look-alikes that must stay clean (``collections.abc.Mapping``,
``context.wrap_socket``, ``getfullargspec``, modern unittest names).

Planner-only discipline is unchanged: scanning never writes to the
scanned project (also pinned by test_scan_patterns.py) and no hit here
rewrites anything.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import CORE_AVAILABLE, PACK_ID, SKIP_CORE, parse_json_output, run_cli  # noqa: E402

SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _hits(source: str) -> list[tuple[str, int]]:
    """Scan one in-memory source string; return sorted (pattern_id, line)."""
    from ghostport.patterns import load_pack
    from ghostport.scanner import scan_file

    pack = load_pack(PACK_ID)
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "only.py"
        path.write_text(source, encoding="utf-8")
        hits, err = scan_file(path, pack)
    assert err is None, err
    return sorted((h["pattern_id"], h["line"]) for h in hits)


def _ids(source: str) -> set[str]:
    return {pid for pid, _ in _hits(source)}


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestBindingResolution(unittest.TestCase):
    def test_import_bindings_and_resolve(self):
        import ast

        from ghostport.scanner import import_bindings, resolve_dotted

        tree = ast.parse(
            "import collections.abc as abc\n"
            "import asyncio as aio\n"
            "import collections\n"
            "from inspect import getargspec as gas\n"
        )
        bindings = import_bindings(tree)
        self.assertEqual(bindings["abc"], "collections.abc")
        self.assertEqual(bindings["aio"], "asyncio")
        self.assertEqual(bindings["collections"], "collections")
        self.assertEqual(bindings["gas"], "inspect.getargspec")
        self.assertEqual(resolve_dotted("abc.Mapping", bindings), "collections.abc.Mapping")
        self.assertEqual(resolve_dotted("aio.coroutine", bindings), "asyncio.coroutine")
        self.assertEqual(resolve_dotted("other.thing", bindings), "other.thing")

    def test_relative_imports_are_not_bound_to_stdlib(self):
        import ast

        from ghostport.scanner import import_bindings

        tree = ast.parse("from . import getargspec\nfrom .inspect import getargspec\n")
        self.assertEqual(import_bindings(tree), {})


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestModuleAttributeForms(unittest.TestCase):
    def test_collections_abc_via_module_attribute(self):
        hits = _hits("import collections\n\n\nAlias = collections.Mapping\n")
        self.assertIn(("PYUP001", 4), hits)

    def test_collections_abc_via_aliased_module(self):
        self.assertIn("PYUP001", _ids("import collections as col\n\nx = col.Sequence\n"))

    def test_collections_abc_modern_location_stays_clean(self):
        self.assertNotIn("PYUP001", _ids("import collections.abc\n\nx = collections.abc.Mapping\n"))
        self.assertNotIn("PYUP001", _ids("import collections.abc as abc\n\nx = abc.Mapping\n"))

    def test_ssl_via_aliased_module(self):
        hits = _hits("import ssl as s\n\n\ndef w(sock):\n    return s.wrap_socket(sock)\n")
        self.assertIn(("PYUP009", 5), hits)

    def test_ssl_unrelated_receiver_stays_clean(self):
        src = (
            "import ssl\n\n\ndef wrap(sock, host):\n"
            "    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)\n"
            "    return context.wrap_socket(sock, server_hostname=host)\n"
        )
        self.assertNotIn("PYUP009", _ids(src))

    def test_asyncio_coroutine_via_aliased_module(self):
        src = "import asyncio as aio\n\n\n@aio.coroutine\ndef fetch():\n    yield from []\n"
        self.assertIn("PYUP002", _ids(src))

    def test_bare_collections_import_alone_is_not_a_hit(self):
        # `import collections` without using a removed ABC is modern code.
        self.assertNotIn("PYUP001", _ids("import collections\n\nprint(collections)\n"))


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestFromImportForms(unittest.TestCase):
    def test_unused_from_import_of_removed_name_is_a_hit(self):
        self.assertIn(("PYUP003", 1), _hits("from inspect import getargspec\n"))
        self.assertIn(("PYUP007", 1), _hits("from threading import currentThread\n"))
        self.assertIn(("PYUP011", 1), _hits("from locale import getdefaultlocale\n"))
        self.assertIn(("PYUP009", 1), _hits("from ssl import wrap_socket\n"))
        self.assertIn(("PYUP006", 1), _hits("from configparser import SafeConfigParser\n"))

    def test_aliased_from_import_hits_import_and_use_lines(self):
        src = "from inspect import getargspec as gas\n\n\ndef d(fn):\n    return gas(fn)\n"
        hits = _hits(src)
        self.assertIn(("PYUP003", 1), hits)
        self.assertIn(("PYUP003", 5), hits)

    def test_aliased_from_import_of_abc_hits_use_line(self):
        src = "from collections import Mapping as M\n\n\ndef f(o):\n    return isinstance(o, M)\n"
        hits = _hits(src)
        self.assertIn(("PYUP001", 1), hits)
        self.assertIn(("PYUP001", 5), hits)

    def test_modern_from_imports_stay_clean(self):
        self.assertNotIn("PYUP003", _ids("from inspect import getfullargspec\n"))
        self.assertNotIn("PYUP001", _ids("from collections.abc import Mapping\n"))
        self.assertNotIn("PYUP007", _ids("from threading import current_thread\n"))


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestUnittestAliasCompletion(unittest.TestCase):
    """PYUP008's description always named aliases its matcher lacked."""

    def _case(self, call: str) -> str:
        return (
            "import unittest\n\n\nclass T(unittest.TestCase):\n"
            f"    def test_x(self):\n        self.{call}\n"
        )

    def test_previously_missing_aliases_are_hit(self):
        for call in (
            "assertNotEquals(1, 1)",
            "assertAlmostEquals(1.0, 1.0)",
            "assertNotAlmostEquals(1.0, 2.0)",
            "failIfEqual(1, 2)",
            "failIfAlmostEqual(1.0, 2.0)",
            "failUnlessRaises(ValueError)",
            "assertRegexpMatches('x', 'x')",
            "assertRaisesRegexp(ValueError, 'x')",
        ):
            with self.subTest(call=call):
                self.assertIn("PYUP008", _ids(self._case(call)))

    def test_modern_assert_names_stay_clean(self):
        for call in (
            "assertNotEqual(1, 2)",
            "assertAlmostEqual(1.0, 1.0)",
            "assertRegex('x', 'x')",
            "assertRaises(ValueError)",
        ):
            with self.subTest(call=call):
                self.assertNotIn("PYUP008", _ids(self._case(call)))


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestBindingAwareCli(unittest.TestCase):
    def test_scan_json_reports_aliased_hit_with_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp)
            (proj / "legacy.py").write_text(
                "import ssl as _ssl\n\n\ndef w(sock):\n    return _ssl.wrap_socket(sock)\n",
                encoding="utf-8",
            )
            proc = run_cli(["scan", str(proj), "--pack", PACK_ID, "--json"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = parse_json_output(proc)
            hits = [h for h in result["hits"] if h["pattern_id"] == "PYUP009"]
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["file"], "legacy.py")
            self.assertEqual(hits[0]["line"], 5)


if __name__ == "__main__":
    unittest.main()
