"""Deepen tests (Oct 18, 2026): full Scope-pack citation.

Before this pass, load_scope_pack read a supplied GhostScope
pack's changed-file list and risk reasons, then dropped the rest
of what the pack records: its reading order, per-file changed
symbols, covering tests and direct caller counts, and its pack
totals. The changed-file list was also never compared with the
diff actually reviewed, so a pack built for a different change
was cited as if it described this one.

These tests pin the deepened citation: every added fact is copied
from scope.json or counted from the two supplied lists, the
reconciliation never becomes a risk flag and never changes the
verdict, and an absent changed-file list claims no comparison.
Unit-level, same style as tests/test_polish.py.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostreview.core import build_review, reconcile_scope  # noqa: E402
from ghostreview.inputs import load_scope_pack              # noqa: E402
from ghostreview.reports import render_markdown             # noqa: E402

FIXTURE_SCOPE = (Path(__file__).resolve().parent / "fixtures"
                 / "reports" / "scope.json")


def _proj(files):
    td = Path(tempfile.mkdtemp(prefix="gr-deepen-"))
    for rel, content in files.items():
        fp = td / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    return td


def _diff_for(*paths):
    return "".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n"
        f"@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n" for p in paths)


class TestScopeReaderDeepen(unittest.TestCase):
    def setUp(self):
        self.proj = _proj({"a.py": "x = 1\n"})
        self.addCleanup(lambda: shutil.rmtree(self.proj, ignore_errors=True))

    def _pack(self, data):
        sp = self.proj / "scope.json"
        sp.write_text(json.dumps(data))
        return load_scope_pack(str(sp))

    def test_real_fixture_pack_fields_are_cited(self):
        rec = load_scope_pack(str(FIXTURE_SCOPE))
        self.assertTrue(rec["present"])
        self.assertEqual(rec["changed_symbols_by_file"],
                         {"pricing.py": ["compute_total"]})
        # The fixture records covering_tests explicitly as []:
        # kept as an empty entry, not dropped as "not recorded".
        self.assertEqual(rec["covering_tests_by_file"], {"pricing.py": []})
        self.assertEqual(rec["direct_callers_by_file"], {"pricing.py": 6})
        self.assertEqual(rec["reading_order"],
                         [{"path": "pricing.py", "order": 1, "mode": "full"}])
        self.assertEqual(rec["reading_order_paths"], ["pricing.py"])
        self.assertEqual(rec["pack_files"], 1)
        self.assertEqual(rec["pack_tokens_estimate"], 120)

    def test_reading_order_is_sorted_by_recorded_order(self):
        rec = self._pack({"reading_order": [
            {"path": "b.py", "order": 2, "mode": "full"},
            {"path": "a.py", "order": 1, "mode": "signatures"}]})
        self.assertEqual(rec["reading_order_paths"], ["a.py", "b.py"])
        self.assertEqual(rec["reading_order"][0]["mode"], "signatures")

    def test_per_file_facts_merge_across_lists_without_duplicates(self):
        rec = self._pack({
            "changed": [{"path": "a.py", "changed_symbols": ["f"],
                         "covering_tests": ["tests/test_a.py"]}],
            "files": [{"path": "a.py", "changed_symbols": ["f", "g"],
                       "covering_tests": ["tests/test_a.py"],
                       "direct_callers": 3}]})
        self.assertEqual(rec["changed_symbols_by_file"], {"a.py": ["f", "g"]})
        self.assertEqual(rec["covering_tests_by_file"],
                         {"a.py": ["tests/test_a.py"]})
        self.assertEqual(rec["direct_callers_by_file"], {"a.py": 3})

    def test_pack_without_new_fields_still_loads(self):
        rec = self._pack({"files": [{"path": "a.py",
                                     "risk_reasons": ["exported API"]}]})
        self.assertEqual(rec["changed_symbols_by_file"], {})
        self.assertEqual(rec["covering_tests_by_file"], {})
        self.assertEqual(rec["reading_order"], [])
        self.assertIsNone(rec["pack_files"])
        self.assertIsNone(rec["pack_tokens_estimate"])


class TestScopeReconciliation(unittest.TestCase):
    def setUp(self):
        self.proj = _proj({"a.py": "x = 1\n", "b.py": "y = 1\n",
                           "c.py": "z = 1\n"})
        self.addCleanup(lambda: shutil.rmtree(self.proj, ignore_errors=True))

    def _review(self, diff_paths, pack_files):
        sp = self.proj / "scope.json"
        sp.write_text(json.dumps(
            {"files": [{"path": p} for p in pack_files]}))
        return build_review(self.proj, _diff_for(*diff_paths), "file:x",
                            scope_pack=str(sp))

    def test_full_agreement(self):
        rep = self._review(["a.py"], ["a.py"])
        rec = rep["scope"]["reconciliation"]
        self.assertTrue(rec["scope_files_recorded"])
        self.assertEqual(rec["matched"], ["a.py"])
        self.assertEqual(rec["only_in_scope"], [])
        self.assertEqual(rec["only_in_diff"], [])
        self.assertIn("agree on 1 file(s)", rep["verdict_summary"])

    def test_mismatch_is_listed_both_ways(self):
        rep = self._review(["a.py", "b.py"], ["a.py", "c.py"])
        rec = rep["scope"]["reconciliation"]
        self.assertEqual(rec["matched"], ["a.py"])
        self.assertEqual(rec["only_in_scope"], ["c.py"])
        self.assertEqual(rec["only_in_diff"], ["b.py"])
        md = render_markdown(rep)
        self.assertIn("Scope reconciliation: 1 file(s) appear in both", md)
        self.assertIn("listed only in the pack: `c.py`", md)
        self.assertIn("in this diff only: `b.py`", md)

    def test_mismatch_never_flags_or_changes_verdict(self):
        # A pack for a wholly different change: the discrepancy is
        # cited, but no risk flag is invented and the verdict is
        # exactly what the diff alone would produce.
        rep = self._review(["a.py"], ["c.py"])
        plain = build_review(self.proj, _diff_for("a.py"), "file:x")
        self.assertEqual(rep["verdict"], plain["verdict"])
        self.assertEqual(rep["risks"], plain["risks"])
        self.assertNotIn("SCOPE", [r["rule"] for r in rep["risks"]])

    def test_no_changed_file_list_claims_no_comparison(self):
        sp = self.proj / "scope.json"
        sp.write_text(json.dumps({"tool": "ghostscope"}))
        rep = build_review(self.proj, _diff_for("a.py"), "file:x",
                           scope_pack=str(sp))
        rec = rep["scope"]["reconciliation"]
        self.assertFalse(rec["scope_files_recorded"])
        self.assertEqual(rec["only_in_diff"], [])
        self.assertIn("no changed-file list", render_markdown(rep))
        self.assertNotIn("agree on", rep["verdict_summary"])

    def test_no_pack_means_no_reconciliation(self):
        self.assertIsNone(reconcile_scope({"present": False}, ["a.py"]))
        rep = build_review(self.proj, _diff_for("a.py"), "file:x")
        self.assertNotIn("reconciliation", rep["scope"])

    def test_reconciliation_present_even_when_diff_unreviewable(self):
        sp = self.proj / "scope.json"
        sp.write_text(json.dumps({"files": [{"path": "a.py"}]}))
        rep = build_review(self.proj, "", "file:x", scope_pack=str(sp))
        self.assertEqual(rep["verdict"], "could-not-review")
        rec = rep["scope"]["reconciliation"]
        self.assertEqual(rec["only_in_scope"], ["a.py"])
        self.assertEqual(rec["diff_file_count"], 0)


class TestScopeCitationInReport(unittest.TestCase):
    def setUp(self):
        self.proj = _proj({"pricing.py": "def compute_total():\n    return 1\n",
                           "app.py": "import pricing\n"})
        self.addCleanup(lambda: shutil.rmtree(self.proj, ignore_errors=True))

    def test_fixture_pack_is_fully_rendered(self):
        diff = _diff_for("pricing.py")
        rep = build_review(self.proj, diff, "file:x",
                           scope_pack=str(FIXTURE_SCOPE))
        md = render_markdown(rep)
        self.assertIn("Scope reading order: 1. `pricing.py` (full)", md)
        self.assertIn("Scope detail for `pricing.py`", md)
        self.assertIn("changed symbols recorded: `compute_total`", md)
        self.assertIn("covering tests recorded: none", md)
        self.assertIn("direct callers recorded: 6", md)
        self.assertIn("120 pack tokens estimated by GhostScope", md)
        self.assertIn("agree on 1 file(s)", rep["verdict_summary"])
        # The deepened citation is in review.json too, not prose only.
        blob = json.dumps(rep)
        self.assertIn('"reading_order"', blob)
        self.assertIn('"reconciliation"', blob)


if __name__ == "__main__":
    unittest.main()
