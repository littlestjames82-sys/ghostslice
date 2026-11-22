"""Tier 2 core: minified-JS lift in the GhostLift core (jslift).

The JS beautify originally shipped only as the example lifter under
examples/. The core now lifts .js artifacts itself: inspect reports
them Tier 2 / liftable with function boundaries, and lift writes a
watermarked, beautified file plus a Tier 2 manifest entry.

Covered here beyond the example's bar:
* token preservation on regex literals containing braces/semicolons;
* division is not mistaken for a regex start (and vice versa);
* for(;;) header semicolons do not split the header line;
* function-like text inside strings is not a function boundary;
* undecodable JS is a recorded failure in inspect/lift, never a crash
  and never executed.
"""

import json
import re
import tempfile
import unittest
from pathlib import Path

from ghostlift.core import inspect_artifact, lift_path
from ghostlift.jslift import beautify_js, find_function_boundaries, lift_javascript
from tests import helpers
from tests.helpers import FIXTURES
from tests.test_cli_contract import run_cli

MINIFIED = FIXTURES / "minified" / "app.min.js"
EXPECTED = ["clamp", "describeScore", "doubleIt"]


def strip_ws(text: str) -> str:
    return re.sub(r"\s+", "", text)


class CoreJsBeautifyTest(unittest.TestCase):
    def test_fixture_boundaries_and_token_preservation(self):
        source = MINIFIED.read_text()
        self.assertEqual(find_function_boundaries(source), EXPECTED)
        self.assertEqual(strip_ws(beautify_js(source)), strip_ws(source))

    def test_regex_literal_braces_and_semicolons_stay_in_literal(self):
        source = r"function f(){return /a{2};b/.test(x)}function g(){return 1}"
        out = beautify_js(source)
        self.assertEqual(strip_ws(out), strip_ws(source))
        self.assertEqual(find_function_boundaries(source), ["f", "g"])
        self.assertIn(r"/a{2};b/", out)

    def test_division_is_not_a_regex_start(self):
        source = "function g(a,b){return a/b}function d(x){return x/2/1}"
        out = beautify_js(source)
        self.assertEqual(strip_ws(out), strip_ws(source))
        self.assertEqual(find_function_boundaries(source), ["g", "d"])
        # The closing brace still lands on its own line: the slash was
        # not swallowed into a phantom regex chunk.
        self.assertIn("return a/b\n}", out)

    def test_regex_after_return_keyword_is_a_regex(self):
        source = r"function e(s){return /^\d+$/.test(s)}"
        out = beautify_js(source)
        self.assertEqual(strip_ws(out), strip_ws(source))
        self.assertIn(r"/^\d+$/", out)

    def test_for_header_semicolons_do_not_split_line(self):
        source = "function h(){for(let i=0;i<3;i++){console.log(i)}return 1}"
        out = beautify_js(source)
        header = [line for line in out.splitlines() if "for(" in line]
        self.assertEqual(len(header), 1)
        self.assertIn("i=0;i<3;i++", strip_ws(header[0]))

    def test_function_text_inside_string_or_comment_is_not_a_boundary(self):
        source = (
            'const s="function fake(){}";/* function alsoFake(){} */'
            "function real(){return 1}"
        )
        self.assertEqual(find_function_boundaries(source), ["real"])

    def test_lift_javascript_is_watermarked_tier2_and_preserves_tokens(self):
        source = MINIFIED.read_text()
        out = lift_javascript(source, "app.min.js")
        self.assertTrue(helpers.has_watermark(out))
        self.assertEqual(helpers.watermark_tier(out), 2)
        body = "\n".join(out.splitlines()[2:])
        self.assertEqual(strip_ws(body), strip_ws(source))


class CoreJsInspectLiftTest(unittest.TestCase):
    def test_inspect_reports_liftable_with_boundaries(self):
        info = inspect_artifact(MINIFIED)
        self.assertEqual(info["kind"], "javascript")
        self.assertEqual(info["tier"], 2)
        self.assertTrue(info["liftable"])
        self.assertFalse(info["executable_by_ghostlift"])
        self.assertEqual(info["function_boundaries"], EXPECTED)

    def test_lift_path_writes_watermarked_file_and_tier2_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            manifest = lift_path(MINIFIED, out_dir)
            self.assertEqual(manifest["totals"]["files"], 1)
            self.assertEqual(manifest["totals"]["failures"], 0)
            entry = manifest["files"][0]
            self.assertTrue(entry["lifted"])
            self.assertEqual(entry["tier"], 2)
            self.assertEqual(entry["recovery"], "structured")
            self.assertEqual(entry["function_boundaries"], EXPECTED)
            text = (out_dir / "files" / entry["path"]).read_text()
            self.assertEqual(helpers.watermark_tier(text), 2)
            self.assertGreater(len(text.splitlines()), 10)

    def test_lift_directory_picks_up_js_alongside_other_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "app.min.js").write_bytes(MINIFIED.read_bytes())
            (tmp_path / "bundle.js.map").write_bytes(
                (FIXTURES / "sourcemap" / "bundle.js.map").read_bytes()
            )
            manifest = lift_path(tmp_path, tmp_path / "out")
            tiers = sorted(e["tier"] for e in manifest["files"])
            self.assertEqual(tiers, [1, 1, 2])

    def test_undecodable_js_is_refused_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.js"
            bad.write_bytes(b"\xff\xfe\x00not utf-8 javascript")
            info = inspect_artifact(bad)
            self.assertFalse(info["liftable"])
            self.assertIn("error", info)
            manifest = lift_path(bad, Path(tmp) / "out")
            self.assertEqual(manifest["totals"]["files"], 0)
            self.assertEqual(manifest["totals"]["failures"], 1)

    def test_cli_lift_js_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            result = run_cli("lift", MINIFIED, "-o", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["totals"]["files"], 1)
            self.assertEqual(manifest["files"][0]["tier"], 2)


if __name__ == "__main__":
    unittest.main()
