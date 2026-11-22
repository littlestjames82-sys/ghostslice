"""State integrity: resume-from-ledger, PLAN.md MVP items 3-4.

The resume fixture seeds `.ghostport-history.jsonl` (events: planned,
bundled, and a ported-claimed CLAIM for the leaf unit; planned for the
app unit) plus a minimal `port-plan.json` in the shape core's
`build_status` consumes (unit ids are core's `unit-<slug>` form).

The plan's verification bar: status shows **zero verified units** until
a GhostVerify report exists in the ledger chain. A claim is not
verification. Latest state wins per unit, so the expected status counts
are planned 1 (app), ported-claimed 1 (leaf), verified 0, and the next
unit is the app unit.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import (  # noqa: E402
    CORE_AVAILABLE, FIXTURES, SKIP_CORE, copy_fixture, load_expected,
    parse_json_output, run_cli,
)


class TestResumeFixtureContract(unittest.TestCase):
    def test_expected_status_matches_ledger_contents(self):
        expected = load_expected("resume_project", "expected_status.json")
        ledger = FIXTURES / "resume_project" / ".ghostport-history.jsonl"
        entries = [json.loads(l) for l in ledger.read_text(encoding="utf-8").strip().splitlines()]
        event_counts: dict[str, int] = {}
        latest: dict[str, str] = {}
        for entry in entries:
            event_counts[entry["state"]] = event_counts.get(entry["state"], 0) + 1
            latest[entry["unit"]] = entry["state"]
            # No entry in this fixture may rest on a Verify report.
            self.assertFalse(entry.get("verify_report"), entry)
        for state, count in expected["ledger_events"].items():
            self.assertEqual(event_counts.get(state, 0), count, state)
        latest_counts: dict[str, int] = {}
        for state in latest.values():
            latest_counts[state] = latest_counts.get(state, 0) + 1
        for state, count in expected["status_counts_latest_state"].items():
            self.assertEqual(latest_counts.get(state, 0), count, state)
        self.assertNotIn("verified", latest.values())


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestStatusCommand(unittest.TestCase):
    def test_status_shows_zero_verified_without_verify_report(self):
        expected = load_expected("resume_project", "expected_status.json")
        with tempfile.TemporaryDirectory() as tmp:
            proj = copy_fixture("resume_project", pathlib.Path(tmp))
            proc = run_cli(["status", str(proj), "--json"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = parse_json_output(proc)
            self.assertEqual(data["verified_units"], expected["verified_units"])
            counts = data["counts"]
            self.assertEqual(counts.get("verified", 0), 0)
            self.assertEqual(
                counts.get("ported-claimed", 0),
                expected["status_counts_latest_state"]["ported-claimed"],
            )
            self.assertEqual(data["next_unit"], expected["next_unit"])

    def test_status_text_never_declares_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = copy_fixture("resume_project", pathlib.Path(tmp))
            proc = run_cli(["status", str(proj)])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("migration complete", (proc.stdout + proc.stderr).lower())
            self.assertIn("Verified units: 0", proc.stdout)


if __name__ == "__main__":
    unittest.main()
