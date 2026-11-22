"""Hardening regression tests (improvement wave, lane: harden).

Each test pins a bug found by auditing the planner / bundle writer /
checker / CLI against malformed or adversarial inputs:

- the planner could emit a shard-dependency CYCLE (quotient of the
  file DAG via user assignment) that failed its own `check`;
- a fit-split renamed a shard to <id>-partN but left dependents,
  parallel_groups and the bus manifest pointing at the old id, so
  the written plan failed `check` with unknown-shard errors;
- `check` crashed with tracebacks on malformed shards.json /
  manifests and happily read files OUTSIDE the plan folder when a
  manifest row path contained '..';
- `check` ignored bus-manifest.json entirely, so a tampered
  dispatch: true passed silently (the planner-only hard rule);
- profile parsing crashed on non-integer values, and an explicit
  --budget 0 was silently ignored (truthiness test);
- export-bus crashed with a traceback on invalid shards.json and
  on an -o destination whose parent directory did not exist;
- an empty project produced a complete-looking empty plan (exit 0).
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tests.helpers import (check_folder, copy_fixture_project,
                           core_available, plan_project, run_cli)


def _no_traceback(proc):
    return "Traceback" not in (proc.stdout + proc.stderr)


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestShardCycleContraction(unittest.TestCase):
    def test_cross_import_dag_cycle_is_contracted_and_checks_ok(self):
        from ghostshard.bundles import check_plan, write_plan
        from ghostshard.planner import plan_project as plan_p
        from ghostshard.project import find_cycle
        from ghostshard.taskfile import Subtask
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            proj = tmp / "proj"
            proj.mkdir()
            # File-level DAG (a_one -> b -> a_two, no file cycle) whose
            # shard quotient cycles: Alpha owns a_*, Beta owns b.
            (proj / "a_one.py").write_text(
                "# alpha apple\nfrom b import beta_thing\n"
                "def alpha_one():\n    return beta_thing()\n")
            (proj / "a_two.py").write_text(
                "# alpha apple\ndef alpha_two():\n    return 2\n")
            (proj / "b.py").write_text(
                "# beta banana\nfrom a_two import alpha_two\n"
                "def beta_thing():\n    return alpha_two()\n")
            subs = [Subtask("Alpha work", "alpha apple"),
                    Subtask("Beta work", "beta banana")]
            plan = plan_p(proj, subtasks=subs)
            graph = {s["id"]: s["depends_on"] for s in plan["shards"]}
            self.assertIsNone(find_cycle(graph), graph)
            self.assertEqual(len(plan["shards"]), 1, plan["shards"])
            merged = plan["shards"][0]
            self.assertEqual(sorted(merged["owns_files"]),
                             ["a_one.py", "a_two.py", "b.py"])
            self.assertTrue(any("dependency-cycle" in c
                                for c in plan["conflicts"]), plan["conflicts"])
            out = tmp / "out"
            _, code = write_plan(plan, proj, out)
            self.assertEqual(code, 0)
            self.assertTrue(check_plan(out)["ok"], check_plan(out))


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestFitSplitRemap(unittest.TestCase):
    def test_split_shard_dependents_groups_and_bus_are_remapped(self):
        from ghostshard.bundles import check_plan, write_plan
        from ghostshard.project import FileInfo
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            def fi(rel, ntok):
                return FileInfo(rel=rel, text="aaaa " * ntok,
                                language="python")
            files = {"x1.py": fi("x1.py", 60), "x2.py": fi("x2.py", 60),
                     "y.py": fi("y.py", 5)}
            base = {"owns_symbols": [], "shared_files_readonly": [],
                    "shared_symbols": [], "rules_fired": [],
                    "seam_basis": "python-ast"}
            plan = {
                "files": files, "mode": "user-split", "partial": False,
                "conflicts": [], "budget_tokens": 100, "max_shards": 12,
                "parallel_groups": [["shard-01-xwork"], ["shard-02-ywork"]],
                "max_parallelism": 1,
                "shards": [
                    dict(base, id="shard-01-xwork", title="xwork",
                         task="do x", owns_files=["x1.py", "x2.py"],
                         depends_on=[], parallel_group=0),
                    dict(base, id="shard-02-ywork", title="ywork",
                         task="do y", owns_files=["y.py"],
                         depends_on=["shard-01-xwork"], parallel_group=1),
                ]}
            out = tmp / "out"
            summary, code = write_plan(plan, tmp, out)
            self.assertEqual(code, 0)
            by_id = {s["id"]: s for s in summary["shards"]}
            self.assertIn("shard-01-xwork-part1", by_id)
            self.assertIn("shard-01-xwork-part2", by_id)
            self.assertEqual(by_id["shard-02-ywork"]["depends_on"],
                             ["shard-01-xwork-part1", "shard-01-xwork-part2"])
            flat = [i for g in summary["parallel_groups"] for i in g]
            self.assertEqual(sorted(flat), sorted(by_id), summary["parallel_groups"])
            bus = json.loads((out / "bus-manifest.json").read_text())
            jobs = {j["job_id"]: j for j in bus["jobs"]}
            self.assertEqual(jobs["shard-02-ywork"]["depends_on"],
                             ["shard-01-xwork-part1", "shard-01-xwork-part2"])
            self.assertTrue(all(j["dispatch"] is False for j in bus["jobs"]))
            self.assertTrue(check_plan(out)["ok"], check_plan(out))


def _folder_with_shards(tmp: Path, shards_json_text: str) -> Path:
    folder = tmp / "plan"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "shards.json").write_text(shards_json_text, encoding="utf-8")
    return folder


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestCheckHardening(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_malformed_manifest_is_error_not_crash(self):
        folder = _folder_with_shards(self.tmp, json.dumps({"shards": [
            {"id": "s1", "bundle": "s1", "owns_files": [],
             "depends_on": [], "estimated_tokens": 0}]}))
        (folder / "s1").mkdir()
        (folder / "s1" / "manifest.json").write_text("{not json")
        proc = check_folder(folder)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertTrue(_no_traceback(proc), proc.stderr)
        self.assertIn("manifest", proc.stdout + proc.stderr)

    def test_shards_json_wrong_shape_is_error_not_crash(self):
        folder = _folder_with_shards(self.tmp, "[]")
        proc = check_folder(folder)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertTrue(_no_traceback(proc), proc.stderr)

    def test_shard_entry_missing_id_is_error_not_crash(self):
        folder = _folder_with_shards(
            self.tmp, json.dumps({"shards": [{"owns_files": []}]}))
        proc = check_folder(folder)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertTrue(_no_traceback(proc), proc.stderr)
        self.assertIn("malformed", proc.stdout + proc.stderr)

    def test_manifest_row_path_traversal_rejected(self):
        folder = _folder_with_shards(self.tmp, json.dumps({"shards": [
            {"id": "s1", "bundle": "s1", "owns_files": [],
             "depends_on": [], "estimated_tokens": 1}]}))
        bdir = folder / "s1"
        (bdir / "files").mkdir(parents=True)
        content = "a"
        (folder / "outside.txt").write_text(content)
        sha = hashlib.sha256(content.encode()).hexdigest()
        (bdir / "manifest.json").write_text(json.dumps({
            "files": [{"path": "../../outside.txt", "mode": "full",
                       "original_tokens": 1, "sliced_tokens": 1,
                       "sha256": sha}],
            "total_original_tokens": 1, "total_sliced_tokens": 1}))
        proc = check_folder(folder)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("escapes", proc.stdout + proc.stderr)

    def test_bundle_path_traversal_rejected(self):
        outside = self.tmp / "outside-bundle"
        outside.mkdir()
        (outside / "manifest.json").write_text(json.dumps({
            "files": [], "total_original_tokens": 0,
            "total_sliced_tokens": 0}))
        folder = _folder_with_shards(self.tmp, json.dumps({"shards": [
            {"id": "s1", "bundle": "../outside-bundle", "owns_files": [],
             "depends_on": [], "estimated_tokens": 0}]}))
        proc = check_folder(folder)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("escapes", proc.stdout + proc.stderr)

    def test_dispatch_true_in_bus_manifest_fails_check(self):
        proc0, out, plan = plan_project(
            self.tmp, "disjoint", task="alpha beta work")
        self.assertIsNotNone(plan, proc0.stderr)
        bus_path = out / "bus-manifest.json"
        bus = json.loads(bus_path.read_text(encoding="utf-8"))
        self.assertTrue(all(j["dispatch"] is False for j in bus["jobs"]))
        bus["jobs"][0]["dispatch"] = True
        bus_path.write_text(json.dumps(bus), encoding="utf-8")
        proc = check_folder(out)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("dispatch", proc.stdout + proc.stderr)


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestProfileAndFlagHardening(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _project(self, profile_text=None):
        proj = self.tmp / "proj"
        proj.mkdir(exist_ok=True)
        (proj / "a.py").write_text("x = 1\n")
        if profile_text is not None:
            (proj / ".ghostshard.json").write_text(profile_text)
        return proj

    def test_bad_profiles_are_clean_errors_not_tracebacks(self):
        cases = {
            "non-integer value": '{"shard": {"budget_tokens": "lots"}}',
            "zero value": '{"shard": {"budget_tokens": 0}}',
            "bool value": '{"shard": {"max_shards": true}}',
            "shard not an object": '{"shard": 5}',
            "top level not an object": "[]",
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                proj = self._project(text)
                proc = run_cli(["plan", proj, "--task", "x",
                                "-o", self.tmp / "out"])
                self.assertNotEqual(proc.returncode, 0,
                                    proc.stdout + proc.stderr)
                self.assertTrue(_no_traceback(proc), proc.stderr)
                self.assertIn("invalid", (proc.stdout + proc.stderr).lower())

    def test_budget_zero_flag_rejected_not_ignored(self):
        proj = copy_fixture_project("disjoint", self.tmp / "project")
        proc = run_cli(["plan", proj, "--task", "alpha", "--budget", "0",
                        "-o", self.tmp / "out"])
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(_no_traceback(proc), proc.stderr)
        self.assertIn("budget", (proc.stdout + proc.stderr).lower())


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestExportBusHardening(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_invalid_shards_json_is_clean_error(self):
        folder = self.tmp / "plan"
        folder.mkdir()
        (folder / "shards.json").write_text("not json")
        proc = run_cli(["export-bus", folder])
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertTrue(_no_traceback(proc), proc.stderr)

    def test_shards_json_without_shards_list_is_clean_error(self):
        folder = self.tmp / "plan"
        folder.mkdir()
        (folder / "shards.json").write_text("{}")
        proc = run_cli(["export-bus", folder])
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertTrue(_no_traceback(proc), proc.stderr)

    def test_export_to_nested_destination_creates_parents(self):
        proc0, out, plan = plan_project(
            self.tmp, "disjoint", task="alpha beta work")
        self.assertIsNotNone(plan, proc0.stderr)
        dest = self.tmp / "deep" / "nested" / "bus.json"
        proc = run_cli(["export-bus", out, "-o", dest])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = json.loads(dest.read_text(encoding="utf-8"))
        self.assertTrue(all(j["dispatch"] is False for j in doc["jobs"]))


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestEmptyPlan(unittest.TestCase):
    def test_empty_project_is_partial_not_silent_success(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            proj = tmp / "empty"
            proj.mkdir()
            out = tmp / "out"
            proc = run_cli(["plan", proj, "--task", "anything", "-o", out])
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            plan = json.loads((out / "shards.json").read_text())
            self.assertTrue(plan["partial"])
            self.assertTrue(any("empty-plan" in c
                                for c in plan["conflicts"]), plan["conflicts"])


if __name__ == "__main__":
    unittest.main()
