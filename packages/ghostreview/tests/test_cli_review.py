"""CLI tests for GhostReview: plain-English review of a diff.

Contract pinned here (see REPORT_B.md for the assumptions):
- Outputs: REVIEW.md (human, plain English) + review.json
  (machine-readable), static evidence only.
- Flags: test edits, secrets paths, large deletions.
- A clean small diff exits 0; malformed or missing input never
  exits 0 silently; the project tree is never modified.
- Secret VALUES are never printed: paths and types only, matching
  the family rule. The fixture fake secret must not appear in any
  output.
All tests skip cleanly while no ghostreview CLI is discoverable.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

D = helpers.DIFFS


@unittest.skipUnless(helpers.cli_available(),
                     "ghostreview CLI not discoverable (see REPORT_B.md)")
class TestReviewCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gr-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.project = helpers.copy_project(self.tmp / "project")
        self.out = self.tmp / "out"

    def _review(self, diff, **kw):
        return helpers.run_review(self.project, diff, self.out, **kw)

    def _all_text(self, proc):
        return (proc.stdout + proc.stderr + "\n" +
                helpers.review_text(self.out, [self.project]))

    # -- happy path -------------------------------------------------
    def test_clean_diff_exits_0_and_writes_both_outputs(self):
        proc = self._review(D / "clean_small.diff")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        rj, md = helpers.find_outputs(self.out, [self.project])
        self.assertIsNotNone(rj, "review.json not written")
        self.assertIsNotNone(md, "REVIEW.md not written")
        data = json.loads(rj.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)

    def test_clean_review_names_the_file_in_plain_english(self):
        proc = self._review(D / "clean_small.diff")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self._all_text(proc)
        self.assertIn("pricing.py", text)
        low = text.lower()
        self.assertTrue(
            any(w in low for w in ("changed", "modified", "change")),
            f"review does not describe the change in words: {text[:400]}")
        # Static-evidence honesty: the review must say its evidence
        # is static somewhere, and must never claim approval.
        self.assertIn("static", low)
        self.assertNotIn("safe to merge", low)
        self.assertNotIn("approved for merge", low)

    def test_clean_review_reports_counts(self):
        proc = self._review(D / "clean_small.diff")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = helpers.load_review_json(self.out, [self.project])
        self.assertIsNotNone(data)
        blob = json.dumps(data)
        self.assertIn("pricing.py", blob)

    def test_new_file_is_described_as_added(self):
        proc = self._review(D / "new_file.diff")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        low = self._all_text(proc).lower()
        self.assertIn("feature.py", low)
        self.assertTrue(any(w in low for w in ("add", "new", "creat")),
                        low[:400])

    # -- flags --------------------------------------------------------
    def test_test_edit_is_flagged(self):
        proc = self._review(D / "test_edit.diff")
        text = self._all_text(proc)
        low = text.lower()
        self.assertIn("test_pricing.py", text)
        self.assertTrue(
            any(w in low for w in ("test file", "test edit",
                                   "tests edited", "editing test",
                                   "test_change", "test-edit")),
            f"test edit not flagged: {text[:500]}")
        # Flagged must not be a silent clean pass in the JSON.
        data = helpers.load_review_json(self.out, [self.project])
        if data is not None:
            flags = helpers.flags_of(data)
            blob = json.dumps(data).lower()
            self.assertTrue(flags or "test" in blob)

    def test_secret_path_is_flagged_and_value_never_leaks(self):
        proc = self._review(D / "secret_path.diff")
        text = self._all_text(proc)
        low = text.lower()
        self.assertTrue(
            any(w in low for w in ("secret", "credential", ".env",
                                   "sensitive")),
            f"secrets path not flagged: {text[:500]}")
        self.assertNotIn(helpers.FAKE_SECRET, text,
                         "secret VALUE leaked into review output")
        self.assertNotIn(helpers.FAKE_SECRET, proc.stdout + proc.stderr)

    def test_large_deletion_is_flagged(self):
        proc = self._review(D / "large_deletion.diff")
        text = self._all_text(proc)
        low = text.lower()
        self.assertIn("legacy.py", text)
        self.assertTrue(
            any(w in low for w in ("large deletion", "large_deletion",
                                   "deleted", "deletion")),
            f"large deletion not flagged: {text[:500]}")
        self.assertTrue(any(n in text for n in ("120", "100")),
                        "deletion size not reported")

    def test_mixed_risky_flags_at_least_three_things(self):
        proc = self._review(D / "mixed_risky.diff")
        text = self._all_text(proc)
        low = text.lower()
        hits = 0
        hits += 1 if ("test" in low and "test_pricing" in low) else 0
        hits += 1 if any(w in low for w in ("secret", "credential",
                                             ".env")) else 0
        hits += 1 if any(w in low for w in ("delet", "removed")) else 0
        self.assertGreaterEqual(hits, 3,
                                f"mixed diff under-flagged: {text[:600]}")
        self.assertNotIn(helpers.FAKE_SECRET, text)

    # -- optional reports --------------------------------------------
    def test_verify_report_is_incorporated(self):
        proc = self._review(D / "clean_small.diff",
                            verify=helpers.REPORTS / "verify-report.json")
        # If the CLI rejects the option outright that is a shape
        # gap, recorded in REPORT_B; accept usage failure as skip.
        if proc.returncode == 2 and "unrecognized" in (
                proc.stdout + proc.stderr).lower():
            self.skipTest("CLI has no --verify-report option shape "
                          "helpers know; see REPORT_B.md")
        text = self._all_text(proc)
        self.assertTrue(
            any(w in text for w in ("compute_total", "MISSING-HARD",
                                    "ghostverify", "Verify")),
            f"verify report not reflected: {text[:500]}")

    def test_scope_report_is_incorporated(self):
        proc = self._review(D / "clean_small.diff",
                            scope=helpers.REPORTS / "scope.json")
        if proc.returncode == 2 and "unrecognized" in (
                proc.stdout + proc.stderr).lower():
            self.skipTest("CLI has no --scope-pack option shape "
                          "helpers know; see REPORT_B.md")
        text = self._all_text(proc)
        self.assertTrue(
            any(w in text for w in ("blast radius", "6 callers",
                                    "ghostscope", "Scope")),
            f"scope report not reflected: {text[:500]}")

    # -- remaining plan risk rules --------------------------------------
    def test_config_and_dependency_are_flagged(self):
        proc = self._review(D / "config_change.diff")
        low = self._all_text(proc).lower()
        self.assertTrue(any(w in low for w in ("config", "dependency")),
                        f"config/dependency not flagged: {low[:500]}")

    def test_symbol_removed_is_flagged(self):
        proc = self._review(D / "symbol_removed.diff")
        text = self._all_text(proc)
        self.assertIn("compute_total", text)
        low = text.lower()
        self.assertTrue(any(w in low for w in ("symbol-removed",
                                               "symbol removed",
                                               "removed symbol")),
                        f"symbol removal not flagged: {text[:500]}")

    def test_binary_change_is_flagged_as_unreviewable(self):
        proc = self._review(D / "binary_change.diff")
        low = self._all_text(proc).lower()
        self.assertIn("logo.png", low)
        self.assertIn("binary", low)

    def test_deleted_test_is_flagged(self):
        proc = self._review(D / "deleted_test.diff")
        low = self._all_text(proc).lower()
        self.assertIn("test_pricing.py", low)
        self.assertIn("test-edit", low)

    def test_secret_shaped_line_flagged_value_never_shown(self):
        proc = self._review(D / "secret_shaped_line.diff")
        text = self._all_text(proc)
        low = text.lower()
        self.assertTrue(any(w in low for w in ("secret-shaped-line",
                                               "secret shaped",
                                               "secret-shaped")),
                        f"secret-shaped line not flagged: {text[:500]}")
        self.assertNotIn(helpers.FAKE_SECRET, text)

    def test_verify_failure_raises_attention(self):
        # The fixture Verify verdict is gaps_found with exit 1, so
        # the plan rule VERIFY-FAILED (high) must drive the verdict.
        proc = self._review(D / "clean_small.diff",
                            verify=helpers.REPORTS / "verify-report.json")
        if proc.returncode == 2 and "unrecognized" in (
                proc.stdout + proc.stderr).lower():
            self.skipTest("no --verify-report shape known")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        low = self._all_text(proc).lower()
        self.assertIn("needs-attention", low)

    # -- dependents, verdict, honesty ------------------------------------
    def test_dependent_of_changed_file_is_listed(self):
        # app.py in the sample project imports pricing.compute_total
        # and is not in the diff, so it must be listed as a dependent.
        proc = self._review(D / "clean_small.diff")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = self._all_text(proc)
        self.assertIn("app.py", text)

    def test_unrelated_diff_lists_no_dependents(self):
        proc = self._review(D / "new_file.diff")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = helpers.load_review_json(self.out, [self.project])
        if data is not None and isinstance(data.get("dependents"), dict):
            all_deps = [d for e in data["dependents"].values()
                        for d in (e.get("dependents") or [])]
            self.assertEqual(all_deps, [])

    def test_verdict_vocabulary(self):
        proc = self._review(D / "clean_small.diff")
        data = helpers.load_review_json(self.out, [self.project])
        self.assertIsNotNone(data)
        self.assertIn(data.get("verdict"),
                      ("straightforward", "needs-a-look",
                       "needs-attention", "could-not-review"))

    def test_no_optional_reports_says_so_plainly(self):
        proc = self._review(D / "clean_small.diff")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        low = self._all_text(proc).lower()
        self.assertTrue(
            any(w in low for w in ("no ghostverify report was provided",
                                   "no verify report",
                                   "no ghostverify report")),
            f"missing Verify report not stated: {low[:500]}")
        self.assertTrue(
            any(w in low for w in ("no ghostscope pack was provided",
                                   "no scope pack", "no ghostscope")),
            f"missing Scope pack not stated: {low[:500]}")

    def test_numbers_in_md_match_json(self):
        # Plan known-diff bar: REVIEW.md numbers match review.json.
        proc = self._review(D / "mixed_risky.diff")
        data = helpers.load_review_json(self.out, [self.project])
        self.assertIsNotNone(data)
        totals = data.get("totals") or {}
        rj, md = helpers.find_outputs(self.out, [self.project])
        md_text = md.read_text(encoding="utf-8")
        if totals.get("files_changed") is not None:
            self.assertIn(str(totals["files_changed"]), md_text)

    # -- edge cases ----------------------------------------------------
    def test_empty_diff_is_could_not_review_exit_2(self):
        # Plan verification bar + honesty test: an empty diff exits
        # 2 with could-not-review, never a clean verdict.
        proc = self._review(D / "empty.diff")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        low = self._all_text(proc).lower()
        self.assertIn("could-not-review", low)
        self.assertNotIn("verdict: straightforward", low)

    def test_malformed_diff_is_rejected_loudly(self):
        proc = self._review(D / "malformed.diff")
        self.assertNotEqual(proc.returncode, 0,
                            "malformed diff silently accepted")
        self.assertIn(proc.returncode, (1, 2))

    def test_missing_diff_file_is_an_error(self):
        proc = self._review(self.tmp / "does-not-exist.diff")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(proc.returncode, (1, 2))

    def test_project_tree_is_not_modified(self):
        before = helpers.tree_hashes(self.project)
        proc = self._review(D / "mixed_risky.diff")
        after = helpers.tree_hashes(self.project)
        # New bookkeeping files in the project are tolerated only
        # if they are review outputs; source hashes must not move.
        for rel, h in before.items():
            self.assertIn(rel, after, f"{rel} deleted by review run")
            self.assertEqual(after[rel], h, f"{rel} modified by review")


if __name__ == "__main__":
    unittest.main()
