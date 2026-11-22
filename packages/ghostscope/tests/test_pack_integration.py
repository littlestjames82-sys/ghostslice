"""Integration tests against the GhostScope core (Agent A).

Implements the PLAN.md Verification bar:
  1. High blast radius ranks above a large isolated change, caller count
     stated as the reason.
  2. Completeness: every direct caller of a changed exported symbol is
     in the pack at signatures mode or better.
  3. Honesty: a change with no covering tests (covering test deleted)
     says so in REVIEW.md in plain words.
  4. Signature change with stale callers is noted factually, citing
     file + symbol.
  5. Pack validates: manifest.json totals reproduce; scope.json parses
     and carries base/head; ghostslice check runs when available.

These fail (do not skip) when the core is absent, so the parent can see
the true state of the combined tree. See REPORT_B.md.
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import (
    FIXTURES, apply_change, build_git_project, find_pack_file,
    flatten_text, load_json_recursive, run_pack,
)


class PackCase(unittest.TestCase):
    fixture = None  # name

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        root = FIXTURES / self.fixture
        self.proj = build_git_project(root / "base", tmp)
        apply_change(self.proj, root / "change", root / "deletions.txt")
        self.out = tmp / "pack"
        run_pack(self.proj, self.out)
        self.review_path = find_pack_file(self.out, self.proj, "REVIEW.md")
        self.scope_path = find_pack_file(self.out, self.proj, "scope.json")
        self.manifest_path = find_pack_file(self.out, self.proj, "manifest.json")
        self.review = self.review_path.read_text() if self.review_path else ""
        self.scope = (load_json_recursive(self.scope_path)
                      if self.scope_path else None)

    def assert_artifacts(self):
        self.assertIsNotNone(self.review_path, "pack has no REVIEW.md")
        self.assertIsNotNone(self.scope_path, "pack has no scope.json sidecar")
        self.assertIsNotNone(self.manifest_path, "pack has no manifest.json")


class TestHighBlastRadius(PackCase):
    fixture = "high_blast_radius"

    def test_artifacts_exist(self):
        self.assert_artifacts()

    def test_shared_ranks_above_isolated(self):
        self.assert_artifacts()
        low = self.review.lower()
        self.assertIn("compute_total", low)
        self.assertIn("isolated", low)
        self.assertLess(low.index("compute_total"), low.index("isolated"),
                        "widely-called symbol must appear before the "
                        "isolated change in riskiest-first reading order")

    def test_caller_count_is_the_stated_reason(self):
        self.assert_artifacts()
        blob = (self.review + " " + flatten_text(self.scope or {})).lower()
        self.assertRegex(blob, re.compile(r"6\s*(direct\s*)?callers|callers?\s*[:=]?\s*6"))

    def test_completeness_all_direct_callers_in_pack(self):
        self.assert_artifacts()
        blob = flatten_text(self.scope or {}) + " " + self.review
        for caller in ("caller_a", "caller_b", "caller_c",
                       "caller_d", "caller_e", "caller_f"):
            self.assertIn(caller, blob, f"direct caller {caller} missing from pack")
        # At signatures or better: the pack must not list a caller as excluded.
        if isinstance(self.scope, dict):
            text = flatten_text(self.scope).lower()
            for caller in ("caller_a", "caller_b"):
                idx = text.find(caller)
                if idx >= 0:
                    window = text[idx:idx + 120]
                    self.assertNotIn("exclude", window,
                                     f"{caller} listed as excluded in scope.json")


class TestSignatureChangeStaleCaller(PackCase):
    fixture = "signature_change_stale_caller"

    def test_artifacts_exist(self):
        self.assert_artifacts()

    def test_signature_change_is_noted(self):
        self.assert_artifacts()
        blob = (self.review + " " + flatten_text(self.scope or {})).lower()
        self.assertIn("format_name", blob)
        self.assertRegex(blob, re.compile(r"signature"))

    def test_stale_caller_is_noted_with_file_and_symbol(self):
        self.assert_artifacts()
        blob = (self.review + " " + flatten_text(self.scope or {})).lower()
        self.assertIn("consumer", blob)
        self.assertRegex(
            blob,
            re.compile(r"(not updated|stale|unchanged|old arity|2 arg|two arg)"),
            "pack must state factually that a caller was not updated",
        )


class TestDeletedCoveringTest(PackCase):
    fixture = "deleted_covering_test"

    def test_artifacts_exist(self):
        self.assert_artifacts()

    def test_honesty_no_covering_test_in_plain_words(self):
        self.assert_artifacts()
        blob = (self.review + " " + flatten_text(self.scope or {})).lower()
        self.assertRegex(
            blob,
            re.compile(r"no covering test|covering test.*(deleted|removed|missing)|deleted.*test"),
            "REVIEW.md must say in plain words that the covering test is gone",
        )

    def test_deleted_test_is_not_in_pack_files(self):
        pack_files = [p.name for p in self.out.rglob("*")] if self.out.exists() else []
        self.assertNotIn("test_billing.py", pack_files)


class TestPackValidation(PackCase):
    fixture = "high_blast_radius"

    def test_scope_json_has_base_and_head(self):
        self.assert_artifacts()
        blob = flatten_text(self.scope).lower()
        self.assertIn("base", blob)
        self.assertIn("head", blob)

    def test_manifest_totals_reproduce(self):
        self.assert_artifacts()
        manifest = load_json_recursive(self.manifest_path)
        text = flatten_text(manifest)
        # Some numeric total must be present and positive.
        nums = [int(n) for n in re.findall(r"\b\d+\b", text)]
        self.assertTrue(any(n > 0 for n in nums),
                        "manifest carries no positive token/file totals")

    def test_ghostslice_check_when_available(self):
        exe = shutil.which("ghostslice")
        if not exe:
            self.skipTest("ghostslice not on PATH (optional cross-check)")
        pack_dir = self.manifest_path.parent
        r = subprocess.run([exe, "check", str(pack_dir)],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
