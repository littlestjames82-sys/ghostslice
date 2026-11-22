"""Verification bar: disjoint fixture must parallelise.

Two independent subgraphs (alpha/, beta/) must yield two shards in
ONE parallel group, zero shared owned files (PLAN.md).
"""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import FIXTURES, core_available, plan_project, shards_by_id


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestDisjoint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        task = (FIXTURES / "disjoint" / "TASK.txt").read_text(encoding="utf-8").strip()
        self.proc, self.out, self.plan = plan_project(
            self.tmp, "disjoint", task=task)

    def tearDown(self):
        self._tmp.cleanup()

    def test_plan_succeeds_and_is_complete(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertIsNotNone(self.plan, "shards.json was not written")
        self.assertFalse(self.plan["partial"])

    def test_two_shards_each_owning_one_subgraph(self):
        shards = self.plan["shards"]
        self.assertEqual(len(shards), 2, shards)
        owned = sorted(tuple(s["owns_files"]) for s in shards)
        self.assertEqual(owned, [("alpha/alpha.py",), ("beta/beta.py",)])

    def test_one_parallel_group_max_parallelism_two(self):
        groups = self.plan["parallel_groups"]
        self.assertEqual(len(groups), 1, groups)
        self.assertEqual(sorted(groups[0]),
                         sorted(s["id"] for s in self.plan["shards"]))
        self.assertEqual(self.plan["max_parallelism"], 2)
        for s in self.plan["shards"]:
            self.assertEqual(s["parallel_group"], 0)
            self.assertEqual(s["depends_on"], [])

    def test_zero_shared_owned_files(self):
        owners = {}
        for s in self.plan["shards"]:
            for f in s["owns_files"]:
                self.assertNotIn(f, owners,
                                 f"{f} owned by both {owners.get(f)} and {s['id']}")
                owners[f] = s["id"]
        for s in self.plan["shards"]:
            self.assertEqual(s["shared_files_readonly"], [])

    def test_each_shard_has_a_bundle(self):
        by_id = shards_by_id(self.plan)
        for sid, s in by_id.items():
            bdir = self.out / s["bundle"]
            self.assertTrue((bdir / "manifest.json").is_file(), sid)
            self.assertTrue((bdir / "PROMPT.md").is_file(), sid)
            for f in s["owns_files"]:
                self.assertTrue((bdir / "files" / f).is_file(), f"{sid}:{f}")


if __name__ == "__main__":
    unittest.main()
