"""Hardening regression tests (Oct 18, 2026 improvement lane: HARDEN).

Each test pins a bug found by probing the pre-hardening code:

* source-map path sanitising let "//etc/passwd" (and UNC-style
  backslash paths) stay absolute, so a lift could write outside the
  output tree - the exact escape PLAN.md says sanitising prevents;
* duplicate-name handling in sourcemap recovery and in core's
  ``_unique`` returned an already-taken name when a literal source
  collided with a generated "-2" name, silently overwriting a file;
* the safe marshal parser leaked TypeError / UnicodeDecodeError /
  bare ValueError on hostile streams instead of SafeMarshalError,
  and accepted code objects whose name tuples / counters no real
  code object can have, which then crashed reconstruction;
* one hostile .pyc crashed the whole lift (reconstruction and the
  UTF-8 encode ran outside the per-artifact guard), losing every
  other artifact and the manifest;
* deeply nested JSON source maps leaked RecursionError through
  inspect, which only expected SourceMapError;
* the example JS boundary finder matched ``function`` inside string
  literals and comments; the example .pyc reader had no depth
  limit, rewound its position on negative sizes, and leaked
  IndexError on bad references.
"""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from ghostlift.core import LiftError, _unique, inspect_artifact, lift_path
from ghostlift.marshal_safe import SafeMarshalError, parse_marshal
from ghostlift.pyc import parse_pyc
from ghostlift.sourcemap import SourceMapError, recover_source_map, sanitise_source_path


# -- crafted marshal / .pyc builders ------------------------------------

def _s_bytes(raw: bytes) -> bytes:
    return b"s" + struct.pack("<i", len(raw)) + raw


def _z_str(text: str) -> bytes:
    raw = text.encode()
    assert len(raw) < 256
    return b"z" + bytes([len(raw)]) + raw


def _small_tuple(items) -> bytes:
    return b")" + bytes([len(items)]) + b"".join(items)


def _i32(value: int) -> bytes:
    return b"i" + struct.pack("<i", value)


def _code(names=(), localsplus=(), argcount=0, posonly=0, name="<module>"):
    fields = [
        struct.pack("<i", argcount),
        struct.pack("<i", posonly),
        struct.pack("<i", 0),
        struct.pack("<i", 0),
        struct.pack("<i", 0),
        _s_bytes(b"\x97\x00"),
        _small_tuple([b"N"]),
        _small_tuple(list(names)),
        _small_tuple(list(localsplus)),
        _s_bytes(b"\x01" * len(localsplus)),
        _z_str("mod.py"),
        _z_str(name),
        _z_str(name),
        struct.pack("<i", 1),
        _s_bytes(b""),
        _s_bytes(b""),
    ]
    return b"c" + b"".join(fields)


def _pyc(payload: bytes) -> bytes:
    # 3495 is the CPython 3.11 magic; the parser accepts every magic in
    # SUPPORTED_MAGICS regardless of the running interpreter.
    return (
        struct.pack("<H", 3495)
        + b"\r\n"
        + struct.pack("<I", 0)
        + struct.pack("<II", 0, 0)
        + payload
    )


class SanitiseTraversalTest(unittest.TestCase):
    def test_double_slash_absolute_is_rebased(self):
        path, rewritten = sanitise_source_path("//etc/passwd", 0)
        self.assertEqual(path, "etc/passwd")
        self.assertTrue(rewritten)
        self.assertFalse(path.startswith("/"))

    def test_unc_backslash_path_is_rebased(self):
        path, rewritten = sanitise_source_path("\\\\server\\share\\x.js", 0)
        self.assertEqual(path, "server/share/x.js")
        self.assertTrue(rewritten)

    def test_drive_relative_prefix_is_stripped(self):
        path, rewritten = sanitise_source_path("C:foo/bar.js", 0)
        self.assertEqual(path, "foo/bar.js")
        self.assertTrue(rewritten)

    def test_normal_relative_path_untouched(self):
        self.assertEqual(sanitise_source_path("src/a.js", 0), ("src/a.js", False))


class DuplicateCollisionTest(unittest.TestCase):
    def test_recover_outputs_are_unique(self):
        data = json.dumps(
            {
                "version": 3,
                "sources": ["x.js", "x.js", "x-2.js"],
                "sourcesContent": ["one", "two", "three"],
            }
        ).encode()
        result = recover_source_map(data)
        paths = [item.output_path for item in result.recovered]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(
            {item.output_path: item.content for item in result.recovered},
            {paths[0]: b"one", paths[1]: b"two", paths[2]: b"three"},
        )

    def test_core_unique_sequence_is_unique(self):
        used: dict = {}
        outs = [_unique(rel, used) for rel in ("a.js", "a.js", "a-2.js", "a-2.js")]
        self.assertEqual(len(outs), len(set(outs)))

    def test_lift_keeps_all_colliding_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bundle.js.map").write_text(
                json.dumps(
                    {
                        "version": 3,
                        "sources": ["x.js", "x.js", "x-2.js"],
                        "sourcesContent": ["one", "two", "three"],
                    }
                )
            )
            out = root / "out"
            manifest = lift_path(root, out)
            self.assertEqual(manifest["totals"]["files"], 3)
            paths = [entry["path"] for entry in manifest["files"]]
            self.assertEqual(len(paths), len(set(paths)))
            contents = sorted((out / "files" / p).read_text() for p in paths)
            self.assertEqual(contents, ["one", "three", "two"])


class MarshalLeakTest(unittest.TestCase):
    def test_set_of_list_is_safe_error(self):
        data = b"<" + struct.pack("<i", 1) + b"[" + struct.pack("<i", 0)
        with self.assertRaises(SafeMarshalError):
            parse_marshal(data)

    def test_frozenset_of_list_is_safe_error(self):
        data = b">" + struct.pack("<i", 1) + b"[" + struct.pack("<i", 0)
        with self.assertRaises(SafeMarshalError):
            parse_marshal(data)

    def test_float_garbage_is_safe_error(self):
        with self.assertRaises(SafeMarshalError):
            parse_marshal(b"f" + bytes([4]) + b"abcd")

    def test_string_invalid_utf8_is_safe_error(self):
        with self.assertRaises(SafeMarshalError):
            parse_marshal(b"a" + struct.pack("<i", 2) + b"\xff\xfe")


class CodeValidationTest(unittest.TestCase):
    def test_non_string_name_refused(self):
        with self.assertRaises(SafeMarshalError):
            parse_pyc(_pyc(_code(names=[_i32(42)])))

    def test_non_string_localsplus_name_refused(self):
        with self.assertRaises(SafeMarshalError):
            parse_pyc(_pyc(_code(localsplus=[_i32(7)], argcount=1)))

    def test_negative_argcount_refused(self):
        with self.assertRaises(SafeMarshalError):
            parse_pyc(_pyc(_code(argcount=-1, localsplus=[_z_str("a")])))

    def test_posonly_exceeding_argcount_refused(self):
        with self.assertRaises(SafeMarshalError):
            parse_pyc(_pyc(_code(argcount=1, posonly=2, localsplus=[_z_str("a")])))


class LiftIsolationTest(unittest.TestCase):
    def test_hostile_pyc_does_not_lose_other_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.pyc").write_bytes(_pyc(_code(names=[_i32(42)])))
            (root / "good.js.map").write_text(
                json.dumps(
                    {"version": 3, "sources": ["ok.js"], "sourcesContent": ["hello"]}
                )
            )
            out = root / "out"
            manifest = lift_path(root, out)
            self.assertEqual(manifest["totals"]["files"], 1)
            self.assertEqual((out / "files" / "ok.js").read_text(), "hello")
            self.assertTrue((out / "manifest.json").is_file())
            failure_names = [Path(f["artifact"]).name for f in manifest["failures"]]
            self.assertIn("bad.pyc", failure_names)

    def test_unencodable_pyc_is_recorded_failure_not_crash(self):
        # A name carrying a lone surrogate parses (surrogatepass) but
        # cannot be encoded as UTF-8 lifted source: the lift must
        # record the failure, not die on UnicodeEncodeError.
        surrogate = "\udcff".encode("utf-8", "surrogatepass")
        bad_name = b"a" + struct.pack("<i", len(surrogate)) + surrogate
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "surr.pyc").write_bytes(_pyc(_code(names=[bad_name])))
            (root / "good.js.map").write_text(
                json.dumps(
                    {"version": 3, "sources": ["ok.js"], "sourcesContent": ["hi"]}
                )
            )
            manifest = lift_path(root, root / "out")
            self.assertEqual(manifest["totals"]["files"], 1)
            failure_names = [Path(f["artifact"]).name for f in manifest["failures"]]
            self.assertIn("surr.pyc", failure_names)

    def test_nul_in_source_path_is_recorded_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bundle.js.map").write_text(
                json.dumps(
                    {
                        "version": 3,
                        "sources": ["a\x00b.js", "ok.js"],
                        "sourcesContent": ["x", "y"],
                    }
                )
            )
            out = root / "out"
            manifest = lift_path(root, out)
            self.assertEqual(manifest["totals"]["files"], 1)
            self.assertEqual((out / "files" / "ok.js").read_text(), "y")
            self.assertEqual(manifest["totals"]["failures"], 1)

    def test_out_path_that_is_a_file_is_lift_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "a.js.map"
            source.write_text(
                json.dumps(
                    {"version": 3, "sources": ["a.js"], "sourcesContent": ["x"]}
                )
            )
            occupied = root / "occupied"
            occupied.write_text("a file, not a folder")
            with self.assertRaises(LiftError):
                lift_path(source, occupied)

    def test_deeply_nested_map_is_error_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep.js.map"
            path.write_text(
                '{"version":3,"sources":[],"x":' + "[" * 20000 + "]" * 20000 + "}"
            )
            with self.assertRaises(SourceMapError):
                recover_source_map(path.read_bytes())
            info = inspect_artifact(path)
            self.assertFalse(info["liftable"])
            self.assertIn("error", info)


class JsBoundaryMaskTest(unittest.TestCase):
    def test_function_inside_string_is_not_a_boundary(self):
        from js_lift_demo import find_function_boundaries

        source = 'var s="function fake(a){return 1}";function real(b){return 2}'
        self.assertEqual(find_function_boundaries(source), ["real"])

    def test_function_inside_comments_is_not_a_boundary(self):
        from js_lift_demo import find_function_boundaries

        source = "// function commented() {}\n/* function blocked() {} */\nfunction live(){}"
        self.assertEqual(find_function_boundaries(source), ["live"])

    def test_arrow_inside_string_is_not_a_boundary(self):
        from js_lift_demo import find_function_boundaries

        source = "var t='const ghost = () => 1'; const real2 = () => 2;"
        self.assertEqual(find_function_boundaries(source), ["real2"])


class PycOutlineReaderTest(unittest.TestCase):
    def test_negative_ref_is_value_error(self):
        from pyc_outline_demo import _Reader

        reader = _Reader(b"N" + b"r" + struct.pack("<i", -1))
        reader.read_object()
        with self.assertRaises(ValueError):
            reader.read_object()

    def test_out_of_range_ref_is_value_error(self):
        from pyc_outline_demo import _Reader

        with self.assertRaises(ValueError):
            _Reader(b"r" + struct.pack("<i", 99)).read_object()

    def test_ref_to_unfinished_object_is_value_error(self):
        from pyc_outline_demo import _Reader

        flagged_tuple = bytes([0x80 | ord("(")]) + struct.pack("<i", 1)
        with self.assertRaises(ValueError):
            _Reader(flagged_tuple + b"r" + struct.pack("<i", 0)).read_object()

    def test_negative_sizes_and_counts_are_value_errors(self):
        from pyc_outline_demo import _Reader

        for data in (
            b"s" + struct.pack("<i", -1) + b"abcdef",
            b"(" + struct.pack("<i", -3),
            b"[" + struct.pack("<i", -2),
        ):
            with self.assertRaises(ValueError, msg=f"stream {data!r}"):
                _Reader(data).read_object()

    def test_deep_nesting_is_value_error_not_recursion_error(self):
        from pyc_outline_demo import _Reader

        data = b"N"
        for _ in range(150):
            data = b"(" + struct.pack("<i", 1) + data
        with self.assertRaises(ValueError):
            _Reader(data).read_object()


if __name__ == "__main__":
    unittest.main()
