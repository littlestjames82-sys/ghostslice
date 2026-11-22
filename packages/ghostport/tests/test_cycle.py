"""Layer 2 (core black-box): import cycle handling, PLAN.md MVP item 2.

A cycle in the touched set must port together as ONE combined unit and be
named in the plan (as a combined unit and/or a blocker), never ordered
arbitrarily as if one side came first.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import (  # noqa: E402
    CORE_AVAILABLE, PACK_ID, SKIP_CORE, copy_fixture, load_expected,
    run_cli, unit_file_lists,
)


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestCycle(unittest.TestCase):
    def test_cycle_members_combined_and_named(self):
        expected = load_expected("cycle_project", "expected_cycle.json")
        members = sorted(expected["cycle_members"])
        with tempfile.TemporaryDirectory() as tmp:
            proj = copy_fixture("cycle_project", pathlib.Path(tmp))
            proc = run_cli(["plan", str(proj), "--pack", PACK_ID])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            plan = json.loads((proj / "port-plan.json").read_text(encoding="utf-8"))
            units = unit_file_lists(plan)
            containing = [u for u in units if any(m in u for m in members)]
            # Both members in exactly one shared unit.
            self.assertEqual(len(containing), 1, f"cycle split across units: {units}")
            self.assertEqual(sorted(containing[0]), members)
            # And the cycle is named somewhere human/machine visible.
            plan_md = (proj / "PORT_PLAN.md").read_text(encoding="utf-8")
            blob = (plan_md + json.dumps(plan)).lower()
            self.assertIn("cycle", blob)
            for member in members:
                self.assertIn(member, plan_md + json.dumps(plan))


if __name__ == "__main__":
    unittest.main()
