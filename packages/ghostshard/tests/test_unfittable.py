"""Fixture: unfittable. One 20k-char file planned with a 250-token
per-shard budget must be reported honestly: non-zero exit, plan
marked partial, or a shard flagged unfittable with a reason.
Never a clean-looking complete plan, never silent truncation.
"""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import FIXTURES, core_available, plan_project


@unittest.skipUnless(core_available(), "GhostShard core (Agent A) not present")
class TestUnfittable(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        task = (FIXTURES / "unfittable" / "TASK.txt").read_text(
            encoding="utf-8").strip()
        self.proc, self.out, self.plan = plan_project(
            self.tmp, "unfittable", task=task, budget=250)

    def tearDown(self):
        self._tmp.cleanup()

    def test_hub_is_the_only_owned_file(self):
        self.assertIsNotNone(self.plan, self.proc.stderr)
        owned = [f for s in self.plan["shards"] for f in s["owns_files"]]
        self.assertEqual(owned, ["hub.py"])

    def test_plan_admits_it_does_not_fit(self):
        self.assertIsNotNone(self.plan, self.proc.stderr)
        signals = []
        if self.proc.returncode != 0:
            signals.append(f"exit {self.proc.returncode}")
        if self.plan.get("partial"):
            signals.append("partial=True")
        unfit = [s["id"] for s in self.plan["shards"] if s.get("unfittable")]
        if unfit:
            signals.append(f"unfittable shards: {unfit}")
        conflicts = "\n".join(self.plan.get("conflicts", []))
        if "unfittable" in conflicts and "hub.py" in conflicts:
            signals.append("conflict names hub.py as unfittable")
        self.assertTrue(signals,
                        f"no honest unfittable signal: rc={self.proc.returncode} "
                        f"partial={self.plan.get('partial')} "
                        f"shards={self.plan['shards']} conflicts={conflicts!r}")
        # and every claimed signal must be consistent: a fitting,
        # complete plan may not also be returned as exit 0 clean
        if self.proc.returncode == 0:
            self.assertTrue(self.plan.get("partial") or unfit,
                            "exit 0 with no partial/unfittable marking")

    def test_nothing_silently_dropped(self):
        self.assertIsNotNone(self.plan, self.proc.stderr)
        # hub.py still exists in exactly one bundle, whole
        bundles = [self.out / s["bundle"] for s in self.plan["shards"]]
        found = [b / "files" / "hub.py" for b in bundles
                 if (b / "files" / "hub.py").is_file()]
        self.assertEqual(len(found), 1)
        src_len = len((FIXTURES / "unfittable" / "hub.py").read_text(
            encoding="utf-8"))
        self.assertEqual(len(found[0].read_text(encoding="utf-8")), src_len)


if __name__ == "__main__":
    unittest.main()
