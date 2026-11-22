"""Static validation of the GhostLift fixtures themselves.

These tests do not need the GhostLift core. They prove each fixture
actually has the property the tier tests rely on, so a later core
failure cannot be blamed on a broken fixture:

* the source map's ``sourcesContent`` is byte-for-byte the original
  files stored next to it (Tier 1 ground truth);
* the minified JS really is minified (one line, no indentation) and
  names the same functions as its readable counterpart (Tier 2);
* the .pyc sample module parses and has the signatures the
  round-trip test expects (Tier 2/3 ground truth).
"""

import ast
import json
import pathlib
import unittest

from tests.helpers import EXAMPLES, FIXTURES


class SourceMapFixtureTest(unittest.TestCase):
    def setUp(self):
        self.map_path = FIXTURES / "sourcemap" / "bundle.js.map"
        self.data = json.loads(self.map_path.read_text())

    def test_map_is_version_3_with_sources_content(self):
        self.assertEqual(self.data["version"], 3)
        self.assertEqual(self.data["sources"], ["src/greeting.js", "src/math.js"])
        self.assertEqual(len(self.data["sourcesContent"]), 2)

    def test_sources_content_matches_originals_byte_for_byte(self):
        for source, content in zip(self.data["sources"], self.data["sourcesContent"]):
            original = (FIXTURES / "sourcemap" / "originals" / source).read_text()
            self.assertEqual(content, original, f"sourcesContent for {source} differs")

    def test_bundle_references_the_map(self):
        bundle = (FIXTURES / "sourcemap" / "bundle.js").read_text()
        self.assertIn("sourceMappingURL=bundle.js.map", bundle)

    def test_examples_copy_matches_fixture(self):
        example_map = json.loads((EXAMPLES / "sourcemap_demo" / "bundle.js.map").read_text())
        self.assertEqual(example_map["sourcesContent"], self.data["sourcesContent"])


class MinifiedFixtureTest(unittest.TestCase):
    def test_minified_is_a_single_line(self):
        text = (FIXTURES / "minified" / "app.min.js").read_text()
        self.assertEqual(len(text.strip().splitlines()), 1)

    def test_minified_and_readable_name_the_same_functions(self):
        import re

        pattern = r"\bfunction\s+([A-Za-z_$][\w$]*)"
        minified = (FIXTURES / "minified" / "app.min.js").read_text()
        readable = (FIXTURES / "minified" / "app.js").read_text()
        self.assertEqual(
            sorted(re.findall(pattern, minified)),
            sorted(re.findall(pattern, readable)),
        )
        for text in (minified, readable):
            self.assertIn("doubleIt", text)


class PycSampleFixtureTest(unittest.TestCase):
    def test_sample_module_signatures(self):
        source = (EXAMPLES / "pyc_demo" / "sample_module.py").read_text()
        tree = ast.parse(source)
        funcs = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
        self.assertEqual(funcs, {"greet", "add", "__init__", "swap"})
        self.assertEqual(classes, {"Pair"})

    def test_no_shipped_pyc_fixture(self):
        # .pyc fixtures are generated at test time (they are tied to
        # one interpreter version), never committed.
        shipped = list(pathlib.Path(FIXTURES).rglob("*.pyc"))
        self.assertEqual(shipped, [])


if __name__ == "__main__":
    unittest.main()
