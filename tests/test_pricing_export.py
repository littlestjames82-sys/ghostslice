import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ghostslice.exporter import build_bundle, validate_bundle
from ghostslice.pricing import estimate_cost, get_model, load_prices, preflight


class TestPricing(unittest.TestCase):
    def setUp(self):
        self.prices = load_prices()

    def test_prices_are_local_and_dated(self):
        self.assertIn("as_of", self.prices)
        self.assertTrue(self.prices["models"])

    def test_estimate_cost_math(self):
        model = {"id": "x", "input_per_mtok_usd": 3.0}
        self.assertAlmostEqual(estimate_cost(1_000_000, model), 3.0)
        self.assertAlmostEqual(estimate_cost(500_000, model), 1.5)
        self.assertAlmostEqual(estimate_cost(84_000, model), 0.252)
        self.assertEqual(estimate_cost(0, model), 0.0)

    def test_preflight_savings(self):
        model = get_model(self.prices, "claude-sonnet")
        pf = preflight(84_000, 12_000, model, self.prices)
        self.assertEqual(pf["saved_tokens"], 72_000)
        self.assertAlmostEqual(pf["before_cost_usd"], 0.252)
        self.assertAlmostEqual(pf["after_cost_usd"], 0.036)
        self.assertAlmostEqual(pf["saved_cost_usd"], 0.216)

    def test_unknown_model_raises(self):
        with self.assertRaises(KeyError):
            get_model(self.prices, "no-such-model")


def make_project(root: Path):
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text(
        "def run(x: int) -> int:\n    secret = x * 3\n    return secret\n")
    (root / "src" / "api.ts").write_text(
        "export interface Api { go(): void; }\nexport function go(): void {\n  const hidden = 1;\n}\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("def test_run():\n    assert True\n")
    (root / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    (root / "README.md").write_text("# demo project\n")


class TestExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "proj"
        self.root.mkdir()
        make_project(self.root)
        self.bundle = base / "bundle"
        self.manifest = build_bundle(self.root, self.bundle)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bundle_layout(self):
        self.assertTrue((self.bundle / "manifest.json").is_file())
        self.assertTrue((self.bundle / "PROMPT.md").is_file())
        self.assertTrue((self.bundle / "files" / "src" / "app.py").is_file())
        prompt = (self.bundle / "PROMPT.md").read_text()
        self.assertIn("# File: src/app.py", prompt)

    def test_manifest_fields_and_hashes(self):
        files = {f["path"]: f for f in self.manifest["files"]}
        self.assertIn("src/app.py", files)
        entry = files["src/app.py"]
        self.assertIn("mode", entry)
        self.assertIn("original_tokens", entry)
        self.assertIn("sliced_tokens", entry)
        on_disk = (self.bundle / "files" / "src" / "app.py").read_bytes()
        self.assertEqual(entry["sha256"], hashlib.sha256(on_disk).hexdigest())
        self.assertLess(entry["sliced_tokens"], entry["original_tokens"])

    def test_manifest_totals(self):
        self.assertEqual(
            self.manifest["total_original_tokens"],
            sum(f["original_tokens"] for f in self.manifest["files"]))
        self.assertEqual(
            self.manifest["total_sliced_tokens"],
            sum(f["sliced_tokens"] for f in self.manifest["files"]))
        self.assertEqual(
            self.manifest["total_saved_tokens"],
            self.manifest["total_original_tokens"] - self.manifest["total_sliced_tokens"])

    def test_default_modes(self):
        files = {f["path"]: f for f in self.manifest["files"]}
        self.assertEqual(files["src/app.py"]["mode"], "signatures")
        self.assertEqual(files["tests/test_app.py"]["mode"], "strip-tests")
        self.assertEqual(files["package-lock.json"]["mode"], "exclude")
        self.assertEqual(files["README.md"]["mode"], "full")

    def test_validate_bundle(self):
        check = validate_bundle(self.bundle)
        self.assertTrue(check["ok"], check["errors"])
        self.assertEqual(check["total_sliced_tokens"], self.manifest["total_sliced_tokens"])

    def test_validate_detects_tampering(self):
        target = self.bundle / "files" / "src" / "app.py"
        target.write_text(target.read_text() + "\n# tampered with extra words here\n")
        check = validate_bundle(self.bundle)
        self.assertFalse(check["ok"])

    def test_manifest_json_roundtrip(self):
        loaded = json.loads((self.bundle / "manifest.json").read_text())
        self.assertEqual(loaded["tool"], "ghostslice")
        self.assertIn("token_method", loaded)


if __name__ == "__main__":
    unittest.main()
