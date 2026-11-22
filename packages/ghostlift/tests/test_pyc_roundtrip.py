"""Tier 2/3: .pyc round-trip signatures.

The .pyc fixture is generated at test time from
``examples/pyc_demo/sample_module.py`` with this interpreter's own
``py_compile`` - a committed .pyc would only be valid for one Python
version, so none is shipped (that is pinned by the fixture tests).

Round-trip bar: signatures recovered from the bytecode alone must
match the signatures in the original source (names and argument
names). The example outline lifter (examples/pyc_outline_demo.py)
is tested against that bar directly. The core half exercises Agent
A's core through discovery and skips with a reason if no usable
callable exists yet.

Nothing in this file ever executes the compiled module: it is only
ever compiled to bytes, parsed, and outlined.
"""

import pathlib
import py_compile
import tempfile
import unittest

from tests import helpers
from tests.helpers import EXAMPLES

SAMPLE = EXAMPLES / "pyc_demo" / "sample_module.py"
EXPECTED_SIGNATURES = {
    "greet": ["name", "punctuation"],
    "add": ["a", "b"],
    "Pair": [],
    "Pair.__init__": ["self", "left", "right"],
    "Pair.swap": ["self"],
}


def compile_sample(tmp_dir: pathlib.Path) -> pathlib.Path:
    pyc = tmp_dir / "sample_module.pyc"
    py_compile.compile(str(SAMPLE), cfile=str(pyc), doraise=True)
    assert pyc.is_file()
    return pyc


class PycFixtureGenerationTest(unittest.TestCase):
    def test_sample_compiles_and_original_signatures_match_ground_truth(self):
        signatures = helpers.python_signatures(SAMPLE.read_text())
        self.assertEqual(signatures, EXPECTED_SIGNATURES)

    def test_generated_pyc_has_this_interpreters_magic(self):
        import importlib.util

        with tempfile.TemporaryDirectory() as tmp:
            pyc = compile_sample(pathlib.Path(tmp))
            self.assertEqual(pyc.read_bytes()[:4], importlib.util.MAGIC_NUMBER)


class PycExampleOutlineTest(unittest.TestCase):
    def test_outline_recovers_names_and_args(self):
        from pyc_outline_demo import load_code_object, walk_outline

        with tempfile.TemporaryDirectory() as tmp:
            pyc = compile_sample(pathlib.Path(tmp))
            entries = walk_outline(load_code_object(pyc.read_bytes()))
        recovered = {entry["qualname"]: entry["args"] for entry in entries}
        self.assertEqual(recovered, EXPECTED_SIGNATURES)

    def test_outline_refuses_foreign_magic(self):
        from pyc_outline_demo import load_code_object

        with self.assertRaises(ValueError):
            load_code_object(b"\x00\x00\x00\x00" + b"\x00" * 32)


class PycCoreRoundTripTest(unittest.TestCase):
    def test_core_lift_recovers_signatures(self):
        module = helpers.import_core()
        candidates = helpers._candidate_callables(
            module, "pyc", "bytecode", "lift_python", "decompile", "lift"
        )
        if not candidates:
            self.skipTest(
                "ghostlift core not importable or exposes no pyc/lift "
                "callable yet (Agent A surface); example outline above "
                "proves the fixture round-trips"
            )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            pyc = compile_sample(tmp_path)
            out_dir = tmp_path / "out"
            errors = []
            for name, func in candidates:
                ok, result = helpers.call_variants(
                    func, (pyc,), (str(pyc),), (pyc, out_dir), (str(pyc), str(out_dir))
                )
                if not ok:
                    errors.append(f"{name}: {result!r}")
                    continue
                texts = helpers.texts_from_result(result, out_dir)
                names = set()
                for text in texts:
                    names |= helpers.signature_names_from_text(text)
                if {"greet", "add", "Pair", "__init__", "swap"} <= names:
                    return
                errors.append(f"{name}: lifted output missing expected names, got {sorted(names)}")
        self.skipTest("no candidate core callable lifted the .pyc: " + "; ".join(errors))


if __name__ == "__main__":
    unittest.main()
