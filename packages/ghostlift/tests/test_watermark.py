"""Watermark presence: every lifted file must say what it is.

Contract (README.md): lifted output carries a watermark naming
GhostLift, the fact it was lifted, and its tier (tier=1/2/3), in a
comment appropriate to the output language, and a manifest entry if
the tool writes a manifest. A lifted file with no watermark is a
release-blocking bug, because downstream tools (GhostSlice and the
rest of the suite) must never mistake a reconstruction for original
source.

These tests check:
* the example lifters watermark their output with the right tier;
* the watermark helpers themselves (a text with no ghostlift/tier
  tokens does not pass);
* any core-produced output the discovery layer can obtain also
  carries a watermark with a tier (skips with a reason if the core
  is not available yet);
* README.md documents the watermark, which is part of the contract
  a user relies on.
"""

import unittest

from tests import helpers
from tests.helpers import EXAMPLES, FIXTURES, ROOT


class WatermarkHelperTest(unittest.TestCase):
    def test_plain_source_has_no_watermark(self):
        self.assertFalse(helpers.has_watermark("function add(a, b) { return a + b; }"))
        self.assertIsNone(helpers.watermark_tier("function add(a, b) { return a + b; }"))

    def test_tokens_detected(self):
        text = "# ghostlift: lifted tier=2 source=pyc reconstruction=structured"
        self.assertTrue(helpers.has_watermark(text))
        self.assertEqual(helpers.watermark_tier(text), 2)


class ExampleWatermarkTest(unittest.TestCase):
    def test_js_example_output_is_watermarked_tier_2(self):
        from js_lift_demo import lift_minified_js

        out = lift_minified_js((FIXTURES / "minified" / "app.min.js").read_text())
        self.assertTrue(helpers.has_watermark(out))
        self.assertEqual(helpers.watermark_tier(out), 2)
        self.assertIn("lifted", out.lower())

    def test_pyc_outline_example_output_is_watermarked_tier_3(self):
        import py_compile
        import tempfile
        from pathlib import Path

        from pyc_outline_demo import load_code_object, outline_pseudo_source

        with tempfile.TemporaryDirectory() as tmp:
            pyc = Path(tmp) / "sample_module.pyc"
            py_compile.compile(
                str(EXAMPLES / "pyc_demo" / "sample_module.py"),
                cfile=str(pyc),
                doraise=True,
            )
            out = outline_pseudo_source(load_code_object(pyc.read_bytes()))
        self.assertTrue(helpers.has_watermark(out))
        self.assertEqual(helpers.watermark_tier(out), 3)
        self.assertIn("lifted", out.lower())


class ReadmeWatermarkContractTest(unittest.TestCase):
    def test_readme_documents_watermark_and_tiers(self):
        readme = (ROOT / "README.md").read_text().lower()
        self.assertIn("watermark", readme)
        for tier_word in ("tier 1", "tier 2", "tier 3"):
            self.assertIn(tier_word, readme)


class CoreWatermarkTest(unittest.TestCase):
    def test_core_manifest_marks_every_file_lifted_with_tier(self):
        # The core's primary watermark is the manifest: every entry
        # lifted with its tier, plus the manifest note. Checked via
        # the real CLI on the source-map fixture.
        import json
        import pathlib
        import tempfile

        from tests.test_cli_contract import cli_available, run_cli

        if not cli_available():
            self.skipTest("ghostlift core CLI not available yet (Agent A surface)")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out"
            result = run_cli("lift", FIXTURES / "sourcemap" / "bundle.js.map", "-o", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest_text = (out / "manifest.json").read_text()
            manifest = json.loads(manifest_text)
        self.assertTrue(helpers.has_watermark(manifest_text))
        self.assertIn("lifted", manifest_text.lower())
        self.assertTrue(manifest["files"])
        for entry in manifest["files"]:
            self.assertTrue(entry["lifted"])
            self.assertIn(entry["tier"], (1, 2, 3))


if __name__ == "__main__":
    unittest.main()
