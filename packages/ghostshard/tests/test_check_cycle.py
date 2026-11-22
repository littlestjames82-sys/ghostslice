"""Verification bar: a shard dependency cycle must FAIL check,
with the cycle printed (PLAN.md). Also: check's other structural
rules (unknown dependency, duplicate ownership) must fail, and a
source-level import cycle must be contracted by the planner into
one shard, never leaked into a plan as a dependency cycle.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import (FIXTURES, check_folder, core_available,
                           plan_project, run_cli)


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestCycleFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.folder = self.tmp / "plan_folder"
        shutil.copytree(FIXTURES / "cycle" / "plan_folder", self.folder)

    def tearDown(self):
        self._tmp.cleanup()

    def test_cycle_fails_check(self):
        proc = check_folder(self.folder)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        out = (proc.stdout + proc.stderr).lower()
        self.assertIn("cycle", out)

    def test_cycle_output_names_both_shards(self):
        proc = check_folder(self.folder)
        out = proc.stdout + proc.stderr
        self.assertIn("shard-a", out)
        self.assertIn("shard-b", out)

    def test_cycle_json_reports_cycle(self):
        proc = run_cli(["check", self.folder, "--json"])
        self.assertEqual(proc.returncode, 1)
        res = json.loads(proc.stdout)
        self.assertFalse(res["ok"])
        self.assertTrue(res.get("cycle"), res)
        joined = " ".join(res["cycle"])
        self.assertIn("shard-a", joined)
        self.assertIn("shard-b", joined)


def _minimal_plan_folder(dest: Path, shards_spec):
    """Build a structurally minimal but bundle-valid plan folder.
    shards_spec: list of (id, owns_files, depends_on)."""
    dest.mkdir(parents=True, exist_ok=True)
    shards = []
    for sid, owns, deps in shards_spec:
        bdir = dest / sid
        (bdir / "files").mkdir(parents=True, exist_ok=True)
        manifest = {"tool": "ghostshard-bundle", "ghostshard_version": "0.1.0",
                    "shard_id": sid, "files": [],
                    "total_original_tokens": 0, "total_sliced_tokens": 0,
                    "estimator": "estimates"}
        (bdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (bdir / "PROMPT.md").write_text(f"# Shard: {sid}\n", encoding="utf-8")
        shards.append({"id": sid, "title": sid, "task": sid,
                       "owns_files": owns, "owns_symbols": [],
                       "shared_files_readonly": [], "shared_symbols": [],
                       "depends_on": deps, "parallel_group": 0,
                       "rules_fired": [], "seam_basis": "python-ast",
                       "bundle": sid, "estimated_tokens": 0,
                       "original_tokens": 0, "unfittable": False})
    plan = {"tool": "ghostshard", "version": "0.1.0", "mode": "user-split",
            "mode_label": "test", "project": "test", "partial": False,
            "budget_tokens_per_shard": 60000, "estimator": "estimates",
            "parallel_groups": [[s[0] for s in shards_spec]],
            "max_parallelism": 1, "conflicts": [], "shards": shards,
            "totals": {"estimated_tokens": 0, "original_tokens": 0, "note": "test"}}
    (dest / "shards.json").write_text(json.dumps(plan), encoding="utf-8")
    return dest


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestCheckStructuralRules(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_unknown_dependency_fails(self):
        folder = _minimal_plan_folder(
            self.tmp / "p", [("shard-x", ["x.py"], ["shard-ghost"])])
        proc = check_folder(folder)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("shard-ghost", proc.stdout + proc.stderr)

    def test_duplicate_ownership_fails(self):
        folder = _minimal_plan_folder(
            self.tmp / "p", [("shard-x", ["same.py"], []),
                             ("shard-y", ["same.py"], [])])
        proc = check_folder(folder)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("same.py", proc.stdout + proc.stderr)

    def test_valid_minimal_plan_passes(self):
        folder = _minimal_plan_folder(
            self.tmp / "p", [("shard-x", ["x.py"], []),
                             ("shard-y", ["y.py"], ["shard-x"])])
        proc = check_folder(folder)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_missing_shards_json_fails(self):
        proc = check_folder(self.tmp / "empty")
        self.assertEqual(proc.returncode, 1)


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestImportCycleContracted(unittest.TestCase):
    def test_source_import_cycle_becomes_one_shard_and_checks_ok(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            proc, out, plan = plan_project(
                tmp, "cycle", task="Change a_value and b_value",
                sub="project")
            self.assertIsNotNone(plan, proc.stderr)
            owners = [s for s in plan["shards"]
                      if "a.py" in s["owns_files"]]
            self.assertEqual(len(owners), 1, plan["shards"])
            self.assertIn("b.py", owners[0]["owns_files"])
            chk = check_folder(out)
            self.assertEqual(chk.returncode, 0, chk.stdout + chk.stderr)


if __name__ == "__main__":
    unittest.main()
