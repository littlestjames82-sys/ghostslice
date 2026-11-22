"""Layer 2 (core black-box): per-unit bundle, PLAN.md MVP item 3.

A unit bundle must contain the unit in full, a UNIT.md checklist naming
the patterns to fix with locations, contract notes, and a state box the
GhostVerify step fills later. Port never performs the migration itself:
the bundle step must not modify the source project.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import (  # noqa: E402
    CORE_AVAILABLE, PACK_ID, SKIP_CORE, copy_fixture, run_cli,
    unit_file_lists,
)


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestBundle(unittest.TestCase):
    def _first_unit(self, proj: pathlib.Path) -> tuple[str, list[str]]:
        proc = run_cli(["plan", str(proj), "--pack", PACK_ID])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = json.loads((proj / "port-plan.json").read_text(encoding="utf-8"))
        units = plan["units"]
        first = units[0]
        uid = str(first.get("id") or first.get("unit") or "1")
        return uid, unit_file_lists(plan)[0]

    def test_bundle_writes_unit_md_and_leaves_source_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = copy_fixture("ordering_project", pathlib.Path(tmp))
            before = {
                p.relative_to(proj): p.read_bytes()
                for p in proj.rglob("*.py")
            }
            uid, files = self._first_unit(proj)
            out_dir = pathlib.Path(tmp) / "bundle-out"
            proc = run_cli(["bundle", str(proj), "--unit", uid, "-o", str(out_dir)])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(out_dir.is_dir())
            unit_md = out_dir / "UNIT.md"
            self.assertTrue(unit_md.is_file(), "bundle must include UNIT.md")
            text = unit_md.read_text(encoding="utf-8")
            for f in files:
                self.assertIn(pathlib.Path(f).name, text)
            # State box exists and starts unverified.
            self.assertIn("verified", text.lower())
            # Planner only: source .py files are byte-identical afterwards.
            after = {
                p.relative_to(proj): p.read_bytes()
                for p in proj.rglob("*.py")
            }
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
