import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.bundlediff import diff_bundles
from ghostslice.cli import main as cli_main
from ghostslice.exporter import build_bundle, validate_bundle
from ghostslice.mcp_server import handle_message
from ghostslice.profile import load_profile
from ghostslice.scanner import is_test_file, language_for, scan
from ghostslice.selection import select_for_task
from ghostslice.server import make_server
from ghostslice.slicer import slice_source


def make_fit_project(root: Path):
    (root / "main.py").write_text(
        "from util import helper\n\ndef main():\n    return helper()\n")
    (root / "util.py").write_text("def helper():\n    x = 1\n    return x\n" * 10)
    (root / "fat.py").write_text("".join(
        f"def fat_{i}():\n    a = compute_{i}()\n    b = a + 1\n    return b\n\n"
        for i in range(30)))
    (root / "notes.md").write_text(
        "# Notes\n" + ("Lots of prose about the system design and its history. " * 40 + "\n\n") * 10)


class TestFit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.root.mkdir(parents=True)
        make_fit_project(self.root)
        self.default = build_bundle(self.root, Path(self.tmp.name) / "d",
                                    record_history=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fit_noop_when_budget_generous(self):
        total = self.default["total_sliced_tokens"]
        m = build_bundle(self.root, Path(self.tmp.name) / "f",
                         record_history=False, fit=total)
        self.assertTrue(m["fit"]["fitted"])
        self.assertEqual(m["fit"]["steps"], {})
        self.assertEqual(m["total_sliced_tokens"], total)
        modes_default = {f["path"]: f["mode"] for f in self.default["files"]}
        modes_fit = {f["path"]: f["mode"] for f in m["files"]}
        self.assertEqual(modes_default, modes_fit)

    def test_fit_reduces_under_target(self):
        total = self.default["total_sliced_tokens"]
        target = total // 3
        m = build_bundle(self.root, Path(self.tmp.name) / "f",
                         record_history=False, fit=target)
        self.assertTrue(m["fit"]["fitted"])
        self.assertLessEqual(m["total_sliced_tokens"], target)
        self.assertEqual(m["fit"]["after_tokens"], m["total_sliced_tokens"])
        self.assertTrue(validate_bundle(Path(self.tmp.name) / "f")["ok"])

    def test_fit_entry_point_never_excluded(self):
        m = build_bundle(self.root, Path(self.tmp.name) / "f",
                         record_history=False, fit=1)
        self.assertFalse(m["fit"]["fitted"])
        modes = {f["path"]: f["mode"] for f in m["files"]}
        self.assertEqual(modes["main.py"], "interfaces")  # downgraded, not excluded

    def test_fit_profile_mode_protected(self):
        (self.root / ".ghostslice.json").write_text(json.dumps(
            {"modes": {"notes.md": "full"}}))
        profile = load_profile(self.root)
        m = build_bundle(self.root, Path(self.tmp.name) / "f",
                         record_history=False, fit=1, profile=profile)
        modes = {f["path"]: f["mode"] for f in m["files"]}
        self.assertEqual(modes["notes.md"], "full")  # profile mode never downgraded
        self.assertFalse(m["fit"]["fitted"])  # and that is reported honestly

    def test_fit_deterministic(self):
        target = self.default["total_sliced_tokens"] // 3
        m1 = build_bundle(self.root, Path(self.tmp.name) / "f1",
                          record_history=False, fit=target)
        m2 = build_bundle(self.root, Path(self.tmp.name) / "f2",
                          record_history=False, fit=target)
        self.assertEqual({f["path"]: f["mode"] for f in m1["files"]},
                         {f["path"]: f["mode"] for f in m2["files"]})
        self.assertEqual(m1["fit"]["steps"], m2["fit"]["steps"])
        self.assertEqual(m1["fit"]["downgraded"], m2["fit"]["downgraded"])

    def test_fit_cli_exit_codes(self):
        out_ok = Path(self.tmp.name) / "cli-ok"
        total = self.default["total_sliced_tokens"]
        rc = cli_main(["export", str(self.root), "-o", str(out_ok), "--fit", str(total // 3)])
        self.assertEqual(rc, 0)
        out_bad = Path(self.tmp.name) / "cli-bad"
        rc = cli_main(["export", str(self.root), "-o", str(out_bad), "--fit", "1"])
        self.assertEqual(rc, 1)  # could not fit: exit 1...
        self.assertTrue((out_bad / "manifest.json").is_file())  # ...but bundle written

    def test_task_bundle_fit(self):
        _r, selections, chosen, _s = select_for_task(self.root, "helper")
        m = build_bundle(self.root, Path(self.tmp.name) / "t",
                         selections=selections, include=set(chosen),
                         record_history=False, fit=50, fit_protect_selections=False)
        self.assertTrue(m["fit"]["fitted"])
        self.assertLessEqual(m["total_sliced_tokens"], 50)
        self.assertLess(m["fit"]["after_tokens"], m["fit"]["before_tokens"])


class TestTfIdfSelection(unittest.TestCase):
    def test_rare_word_file_ranks_first(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # alpha appears in all 10 files (idf -> 1.0); omega only here.
            (root / "heavy.py").write_text('WORDS = "alpha alpha alpha alpha alpha"\n')
            (root / "rare.py").write_text('WORDS = "alpha omega omega omega"\n')
            for i in range(8):
                (root / f"filler_{i}.py").write_text('WORDS = "alpha"\n')
            _r, _s, chosen, scores = select_for_task(root, "alpha omega")
            # Raw counts would rank heavy.py first (5 hits vs 4 total).
            self.assertEqual(chosen[0], "rare.py")
            self.assertGreater(scores["rare.py"], scores["heavy.py"])
            self.assertIsInstance(scores["rare.py"], float)

    def test_path_hits_still_boost(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "payments.py").write_text("x = 1\n")
            (root / "other.py").write_text("y = 2\n")
            _r, _s, chosen, scores = select_for_task(root, "payments")
            self.assertIn("payments.py", chosen)
            self.assertGreater(scores["payments.py"], 0)

    def test_billing_still_found(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "billing.py").write_text(
                "# billing payments module\ndef charge():\n    return 'billing payments'\n" * 3)
            (root / "misc.py").write_text("def thing():\n    return 1\n")
            _r, _s, chosen, scores = select_for_task(root, "fix billing payments")
            self.assertEqual(chosen[0], "billing.py")
            self.assertGreater(scores["billing.py"], 0)


PHP_SAMPLE = """<?php
namespace Shop;

use Shop\\Money;

interface Payer {
    public function pay(int $cents): bool;
}

class Store {
    private int $total = 0;

    public function total(): int {
        $x = $this->compute();
        return $x;
    }

    private function compute(): int {
        $s = "}";
        $t = '{';
        // } not a brace
        return 42;
    }
}

function format_price(int $cents): string {
    return "$" . $cents;
}

function after(): int {
    return 7;
}
"""

PHP_TEST = """<?php
class StoreTest {
    public function helper(): int { return 1; }

    /** @test */
    public function it_works(): void {
        assert(true);
    }

    public function testTotal(): void {
        assert(true);
    }

    #[Test]
    public function annotated(): void {
        assert(true);
    }
}
"""

RUBY_SAMPLE = """require "money"

module Shop
  class Store
    attr_reader :total

    def initialize
      @total = 0
    end

    def total
      @total
    end

    def config
      label = "end of the road"
      {
        a: 1,
      }
    end
  end
end

def format_price(cents)
  "$#{cents / 100.0}"
end
"""

RUBY_TEST = """class Store
  def total
    42
  end

  def test_total
    assert_equal 42, 42
  end

  def helper
    1
  end
end

describe Store do
  it "works" do
    assert_equal 42, Store.new.total
  end
end
"""

KOTLIN_SAMPLE = """package shop

import kotlin.math.abs

interface Payer {
    fun pay(cents: Int): Boolean
}

class Store {
    private var total: Int = 0

    fun total(): Int {
        val x = compute()
        return x
    }

    private fun compute(): Int {
        val label = "}"
        val tpl = "${label}"
        return 42
    }
}

fun formatPrice(cents: Int): String {
    return "$" + cents / 100
}

fun after(): Int {
    return 7
}
"""

KOTLIN_TEST = """class Store {
    fun helper(): Int { return 1 }

    @Test
    fun totalWorks() {
        assert(true)
    }

    fun testOther() {
        assert(true)
    }
}
"""

SWIFT_SAMPLE = """import Foundation

protocol Payer {
    func pay(cents: Int) -> Bool
}

class Store {
    private var total: Int = 0

    func total() -> Int {
        let x = compute()
        return x
    }

    private func compute() -> Int {
        let label = "}"
        // don't } worry
        return 42
    }
}

func formatPrice(cents: Int) -> String {
    return "$" + String(cents / 100)
}

func after() -> Int {
    return 7
}
"""

SWIFT_TEST = """class Store {
    func helper() -> Int { return 1 }

    func testTotal() {
        assert(true)
    }

    func other() -> Int {
        return 2
    }
}
"""


class TestPhpSlicer(unittest.TestCase):
    def test_signatures(self):
        out = slice_source(PHP_SAMPLE, "php", "signatures", path="shop.php")
        self.assertIn("interface Payer", out)
        self.assertIn("public function pay(int $cents): bool;", out)
        self.assertIn("class Store", out)
        self.assertIn("private int $total = 0;", out)
        self.assertIn("public function total(): int", out)
        self.assertIn("function format_price(int $cents): string", out)
        self.assertNotIn("return 42", out)
        self.assertNotIn("$x = $this->compute()", out)

    def test_interfaces(self):
        out = slice_source(PHP_SAMPLE, "php", "interfaces", path="shop.php")
        self.assertIn("interface Payer", out)
        self.assertIn("public function total(): int", out)
        self.assertNotIn("format_price", out)

    def test_strip_tests(self):
        out = slice_source(PHP_TEST, "php", "strip-tests", path="Checks.php")
        self.assertIn("helper", out)
        self.assertNotIn("it_works", out)
        self.assertNotIn("testTotal", out)
        self.assertNotIn("annotated", out)

    def test_adversarial_braces_in_strings(self):
        # "}" in a string, '{' in a string, } in a comment inside compute():
        # the following top-level function must still be found.
        out = slice_source(PHP_SAMPLE, "php", "signatures", path="shop.php")
        self.assertIn("function after(): int", out)


class TestRubySlicer(unittest.TestCase):
    def test_signatures(self):
        out = slice_source(RUBY_SAMPLE, "ruby", "signatures", path="store.rb")
        self.assertIn('require "money"', out)
        self.assertIn("module Shop", out)
        self.assertIn("class Store", out)
        self.assertIn("attr_reader :total", out)
        self.assertIn("def initialize", out)
        self.assertIn("def total", out)
        self.assertIn("def format_price(cents)", out)
        self.assertNotIn("@total = 0", out)

    def test_interfaces(self):
        out = slice_source(RUBY_SAMPLE, "ruby", "interfaces", path="store.rb")
        self.assertIn("class Store", out)
        self.assertIn("def total", out)
        self.assertNotIn("format_price", out)

    def test_strip_tests(self):
        out = slice_source(RUBY_TEST, "ruby", "strip-tests", path="checks.rb")
        self.assertIn("def total", out)
        self.assertIn("def helper", out)
        self.assertNotIn("test_total", out)
        self.assertNotIn("describe", out)
        self.assertNotIn("works", out)

    def test_adversarial_hash_braces_and_end_string(self):
        # def config has a multi-line hash literal and a string containing
        # "end of the road": its block must close at its own `end`, and the
        # class/module structure around it must survive.
        out = slice_source(RUBY_SAMPLE, "ruby", "signatures", path="store.rb")
        self.assertIn("def config", out)
        self.assertIn("def format_price(cents)", out)
        self.assertNotIn("a: 1", out)


class TestKotlinSlicer(unittest.TestCase):
    def test_signatures(self):
        out = slice_source(KOTLIN_SAMPLE, "kotlin", "signatures", path="Store.kt")
        self.assertIn("interface Payer", out)
        self.assertIn("fun pay(cents: Int): Boolean", out)
        self.assertIn("class Store", out)
        self.assertIn("private var total: Int = 0", out)
        self.assertIn("fun total(): Int", out)
        self.assertIn("fun formatPrice(cents: Int): String", out)
        self.assertNotIn("return 42", out)

    def test_interfaces(self):
        out = slice_source(KOTLIN_SAMPLE, "kotlin", "interfaces", path="Store.kt")
        self.assertIn("interface Payer", out)
        self.assertNotIn("formatPrice", out)

    def test_strip_tests(self):
        out = slice_source(KOTLIN_TEST, "kotlin", "strip-tests", path="Checks.kt")
        self.assertIn("helper", out)
        self.assertNotIn("totalWorks", out)
        self.assertNotIn("testOther", out)

    def test_adversarial_string_brace_and_template(self):
        out = slice_source(KOTLIN_SAMPLE, "kotlin", "signatures", path="Store.kt")
        self.assertIn("fun after(): Int", out)


class TestSwiftSlicer(unittest.TestCase):
    def test_signatures(self):
        out = slice_source(SWIFT_SAMPLE, "swift", "signatures", path="Store.swift")
        self.assertIn("protocol Payer", out)
        self.assertIn("func pay(cents: Int) -> Bool", out)
        self.assertIn("class Store", out)
        self.assertIn("private var total: Int = 0", out)
        self.assertIn("func total() -> Int", out)
        self.assertIn("func formatPrice(cents: Int) -> String", out)
        self.assertNotIn("return 42", out)

    def test_interfaces(self):
        out = slice_source(SWIFT_SAMPLE, "swift", "interfaces", path="Store.swift")
        self.assertIn("protocol Payer", out)
        self.assertNotIn("formatPrice", out)

    def test_strip_tests(self):
        out = slice_source(SWIFT_TEST, "swift", "strip-tests", path="Checks.swift")
        self.assertIn("helper", out)
        self.assertIn("func other()", out)
        self.assertNotIn("testTotal", out)

    def test_adversarial_string_brace_and_comment(self):
        out = slice_source(SWIFT_SAMPLE, "swift", "signatures", path="Store.swift")
        self.assertIn("func after() -> Int", out)


class TestNewLanguageWiring(unittest.TestCase):
    def test_language_detection(self):
        self.assertEqual(language_for("a.php"), "php")
        self.assertEqual(language_for("a.rb"), "ruby")
        self.assertEqual(language_for("a.kt"), "kotlin")
        self.assertEqual(language_for("a.kts"), "kotlin")
        self.assertEqual(language_for("a.swift"), "swift")

    def test_test_file_conventions(self):
        self.assertTrue(is_test_file("StoreTest.php"))
        self.assertFalse(is_test_file("latest.php"))
        self.assertTrue(is_test_file("StoreTests.swift"))
        self.assertTrue(is_test_file("store_test.rb"))
        self.assertTrue(is_test_file("StoreTest.kt"))

    def test_export_defaults_slice_new_languages(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"; root.mkdir()
            (root / "a.php").write_text(PHP_SAMPLE)
            (root / "b.rb").write_text(RUBY_SAMPLE)
            (root / "c.kt").write_text(KOTLIN_SAMPLE)
            (root / "d.swift").write_text(SWIFT_SAMPLE)
            out = Path(td) / "bundle"
            manifest = build_bundle(root, out, record_history=False)
            modes = {f["path"]: f["mode"] for f in manifest["files"]}
            for p in ("a.php", "b.rb", "c.kt", "d.swift"):
                self.assertEqual(modes[p], "signatures")
            sliced = {f["path"]: f["sliced_tokens"] for f in manifest["files"]}
            original = {f["path"]: f["original_tokens"] for f in manifest["files"]}
            for p in sliced:
                self.assertLess(sliced[p], original[p])
            self.assertTrue(validate_bundle(out)["ok"])
            paths = {f.path for f in scan(root).files}
            self.assertEqual(paths, {"a.php", "b.rb", "c.kt", "d.swift"})


class TestBundleDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.root.mkdir(parents=True)
        make_fit_project(self.root)
        self.a = Path(self.tmp.name) / "a"
        build_bundle(self.root, self.a, record_history=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_bundles_no_changes(self):
        b = Path(self.tmp.name) / "b"
        build_bundle(self.root, b, record_history=False)
        d = diff_bundles(self.a, b)
        self.assertEqual(d["added"], [])
        self.assertEqual(d["removed"], [])
        self.assertEqual(d["changed"], [])
        self.assertEqual(d["totals"]["sliced_delta"], 0)
        self.assertEqual(d["unchanged_count"], 4)
        self.assertEqual(cli_main(["diff", str(self.a), str(b)]), 0)

    def test_mode_change_shows_delta(self):
        b = Path(self.tmp.name) / "b"
        build_bundle(self.root, b, record_history=False, default_mode="full")
        d = diff_bundles(self.a, b)
        changed = {c["path"]: c for c in d["changed"]}
        self.assertIn("fat.py", changed)
        self.assertEqual(changed["fat.py"]["mode_from"], "signatures")
        self.assertEqual(changed["fat.py"]["mode_to"], "full")
        self.assertGreater(changed["fat.py"]["sliced_delta"], 0)
        self.assertGreater(d["totals"]["sliced_delta"], 0)
        self.assertEqual(cli_main(["diff", str(self.a), str(b), "--json"]), 0)

    def test_added_and_removed(self):
        (self.root / "extra.py").write_text("def extra():\n    return 1\n")
        b = Path(self.tmp.name) / "b"
        build_bundle(self.root, b, record_history=False)
        d = diff_bundles(self.a, b)
        self.assertEqual([f["path"] for f in d["added"]], ["extra.py"])
        self.assertEqual(d["removed"], [])
        d2 = diff_bundles(b, self.a)
        self.assertEqual([f["path"] for f in d2["removed"]], ["extra.py"])

    def test_invalid_bundle_exit_1(self):
        b = Path(self.tmp.name) / "b"
        build_bundle(self.root, b, record_history=False)
        victim = b / "files" / "util.py"
        victim.write_text(victim.read_text() + "\ndef tampered():\n    return 0\n")
        self.assertFalse(validate_bundle(b)["ok"])
        self.assertEqual(cli_main(["diff", str(self.a), str(b)]), 1)


class TestNewPresets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.root.mkdir(parents=True)
        make_fit_project(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cursor_preset(self):
        out = Path(self.tmp.name) / "cursor-bundle"
        manifest = build_bundle(self.root, out, preset="cursor", record_history=False)
        self.assertEqual(manifest["preset"], "cursor")
        self.assertTrue((out / "prompt.md").is_file())
        readme = (out / "README.txt").read_text()
        self.assertIn("Cursor", readme)
        self.assertIn("prompt.md", readme)
        self.assertTrue(validate_bundle(out)["ok"])

    def test_copilot_preset(self):
        out = Path(self.tmp.name) / "copilot-bundle"
        manifest = build_bundle(self.root, out, preset="copilot", record_history=False)
        self.assertEqual(manifest["preset"], "copilot")
        prompt = (out / "prompt.md").read_text()
        self.assertIn("Copilot", prompt)
        self.assertIn("## File: main.py", prompt)
        self.assertIn("```python", prompt)
        self.assertTrue(validate_bundle(out)["ok"])

    def test_profile_accepts_new_presets(self):
        (self.root / ".ghostslice.json").write_text(json.dumps({"preset": "copilot"}))
        self.assertEqual(load_profile(self.root).preset, "copilot")

    def test_mcp_preset_enum(self):
        resp = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        enum = tools["export_bundle"]["inputSchema"]["properties"]["preset"]["enum"]
        self.assertIn("cursor", enum)
        self.assertIn("copilot", enum)

    def test_cli_preset_cursor(self):
        out = Path(self.tmp.name) / "cli-cursor"
        self.assertEqual(cli_main(["export", str(self.root), "-o", str(out),
                                   "--preset", "cursor"]), 0)
        self.assertTrue((out / "README.txt").is_file())


class TestDashboardTreemap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "app.py").write_text("def run(x: int) -> int:\n    return x * 3\n")
        (self.root / "api.ts").write_text("export function go(): void {\n  const h = 1;\n}\n")
        self.server, _ = make_server(str(self.root), port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
            return r.status, r.read().decode("utf-8")

    def test_homepage_has_treemap_toggle(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn('id="treemap"', body)
        self.assertIn('id="viewTreemap"', body)
        self.assertIn("Treemap", body)
        self.assertIn('id="fileTable"', body)  # list view still present/default

    def test_apis_unchanged(self):
        status, body = self.get("/api/scan")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["file_count"], 2)
        status, body = self.get("/api/secrets")
        self.assertEqual(status, 200)
        self.assertIn("findings", json.loads(body))


if __name__ == "__main__":
    unittest.main()
