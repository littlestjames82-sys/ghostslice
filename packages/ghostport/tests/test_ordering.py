"""Layer 2 (core black-box): dependency ordering, PLAN.md MVP item 2.

Verification bar from the plan: on a fixture graph, no unit is sequenced
before a touched dependency it calls/imports; cycles are combined and
named (see test_cycle.py for the cycle half).
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import (  # noqa: E402
    CORE_AVAILABLE, PACK_ID, SKIP_CORE, copy_fixture, flatten,
    load_expected, run_cli, unit_file_lists,
)


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestOrdering(unittest.TestCase):
    def _plan(self, proj: pathlib.Path) -> dict:
        proc = run_cli(["plan", str(proj), "--pack", PACK_ID])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan_file = proj / "port-plan.json"
        self.assertTrue(plan_file.is_file(), "plan must write port-plan.json")
        self.assertTrue((proj / "PORT_PLAN.md").is_file(), "plan must write PORT_PLAN.md")
        return json.loads(plan_file.read_text(encoding="utf-8"))

    def test_leaves_first_on_import_chain(self):
        expected = load_expected("ordering_project", "expected_order.json")
        with tempfile.TemporaryDirectory() as tmp:
            proj = copy_fixture("ordering_project", pathlib.Path(tmp))
            plan = self._plan(proj)
            ordered_files = flatten(unit_file_lists(plan))
            wanted = expected["units_leaves_first"]
            positions = {name: ordered_files.index(name) for name in wanted}
            self.assertLess(positions["pkg/leaf.py"], positions["pkg/mid.py"])
            self.assertLess(positions["pkg/mid.py"], positions["pkg/app.py"])

    def test_covering_tests_attached_where_known(self):
        expected = load_expected("ordering_project", "expected_order.json")
        with tempfile.TemporaryDirectory() as tmp:
            proj = copy_fixture("ordering_project", pathlib.Path(tmp))
            plan_text = json.dumps(self._plan(proj))
            for unit_file, tests in expected["covering_tests"].items():
                self.assertIn(unit_file, plan_text)
                for test_file in tests:
                    self.assertIn(test_file, plan_text)


if __name__ == "__main__":
    unittest.main()
