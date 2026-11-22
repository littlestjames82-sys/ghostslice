"""Layer 1: fixture integrity. Runs with or without the core package.

These tests pin the *fixtures* to PLAN.md's verification bar, so a later
core failure cannot be a fixture failure in disguise:

* every pattern in the first pack has one positive fixture that really
  contains its trigger and one look-alike negative that really does not;
* every fixture is valid Python (a broken fixture proves nothing);
* ordering / cycle / resume / clean fixture projects encode exactly the
  structures their expected_*.json files claim.
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import FIXTURES, load_expected  # noqa: E402

PATTERNS = FIXTURES / "patterns"

# Trigger substrings that must appear in each positive fixture and must
# NOT appear in the matching look-alike negative. Kept deliberately
# textual: the fixture's job is to present (or not present) the pattern.
TRIGGERS = {
    "collections_abc.py": ["from collections import", "collections.MutableSequence"],
    "inspect_getargspec.py": ["inspect.getargspec"],
    "threading_camelcase.py": ["threading.currentThread(", "threading.activeCount("],
    "asyncio_coroutine.py": ["asyncio.coroutine"],
    "fractions_gcd.py": ["fractions.gcd", "from fractions import gcd"],
    "unittest_aliases.py": [".failUnless(", ".assertEquals("],
    "safe_config_parser.py": ["SafeConfigParser"],
    "imp_module.py": ["import imp\n"],
    "distutils_use.py": ["import distutils", "from distutils.core import"],
    "ssl_wrap_socket.py": ["ssl.wrap_socket(", "ssl.match_hostname("],
    "typing_pseudo_modules.py": ["import typing.io", "import typing.re"],
    "locale_getdefaultlocale.py": ["locale.getdefaultlocale("],
    "datetime_utcnow.py": [".utcnow(", ".utcfromtimestamp("],
}


class TestPatternFixtures(unittest.TestCase):
    def setUp(self):
        self.expected = load_expected("patterns", "expected.json")

    def test_expected_covers_one_positive_and_one_negative_per_pattern(self):
        for entry in self.expected["patterns"]:
            fname = entry["file"]
            self.assertTrue((PATTERNS / "positive" / fname).is_file(), fname)
            self.assertTrue((PATTERNS / "negative" / fname).is_file(), fname)

    def test_proposed_patterns_also_have_fixture_pairs(self):
        for entry in self.expected.get("proposed_patterns", []):
            fname = entry["file"]
            self.assertTrue((PATTERNS / "positive" / fname).is_file(), fname)
            self.assertTrue((PATTERNS / "negative" / fname).is_file(), fname)

    def test_every_pattern_has_a_dated_reference(self):
        # PLAN.md: "An undated pattern is a bug."
        for entry in self.expected["patterns"]:
            self.assertTrue(entry["reference"], entry["slug"])
            self.assertRegex(entry["reference_date"], r"^\d{4}-\d{2}-\d{2}$", entry["slug"])
            self.assertTrue(entry["description"], entry["slug"])
            self.assertTrue(entry["pattern_id"], entry["slug"])

    def test_pattern_ids_unique(self):
        ids = [e["pattern_id"] for e in self.expected["patterns"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_positives_contain_their_trigger(self):
        for fname, triggers in TRIGGERS.items():
            text = (PATTERNS / "positive" / fname).read_text(encoding="utf-8")
            for needle in triggers:
                self.assertIn(needle, text, f"{fname} positive missing {needle!r}")

    def test_negatives_are_lookalikes_without_the_trigger(self):
        for fname, triggers in TRIGGERS.items():
            text = (PATTERNS / "negative" / fname).read_text(encoding="utf-8")
            for needle in triggers:
                self.assertNotIn(needle, text, f"{fname} negative leaks {needle!r}")

    def test_all_pattern_fixtures_parse_as_python(self):
        for side in ("positive", "negative"):
            for path in sorted((PATTERNS / side).glob("*.py")):
                with self.subTest(path=str(path)):
                    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


class TestProjectFixtureStructures(unittest.TestCase):
    def test_ordering_project_import_chain(self):
        proj = FIXTURES / "ordering_project"
        app = (proj / "pkg/app.py").read_text(encoding="utf-8")
        mid = (proj / "pkg/mid.py").read_text(encoding="utf-8")
        leaf = (proj / "pkg/leaf.py").read_text(encoding="utf-8")
        self.assertIn("from pkg.mid import", app)
        self.assertIn("from pkg.leaf import", mid)
        self.assertNotIn("from pkg.", leaf)
        expected = load_expected("ordering_project", "expected_order.json")
        self.assertEqual(
            expected["units_leaves_first"],
            ["pkg/leaf.py", "pkg/mid.py", "pkg/app.py"],
        )

    def test_cycle_project_is_a_real_two_node_cycle(self):
        proj = FIXTURES / "cycle_project"
        x = (proj / "cyc/x.py").read_text(encoding="utf-8")
        y = (proj / "cyc/y.py").read_text(encoding="utf-8")
        self.assertIn("from cyc.y import", x)
        self.assertIn("from cyc.x import", y)
        expected = load_expected("cycle_project", "expected_cycle.json")
        self.assertEqual(sorted(expected["cycle_members"]), ["cyc/x.py", "cyc/y.py"])

    def test_resume_ledger_has_claims_and_no_verify_report(self):
        proj = FIXTURES / "resume_project"
        lines = (proj / ".ghostport-history.jsonl").read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines]
        states = [e["state"] for e in entries]
        self.assertIn("planned", states)
        self.assertIn("bundled", states)
        self.assertIn("ported-claimed", states)
        # The whole point of this fixture: nothing here may count as verified.
        self.assertNotIn("verified", states)
        for entry in entries:
            self.assertFalse(entry.get("verify_report"), entry)

    def test_clean_project_has_no_triggers_but_has_an_uncovered_language(self):
        proj = FIXTURES / "clean_project"
        modern = (proj / "modern.py").read_text(encoding="utf-8")
        for triggers in TRIGGERS.values():
            for needle in triggers:
                self.assertNotIn(needle, modern)
        self.assertTrue((proj / "web/app.js").is_file())
        ast.parse(modern)


if __name__ == "__main__":
    unittest.main()
