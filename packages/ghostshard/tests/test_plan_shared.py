"""Verification bar: shared-symbol fixture must sequence or name
a conflict, never produce two owners (PLAN.md).

report.py and export.py both import normalize_records from
shared_core.py; the task file pre-splits report/export subtasks.
"""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import FIXTURES, core_available, plan_project


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestSharedSymbol(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # task file lives OUTSIDE the copied project so its .md text
        # is not scanned as project code
        self.proc, self.out, self.plan = plan_project(
            self.tmp, "shared", task_file=FIXTURES / "shared" / "tasks.md")

    def tearDown(self):
        self._tmp.cleanup()

    def test_plan_produced(self):
        self.assertIsNotNone(self.plan, self.proc.stderr)

    def test_shared_file_has_exactly_one_owner(self):
        owners = [s["id"] for s in self.plan["shards"]
                  if "shared_core.py" in s["owns_files"]]
        self.assertEqual(len(owners), 1,
                         f"shared_core.py owners: {owners} (all shards: "
                         f"{[(s['id'], s['owns_files']) for s in self.plan['shards']]})")
        self.owner = owners[0]

    def test_no_file_has_two_owners(self):
        seen = {}
        for s in self.plan["shards"]:
            for f in s["owns_files"]:
                self.assertNotIn(f, seen, f"{f} doubly owned")
                seen[f] = s["id"]

    def test_other_shard_sequenced_or_conflict_named(self):
        owners = [s for s in self.plan["shards"]
                  if "shared_core.py" in s["owns_files"]]
        self.assertEqual(len(owners), 1)
        owner_id = owners[0]["id"]
        others = [s for s in self.plan["shards"] if s["id"] != owner_id]
        self.assertTrue(others, "expected at least one non-owner shard")
        conflicts_text = "\n".join(self.plan.get("conflicts", []))
        conflict_names_shared = ("shared_core" in conflicts_text
                                 or "normalize" in conflicts_text)
        for s in others:
            sequenced = owner_id in s["depends_on"]
            has_shared_context = "shared_core.py" in s["shared_files_readonly"]
            self.assertTrue(
                sequenced or conflict_names_shared,
                f"{s['id']} neither depends_on owner {owner_id} nor is "
                f"the collision named in conflicts: {conflicts_text!r}")
            if sequenced:
                # a sequenced shard cannot sit in the owner's group
                self.assertNotEqual(s["parallel_group"],
                                    owners[0]["parallel_group"])
            if has_shared_context and s["shared_symbols"]:
                # the shared file arrives as named symbols, not a blob
                self.assertIn("normalize_records", s["shared_symbols"])


if __name__ == "__main__":
    unittest.main()
