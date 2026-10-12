import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.cli import main as cli_main
from ghostslice.exporter import build_bundle, estimate_context_tokens, validate_bundle
from ghostslice.graph import build_graph, changed_files, recommendations
from ghostslice.ledger import read_records, summary
from ghostslice.profile import load_profile, match_glob
from ghostslice.scanner import scan
from ghostslice.selection import select_for_diff, select_for_task


def make_project(root: Path):
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text(
        "from src.util import helper\nfrom src.dead import unused\n\n"
        "def main():\n    return helper()\n")
    (root / "src" / "util.py").write_text("def helper():\n    return 42\n" * 5)
    (root / "src" / "dead.py").write_text("def unused():\n    return 0\n" * 5)
    (root / "src" / "orphan.py").write_text("def lonely():\n    return 1\n" * 5)
    (root / "src" / "__init__.py").write_text("")
    (root / "web").mkdir()
    (root / "web" / "app.ts").write_text(
        "import { api } from './api';\nexport function app() { return api(); }\n")
    (root / "web" / "api.ts").write_text("export function api() { return 1; }\n")
    (root / "web" / "unused.ts").write_text("export function unusedTs() { return 9; }\n")
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# Guide\nPayments and billing flow.\n" * 5)
    (root / "src" / "billing.py").write_text(
        "# billing payments module\ndef charge_card():\n    return 'billing payments'\n" * 5)


class TestNestedGitignore(unittest.TestCase):
    def test_nested_gitignore_rules_apply_to_subtree_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a").mkdir(); (root / "b").mkdir()
            (root / "a" / "secret.py").write_text("x = 1\n")
            (root / "b" / "secret.py").write_text("x = 2\n")
            (root / "a" / "keep.py").write_text("x = 3\n")
            (root / "a" / ".gitignore").write_text("secret.py\n")
            paths = {f.path for f in scan(root).files}
            self.assertNotIn("a/secret.py", paths)
            self.assertIn("b/secret.py", paths)
            self.assertIn("a/keep.py", paths)

    def test_nested_negation_overrides_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".gitignore").write_text("*.log\n")
            (root / "sub").mkdir()
            (root / "sub" / ".gitignore").write_text("!keep.log\n")
            (root / "sub" / "keep.log").write_text("hi\n")
            (root / "sub" / "drop.log").write_text("hi\n")
            paths = {f.path for f in scan(root).files}
            self.assertIn("sub/keep.log", paths)
            self.assertNotIn("sub/drop.log", paths)


class TestGraph(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_project(self.root)
        self.result = scan(self.root)
        self.graph = build_graph(self.result)

    def tearDown(self):
        self.tmp.cleanup()

    def test_python_import_edges(self):
        self.assertIn("src/util.py", self.graph["src/main.py"]["imports"])
        self.assertIn("src/dead.py", self.graph["src/main.py"]["imports"])

    def test_ts_import_edges(self):
        self.assertIn("web/api.ts", self.graph["web/app.ts"]["imports"])

    def test_recommendations_flag_unreachable(self):
        recs = {r["path"]: r for r in recommendations(self.result, self.graph)}
        # orphan.py: nothing imports it and it is unreachable from src/main.py
        self.assertIn("src/orphan.py", recs)
        self.assertGreater(recs["src/orphan.py"]["potential_savings"], 0)
        # reachable + entry files are never candidates
        self.assertNotIn("src/util.py", recs)
        self.assertNotIn("src/main.py", recs)
        # docs are never candidates
        self.assertNotIn("docs/guide.md", recs)


class TestProfile(unittest.TestCase):
    def test_match_glob(self):
        self.assertTrue(match_glob("src/**", "src/a/b.py"))
        self.assertTrue(match_glob("*.snap", "x/y.snap"))
        self.assertTrue(match_glob("**/*.py", "a/b.py"))
        self.assertFalse(match_glob("src/**", "docs/a.py"))

    def test_profile_loads_and_modes_apply_in_export(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"; root.mkdir()
            make_project(root)
            (root / ".ghostslice.json").write_text(json.dumps({
                "modes": {"src/**": "full"},
                "budget_tokens": 12345,
                "entry_points": ["src/main.py"],
            }))
            profile = load_profile(root)
            self.assertEqual(profile.budget_tokens, 12345)
            self.assertEqual(profile.mode_for("src/util.py"), "full")
            out = Path(td) / "bundle"
            manifest = build_bundle(root, out, profile=profile, record_history=False)
            modes = {f["path"]: f["mode"] for f in manifest["files"]}
            self.assertEqual(modes["src/util.py"], "full")

    def test_profile_ignore_skips_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_project(root)
            (root / ".ghostslice.json").write_text(json.dumps({"ignore": ["src/dead.py"]}))
            profile = load_profile(root)
            paths = {f.path for f in scan(root, ignore_matcher=profile.is_ignored).files}
            self.assertNotIn("src/dead.py", paths)


class TestSelection(unittest.TestCase):
    def test_task_keywords_pick_billing_within_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); make_project(root)
            _r, selections, chosen, scores = select_for_task(
                root, "fix billing payments", budget=100000)
            self.assertIn("src/billing.py", chosen)
            self.assertGreater(scores["src/billing.py"], 0)
            self.assertTrue(set(selections) == set(chosen))

    def test_task_budget_limits_selection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); make_project(root)
            _r, _s, chosen, _sc = select_for_task(root, "billing payments guide", budget=1)
            # budget=1: only the single best file is forced in
            self.assertEqual(len(chosen), 1)

    def test_diff_selection_includes_deps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); make_project(root)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                            "commit", "-qm", "init"], cwd=root, check=True)
            (root / "src" / "util.py").write_text("def helper():\n    return 43\n")
            changed = changed_files(root)
            self.assertIn("src/util.py", changed)
            _r, _s, chosen, changed2 = select_for_diff(root)
            self.assertIn("src/util.py", chosen)
            self.assertIn("src/main.py", chosen)  # importer of util.py


class TestBudgetAndPresets(unittest.TestCase):
    def test_check_budget_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); make_project(root)
            self.assertEqual(cli_main(["check-budget", str(root), "--max-tokens", "100000000"]), 0)
            self.assertEqual(cli_main(["check-budget", str(root), "--max-tokens", "1"]), 1)
            self.assertEqual(cli_main(["check-budget", str(root)]), 2)  # no budget anywhere

    def test_estimate_context_tokens_reduces(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); make_project(root)
            before, after = estimate_context_tokens(root)
            self.assertGreater(before, after)

    def test_presets_write_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"; root.mkdir(); make_project(root)
            for preset, artifact in (("aider", "aider-files.txt"), ("generic", "prompt.md")):
                out = Path(td) / f"bundle-{preset}"
                manifest = build_bundle(root, out, preset=preset, record_history=False)
                self.assertEqual(manifest["preset"], preset)
                self.assertTrue((out / artifact).is_file())
                self.assertTrue(validate_bundle(out)["ok"])

    def test_task_cli_exports_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"; root.mkdir(); make_project(root)
            out = Path(td) / "task-bundle"
            rc = cli_main(["task", str(root), "--task", "billing payments",
                           "-o", str(out)])
            self.assertEqual(rc, 0)
            manifest = json.loads((out / "manifest.json").read_text())
            included = [f for f in manifest["files"] if f["mode"] != "exclude"]
            self.assertTrue(any(f["path"] == "src/billing.py" for f in included))


class TestLedger(unittest.TestCase):
    def test_export_appends_history(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"; root.mkdir(); make_project(root)
            build_bundle(root, Path(td) / "b1")
            build_bundle(root, Path(td) / "b2")
            records = read_records(root)
            self.assertEqual(len(records), 2)
            summ = summary(root)
            self.assertEqual(summ["runs"], 2)
            self.assertGreater(summ["total_saved_tokens"], 0)
            # ledger file itself is never scanned into context
            paths = {f.path for f in scan(root).files}
            self.assertNotIn(".ghostslice-history.jsonl", paths)


if __name__ == "__main__":
    unittest.main()
