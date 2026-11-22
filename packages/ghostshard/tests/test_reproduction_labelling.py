"""Verification bars: reproduction and honesty (PLAN.md).

- Plan totals equal the sum of the per-shard bundle manifests, and
  every generated plan passes `ghostshard check`.
- Auto-clustered plans are labelled auto-clustered in shards.json
  AND PLAN.md; user-split plans are labelled user-split in both.
- The GhostBus handoff is a file only: every job carries
  dispatch=false and a Seatbelt approval placeholder; planning
  sends nothing.
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import (FIXTURES, check_folder, core_available,
                           load_manifest, plan_project, run_cli)


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestReproduction(unittest.TestCase):
    def _plan(self, tmp, fixture, **kw):
        proc, out, plan = plan_project(tmp, fixture, **kw)
        self.assertIsNotNone(plan, proc.stderr)
        return proc, out, plan

    def test_totals_equal_sum_of_bundle_manifests(self):
        with tempfile.TemporaryDirectory() as td:
            _, out, plan = self._plan(
                Path(td), "disjoint",
                task=(FIXTURES / "disjoint" / "TASK.txt").read_text(
                    encoding="utf-8").strip())
            manifest_sliced = 0
            manifest_original = 0
            for s in plan["shards"]:
                man = load_manifest(out / s["bundle"])
                self.assertEqual(man["shard_id"], s["id"])
                self.assertEqual(man["total_sliced_tokens"],
                                 s["estimated_tokens"])
                self.assertEqual(
                    man["total_sliced_tokens"],
                    sum(r["sliced_tokens"] for r in man["files"]))
                self.assertEqual(
                    man["total_original_tokens"],
                    sum(r["original_tokens"] for r in man["files"]))
                manifest_sliced += man["total_sliced_tokens"]
                manifest_original += man["total_original_tokens"]
            self.assertEqual(plan["totals"]["estimated_tokens"],
                             manifest_sliced)
            self.assertEqual(plan["totals"]["original_tokens"],
                             manifest_original)
            self.assertEqual(
                plan["totals"]["estimated_tokens"],
                sum(s["estimated_tokens"] for s in plan["shards"]))

    def test_generated_plans_pass_check(self):
        cases = [
            ("disjoint", dict(task="alpha summary and beta export")),
            ("shared", dict(task_file=FIXTURES / "shared" / "tasks.md")),
            ("cycle", dict(task="Change a_value and b_value",
                           sub="project")),
        ]
        for fixture, kw in cases:
            with self.subTest(fixture=fixture), \
                    tempfile.TemporaryDirectory() as td:
                _, out, plan = self._plan(Path(td), fixture, **kw)
                proc = check_folder(out)
                self.assertEqual(proc.returncode, 0,
                                 proc.stdout + proc.stderr)


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestLabelling(unittest.TestCase):
    def test_auto_clustered_labelled_in_json_and_md(self):
        with tempfile.TemporaryDirectory() as td:
            _, out, plan = plan_project(
                Path(td), "disjoint", task="alpha summary and beta export")
            self.assertEqual(plan["mode"], "auto-clustered")
            self.assertIn("auto-clustered", plan["mode_label"])
            md = (out / "PLAN.md").read_text(encoding="utf-8")
            self.assertIn("auto-clustered", md)

    def test_user_split_labelled_in_json_and_md(self):
        with tempfile.TemporaryDirectory() as td:
            _, out, plan = plan_project(
                Path(td), "shared",
                task_file=FIXTURES / "shared" / "tasks.md")
            self.assertEqual(plan["mode"], "user-split")
            self.assertIn("user-split", plan["mode_label"])
            md = (out / "PLAN.md").read_text(encoding="utf-8")
            self.assertIn("user-split", md)

    def test_estimator_labelled_as_estimate(self):
        with tempfile.TemporaryDirectory() as td:
            _, out, plan = plan_project(
                Path(td), "disjoint", task="alpha summary and beta export")
            self.assertIn("estimate", plan["estimator"].lower())


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestBusManifestIsFileOnly(unittest.TestCase):
    def test_jobs_dispatch_false_with_approval_placeholder(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, out, plan = plan_project(
                tmp, "disjoint", task="alpha summary and beta export")
            bus_path = out / "bus-manifest.json"
            self.assertTrue(bus_path.is_file(),
                            "plan did not write bus-manifest.json")
            bus = json.loads(bus_path.read_text(encoding="utf-8"))
            self.assertEqual(bus["kind"], "ghostbus-job-manifest")
            self.assertEqual(len(bus["jobs"]), len(plan["shards"]))
            for job in bus["jobs"]:
                self.assertIs(job["dispatch"], False)
                self.assertIn("seatbelt", job["approval_class"])
                self.assertIn(job["job_id"],
                              [s["id"] for s in plan["shards"]])

    def test_export_bus_command_writes_file_and_sends_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _, out, plan = plan_project(
                tmp, "disjoint", task="alpha summary and beta export")
            dest = tmp / "bus-copy.json"
            proc = run_cli(["export-bus", out, "-o", dest])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(dest.is_file())
            self.assertIn("nothing sent", proc.stdout)


if __name__ == "__main__":
    unittest.main()
