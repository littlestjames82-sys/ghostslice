"""Layer 2 (core black-box): scan behaviour per PLAN.md MVP item 1.

Skipped, with the reason in REPORT_B.md, until the ghostport core lands.
When the core is present these tests enforce the plan's verification bar:
each pattern hits its positive fixture, NO pattern hits its look-alike
negative (any false hit fails the build), and a clean project reports the
honest negative plus its not-covered languages.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import (  # noqa: E402
    CORE_AVAILABLE, FIXTURES, PACK_ID, SKIP_CORE, copy_fixture, load_expected,
    run_cli,
)


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestScanPatterns(unittest.TestCase):
    def _scan_text(self, project: pathlib.Path) -> str:
        proc = run_cli(["scan", str(project), "--pack", PACK_ID])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout + proc.stderr

    def test_each_positive_fixture_is_hit_with_its_pattern_id(self):
        expected = load_expected("patterns", "expected.json")
        with tempfile.TemporaryDirectory() as tmp:
            proj = copy_fixture("patterns", pathlib.Path(tmp)) / "positive"
            out = self._scan_text(proj)
            for entry in expected["patterns"]:
                with self.subTest(pattern=entry["pattern_id"]):
                    self.assertIn(entry["file"], out)
                    self.assertIn(entry["pattern_id"], out)

    def test_no_negative_fixture_is_hit(self):
        expected = load_expected("patterns", "expected.json")
        with tempfile.TemporaryDirectory() as tmp:
            proj = copy_fixture("patterns", pathlib.Path(tmp)) / "negative"
            out = self._scan_text(proj)
            for entry in expected["patterns"]:
                with self.subTest(pattern=entry["pattern_id"]):
                    self.assertNotIn(entry["pattern_id"], out)

    def test_clean_project_reports_zero_hits_and_not_covered(self):
        expected = load_expected("clean_project", "expected_clean.json")
        with tempfile.TemporaryDirectory() as tmp:
            proj = copy_fixture("clean_project", pathlib.Path(tmp))
            out = self._scan_text(proj)
            lowered = out.lower()
            # PLAN.md risks: say "hits for pack X" and keep the honesty
            # negation ("does NOT mean ... ready to upgrade").
            self.assertIn(expected["required_phrasing"], lowered)
            self.assertIn(expected["required_honesty_marker"], lowered)
            for phrase in expected["forbidden_phrases"]:
                self.assertNotIn(phrase, lowered)
            for lang in expected["not_covered_languages"]:
                self.assertIn(lang, lowered)


@unittest.skipUnless(CORE_AVAILABLE, SKIP_CORE)
class TestScanFixtureCopiesStayPristine(unittest.TestCase):
    def test_scan_does_not_write_into_the_scanned_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = copy_fixture("clean_project", pathlib.Path(tmp))
            before = sorted(p.relative_to(proj) for p in proj.rglob("*"))
            run_cli(["scan", str(proj), "--pack", PACK_ID])
            after = sorted(p.relative_to(proj) for p in proj.rglob("*"))
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
