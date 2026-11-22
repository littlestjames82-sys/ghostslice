"""Deepen lane: schedule analytics (critical path / makespan /
bottleneck) are planning-side only. They must agree with the shards
as written, be validated by `check`, and never imply dispatch."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ghostshard.bundles import compute_schedule_analytics  # noqa: E402

from tests.helpers import (FIXTURES, check_folder, core_available,  # noqa: E402
                           plan_project, run_cli)


def S(sid, tokens, deps=(), group=0):
    return {"id": sid, "estimated_tokens": tokens,
            "depends_on": list(deps), "parallel_group": group}


class TestAnalyticsUnit(unittest.TestCase):
    def test_chain_critical_path_sums_the_chain(self):
        a = compute_schedule_analytics(
            [S("a", 10), S("b", 20, ["a"], 1), S("c", 5, ["b"], 2)])
        self.assertEqual(a["critical_path"], ["a", "b", "c"])
        self.assertEqual(a["critical_path_tokens"], 35)
        self.assertEqual(a["makespan_tokens"], 35)
        self.assertEqual(a["total_work_tokens"], 35)
        self.assertEqual(a["parallel_speedup"], 1.0)
        self.assertFalse(a["has_cycle"])

    def test_diamond_picks_heavier_branch_and_speedup(self):
        a = compute_schedule_analytics([
            S("a", 10), S("b", 30, ["a"], 1), S("c", 5, ["a"], 1),
            S("d", 10, ["b", "c"], 2)])
        self.assertEqual(a["critical_path"], ["a", "b", "d"])
        self.assertEqual(a["critical_path_tokens"], 50)
        self.assertEqual(a["total_work_tokens"], 55)
        self.assertEqual(a["parallel_speedup"], round(55 / 50, 3))
        self.assertEqual(a["bottleneck"], {"shard": "b", "estimated_tokens": 30})
        self.assertEqual(a["group_makespan_tokens"], {"0": 10, "1": 30, "2": 10})

    def test_disjoint_speedup_and_deterministic_tiebreak(self):
        a = compute_schedule_analytics([S("z", 10), S("a", 10)])
        self.assertEqual(a["critical_path"], ["a"])  # smallest path on tie
        self.assertEqual(a["parallel_speedup"], 2.0)

    def test_cycle_is_reported_not_scheduled(self):
        a = compute_schedule_analytics([S("a", 10, ["b"]), S("b", 10, ["a"])])
        self.assertTrue(a["has_cycle"])
        self.assertEqual(a["critical_path"], [])
        self.assertIsNone(a["makespan_tokens"])

    def test_empty_and_unknown_deps_are_safe(self):
        self.assertEqual(compute_schedule_analytics([])["total_work_tokens"], 0)
        a = compute_schedule_analytics([S("a", 7, ["ghost"])])
        self.assertEqual(a["critical_path"], ["a"])


@unittest.skipUnless(core_available(), "GhostShard core not present")
class TestAnalyticsEndToEnd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_disjoint_plan_analytics_match_shards(self):
        proc, out, plan = plan_project(
            self.tmp, "disjoint", task="alpha summary and beta export")
        self.assertIsNotNone(plan, proc.stderr)
        a = plan["analytics"]
        total = sum(s["estimated_tokens"] for s in plan["shards"])
        self.assertEqual(a["total_work_tokens"], total)
        self.assertEqual(a["total_work_tokens"], plan["totals"]["estimated_tokens"])
        # disjoint shards: critical path is the single heaviest shard
        self.assertEqual(a["critical_path_length"], 1)
        self.assertEqual(a["critical_path_tokens"],
                         max(s["estimated_tokens"] for s in plan["shards"]))
        if len(plan["shards"]) > 1 and a["critical_path_tokens"] < total:
            self.assertGreater(a["parallel_speedup"], 1.0)
        self.assertIn("not a wall-clock prediction", a["basis"])
        md = (out / "PLAN.md").read_text(encoding="utf-8")
        self.assertIn("## Schedule analysis", md)
        self.assertIn("Critical path:", md)

    def test_shared_plan_critical_path_follows_dependency(self):
        proc, out, plan = plan_project(
            self.tmp, "shared", task_file=FIXTURES / "shared" / "tasks.md")
        self.assertIsNotNone(plan, proc.stderr)
        a = plan["analytics"]
        by_id = {s["id"]: s for s in plan["shards"]}
        path = a["critical_path"]
        # every step after the first must depend on its predecessor
        for prev, cur in zip(path, path[1:]):
            self.assertIn(prev, by_id[cur]["depends_on"])
        self.assertEqual(a["critical_path_tokens"],
                         sum(by_id[i]["estimated_tokens"] for i in path))
        # a fresh plan with analytics passes check
        res = check_folder(out)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_check_rejects_tampered_analytics(self):
        proc, out, plan = plan_project(
            self.tmp, "disjoint", task="alpha summary and beta export")
        self.assertIsNotNone(plan, proc.stderr)
        plan["analytics"]["parallel_speedup"] = 999.0
        (out / "shards.json").write_text(json.dumps(plan, indent=2),
                                         encoding="utf-8")
        res = check_folder(out)
        self.assertEqual(res.returncode, 1)
        self.assertIn("analytics mismatch", res.stdout)

    def test_analytics_never_enables_dispatch(self):
        proc, out, plan = plan_project(
            self.tmp, "disjoint", task="alpha summary and beta export")
        self.assertIsNotNone(plan, proc.stderr)
        bus = json.loads((out / "bus-manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(bus["jobs"])
        self.assertTrue(all(j["dispatch"] is False for j in bus["jobs"]))


if __name__ == "__main__":
    unittest.main()
