"""v0.10 (G5): token estimator calibration + the carried P0 fix.

Calibration: per-language-family factors in tokens.py bring the raw
BPE-like split's implied chars/token on the golden corpora
(tests/fixtures/calibration/) onto published-anchor target rates.
The characterization tests measure the corpora — they do not compare
against any real tokenizer (none exists stdlib-side), and the factor
table's evidence basis is documented in tokens.py.

P0 (parent finding, carried from G4): lines rewritten by the config
slicer's scanner backstop must keep their original indentation —
in YAML the indent is the structure. Secrets are assembled from
fragments so this file stays clean under the repo's own guard.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.calibration import calibrate_project
from ghostslice.cli import main as cli_main
from ghostslice.configslice import slice_json, slice_yaml
from ghostslice.exporter import build_bundle, validate_bundle
from ghostslice.profile import load_profile
from ghostslice.scanner import scan
from ghostslice.tokens import (FAMILY_CALIBRATION, FAMILY_FACTORS, METHOD,
                               estimate_tokens, estimate_tokens_raw,
                               family_for, looks_minified)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "calibration"

# Scanner-shaped values, assembled from fragments at runtime.
AKIA = "AK" + "IA" + "J7K9" + "Q2XZ" + "4B8N" + "6M3P"
URL_WITH_PW = "postgres://svc:" + "hunt" + "er2pw" + "@db.internal:5432/app"

# sample file -> (scanner language, expected family)
CORPUS = {
    "python.sample": ("python", "python"),
    "typescript.sample": ("typescript", "ts-js"),
    "go.sample": ("go", "go"),
    "rust.sample": ("rust", "rust"),
    "c.sample": ("c", "c-family"),
    "markdown.sample": ("markdown", "prose"),
    "json.sample": ("json", "json-data"),
    "minified.sample": ("javascript", "minified-js"),
}


def _line_for(text: str, key: str) -> str:
    for line in text.splitlines():
        if key in line:
            return line
    raise AssertionError(f"no line containing {key!r} in:\n{text}")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


class TestP0BackstopIndent(unittest.TestCase):
    """P0: backstop rewrites preserve the original line's indentation."""

    def test_backstop_only_value_nested_keeps_indent(self):
        # access_id is NOT a sensitive key name and the raw split
        # value rule keeps an AKIA-shaped token (no lowercase, so
        # not "random-looking"): only the scanner backstop catches
        # it. The rewritten line must stay at its nested indent.
        src = ("database:\n"
               "  host: db.internal\n"
               f"  access_id: {AKIA}\n"
               "  port: 5432\n")
        out = slice_yaml(src, "structure", "cfg.yaml")
        self.assertNotIn(AKIA, out)
        line = _line_for(out, "access_id")
        self.assertEqual(_indent(line), 2)
        self.assertIn('"…"', line)

    def test_backstop_only_value_deep_nest_keeps_indent(self):
        src = ("a:\n  b:\n    c:\n"
               f"      access_id: {AKIA}\n")
        out = slice_yaml(src, "structure", "cfg.yaml")
        self.assertNotIn(AKIA, out)
        self.assertEqual(_indent(_line_for(out, "access_id")), 6)

    def test_nested_non_sensitive_placeholder_keeps_indent(self):
        # URL-with-password under a non-sensitive key: placeholdered
        # by the value rule; the line must stay nested too.
        src = ("database:\n"
               f"  primary: {URL_WITH_PW}\n"
               "  host: db.internal\n")
        out = slice_yaml(src, "structure", "cfg.yaml")
        self.assertNotIn("er2pw", out)
        self.assertEqual(_indent(_line_for(out, "primary")), 2)

    def test_nested_sensitive_key_placeholders_keep_indent(self):
        pw = "correct" + "horse" + "batterystaple"
        tok = "tok" + "_live_" + "9f8e7d6c5b4a"
        src = ("database:\n"
               "  user: svc_app\n"
               f"  password: {pw}\n"
               f"  api_token: {tok}\n")
        out = slice_yaml(src, "structure", "cfg.yaml")
        self.assertNotIn(pw, out)
        self.assertNotIn(tok, out)
        self.assertEqual(_indent(_line_for(out, "password")), 2)
        self.assertEqual(_indent(_line_for(out, "api_token")), 2)

    def test_backstop_sequence_scalar_keeps_indent_and_dash(self):
        src = f"ids:\n  - {AKIA}\n  - other\n"
        out = slice_yaml(src, "structure", "cfg.yaml")
        self.assertNotIn(AKIA, out)
        line = _line_for(out, '"…"')
        self.assertEqual(_indent(line), 2)
        self.assertTrue(line.lstrip().startswith("- "))

    def test_backstop_json_nested_keeps_indent(self):
        src = '{"database": {"host": "db.internal", "access_id": "' + AKIA + '"}}'
        out = slice_json(src, "structure", "c.json")
        self.assertNotIn(AKIA, out)
        self.assertEqual(_indent(_line_for(out, "access_id")), 4)


class TestCalibrationUnits(unittest.TestCase):
    def test_no_language_is_raw_v1(self):
        # Backward compatibility for direct callers (test_tokens.py
        # pins these values): no language -> factor 1.0.
        self.assertEqual(estimate_tokens("hello"), 2)
        self.assertEqual(estimate_tokens("abcdefghij"), 3)
        self.assertEqual(estimate_tokens("x = 1;"), 4)
        text = "def foo(x):\n    return x + 1\n"
        self.assertEqual(estimate_tokens(text), estimate_tokens_raw(text))

    def test_family_mapping(self):
        self.assertEqual(family_for("python"), "python")
        self.assertEqual(family_for("typescript"), "ts-js")
        self.assertEqual(family_for("cpp"), "c-family")
        self.assertEqual(family_for("ruby"), "c-family")
        self.assertEqual(family_for("markdown"), "prose")
        self.assertEqual(family_for("json"), "json-data")
        self.assertEqual(family_for("yaml"), "json-data")
        self.assertEqual(family_for("sql"), "other")
        self.assertEqual(family_for("text"), "other")
        self.assertEqual(family_for(None), "other")

    def test_calibrated_is_raw_times_factor(self):
        text = (FIXTURES / "python.sample").read_text(encoding="utf-8")
        raw = estimate_tokens_raw(text)
        expected = int(raw * FAMILY_FACTORS["python"] + 0.5)
        self.assertEqual(estimate_tokens(text, "python"), expected)
        self.assertLess(estimate_tokens(text, "python"), raw)

    def test_all_factors_at_most_one(self):
        # v0.10 calibration only lowers the raw split's over-count;
        # a factor > 1 would need its own evidence and review.
        for fam, fac in FAMILY_FACTORS.items():
            self.assertLessEqual(fac, 1.0, fam)

    def test_minified_detection(self):
        mini = (FIXTURES / "minified.sample").read_text(encoding="utf-8")
        readable = (FIXTURES / "typescript.sample").read_text(encoding="utf-8")
        self.assertTrue(looks_minified(mini))
        self.assertFalse(looks_minified(readable))
        self.assertEqual(family_for("javascript", mini), "minified-js")
        self.assertEqual(family_for("typescript", readable), "ts-js")
        short = "x" * 300  # below the 400-char size floor
        self.assertFalse(looks_minified(short))


class TestCorpusCharacterization(unittest.TestCase):
    def test_corpus_lands_on_target_rates(self):
        for name, (language, family) in CORPUS.items():
            path = FIXTURES / name
            self.assertTrue(path.is_file(), f"missing corpus sample {name}")
            text = path.read_text(encoding="utf-8")
            self.assertGreater(len(text), 400, name)
            self.assertEqual(family_for(language, text), family, name)
            factor, target = FAMILY_CALIBRATION[family]
            self.assertGreater(target, 0, name)
            cal = estimate_tokens(text, language)
            implied = len(text) / cal
            self.assertAlmostEqual(implied / target, 1.0, delta=0.12,
                                   msg=f"{name}: implied {implied:.2f} vs target {target}")
            # The raw split over-counts every calibrated family.
            raw = estimate_tokens_raw(text)
            self.assertGreater(raw, cal, name)


# The v1 (raw split) implied chars/token per family, as recorded in
# the evidence table in tokens.py's module docstring. Pinned here so
# an edit to a corpus sample that changes the evidence forces the
# docstring (and a factor review) to be updated with it.
DOCUMENTED_V1_IMPLIED = {
    "python": 3.10, "ts-js": 2.63, "go": 2.48, "rust": 2.93,
    "c-family": 2.86, "prose": 3.42, "json-data": 2.84,
    "minified-js": 2.02,
}


class TestCorpusEvidencePin(unittest.TestCase):
    def test_raw_rates_match_documented_table(self):
        for name, (language, family) in CORPUS.items():
            text = (FIXTURES / name).read_text(encoding="utf-8")
            implied = len(text) / estimate_tokens_raw(text)
            self.assertAlmostEqual(implied / DOCUMENTED_V1_IMPLIED[family], 1.0,
                                   delta=0.05,
                                   msg=f"{name}: raw implied {implied:.2f} drifted from "
                                       f"the documented {DOCUMENTED_V1_IMPLIED[family]}")


class TestCalibrateReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "app.py").write_text(
            (FIXTURES / "python.sample").read_text(encoding="utf-8"))
        (self.root / "notes.md").write_text(
            (FIXTURES / "markdown.sample").read_text(encoding="utf-8"))
        (self.root / "bundle.js").write_text(
            (FIXTURES / "minified.sample").read_text(encoding="utf-8"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_calibrate_agrees_with_scan(self):
        data = calibrate_project(str(self.root), load_profile(self.root))
        result = scan(str(self.root))
        self.assertEqual(data["totals"]["calibrated_tokens"], result.total_tokens)
        fams = {r["family"] for r in data["families"]}
        self.assertEqual(fams, {"python", "prose", "minified-js"})
        for row in data["families"]:
            self.assertGreater(row["raw_tokens"], row["calibrated_tokens"])
            self.assertEqual(row["factor"], FAMILY_FACTORS[row["family"]])
        self.assertEqual(data["token_method"], METHOD)

    def test_calibrate_cli_text_and_json(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli_main(["calibrate", str(self.root)])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("minified-js", out)
        self.assertIn("estimates", out)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli_main(["calibrate", str(self.root), "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["totals"]["files"], 3)

    def test_minified_bundle_validates_despite_family_flip(self):
        # Audit F2 (pinned behaviour): the minified file's original
        # is estimated as minified-js, its signatures slice as
        # ts-js; the bundle must still validate, because validation
        # recomputes from the sliced text alone.
        mini = (FIXTURES / "minified.sample").read_text(encoding="utf-8")
        (self.root / "vendor.js").write_text(mini)
        from ghostslice.slicer import slice_text
        r = slice_text("vendor.js", mini, "signatures")
        self.assertEqual(family_for("javascript", mini), "minified-js")
        self.assertEqual(r.sliced_tokens,
                         estimate_tokens(r.text, "javascript"))
        out_dir = self.root / "bundle2"
        build_bundle(str(self.root), str(out_dir), record_history=False)
        check = validate_bundle(str(out_dir))
        self.assertTrue(check["ok"], check["errors"])

    def test_bundle_validate_agrees_with_calibrated_estimator(self):
        out_dir = self.root / "bundle"
        manifest = build_bundle(str(self.root), str(out_dir), record_history=False)
        self.assertEqual(manifest["token_method"], METHOD)
        check = validate_bundle(str(out_dir))
        self.assertTrue(check["ok"], check["errors"])
        self.assertEqual(check["total_original_tokens"],
                         manifest["total_original_tokens"])


if __name__ == "__main__":
    unittest.main()
