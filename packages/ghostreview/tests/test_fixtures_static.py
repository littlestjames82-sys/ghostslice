"""Fixture-validity tests for GhostReview. No CLI needed.

These pin the planted cases the CLI tests rely on: a clean small
change, a test-only edit, a secrets-path edit, a large deletion
(>=100 deleted lines plus a deleted file), a new file, a rename,
a mixed risky diff carrying all three flag classes at once, an
empty diff, and a malformed non-diff. They also validate the
optional Verify / Scope report fixtures GhostReview can ingest.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

D = helpers.DIFFS


class TestDiffFixtures(unittest.TestCase):
    def test_clean_small_touches_only_pricing(self):
        info = helpers.parse_diff(D / "clean_small.diff")
        paths = [f["new"] for f in info["files"]]
        self.assertEqual(paths, ["pricing.py"])
        self.assertGreater(info["additions"], 0)
        self.assertFalse(helpers.is_test_path("pricing.py"))
        self.assertFalse(helpers.is_secret_path("pricing.py"))

    def test_test_edit_touches_only_a_test_file(self):
        info = helpers.parse_diff(D / "test_edit.diff")
        self.assertEqual(len(info["files"]), 1)
        path = info["files"][0]["new"]
        self.assertTrue(helpers.is_test_path(path), path)
        # The edit weakens an assertion, the classic test-edit flag.
        self.assertIn("== 0.0", info["text"])

    def test_secret_path_touches_secret_paths_only(self):
        info = helpers.parse_diff(D / "secret_path.diff")
        paths = [f["new"] for f in info["files"]]
        self.assertEqual(sorted(paths), [".env", "config/credentials.json"])
        for p in paths:
            self.assertTrue(helpers.is_secret_path(p), p)
        # Fixture carries a FAKE marker only, never a real secret.
        self.assertIn(helpers.FAKE_SECRET, info["text"])

    def test_large_deletion_is_large_and_deletes_a_file(self):
        info = helpers.parse_diff(D / "large_deletion.diff")
        self.assertGreaterEqual(info["deletions"], 100)
        statuses = [f["status"] for f in info["files"]]
        self.assertIn("deleted", statuses)
        self.assertEqual(info["files"][0]["new"], "legacy.py")

    def test_new_file_fixture(self):
        info = helpers.parse_diff(D / "new_file.diff")
        self.assertEqual(info["files"][0]["status"], "added")
        self.assertEqual(info["files"][0]["new"], "feature.py")
        self.assertGreater(info["additions"], 0)
        self.assertEqual(info["deletions"], 0)

    def test_rename_fixture(self):
        info = helpers.parse_diff(D / "rename.diff")
        self.assertEqual(info["files"][0]["status"], "renamed")
        self.assertEqual(info["files"][0]["old"], "old_name.py")
        self.assertEqual(info["files"][0]["new"], "new_name.py")

    def test_mixed_risky_carries_all_three_flag_classes(self):
        info = helpers.parse_diff(D / "mixed_risky.diff")
        paths = [f["new"] or f["old"] for f in info["files"]]
        self.assertTrue(any(helpers.is_test_path(p) for p in paths), paths)
        self.assertTrue(any(helpers.is_secret_path(p) for p in paths), paths)
        self.assertTrue(
            any(f["status"] == "deleted" for f in info["files"]), paths)
        self.assertIn("pricing.py", paths)

    def test_empty_diff_is_empty(self):
        info = helpers.parse_diff(D / "empty.diff")
        self.assertEqual(info["files"], [])
        self.assertEqual(info["additions"], 0)
        self.assertEqual(info["deletions"], 0)

    def test_malformed_is_not_a_diff(self):
        info = helpers.parse_diff(D / "malformed.diff")
        self.assertEqual(info["files"], [])
        self.assertNotIn("diff --git", info["text"])


class TestReportFixtures(unittest.TestCase):
    def test_verify_report_fixture_shape(self):
        data = json.loads(
            (helpers.REPORTS / "verify-report.json").read_text())
        self.assertEqual(data["tool"], "ghostverify")
        gaps = data["gaps"]
        self.assertTrue(gaps)
        self.assertEqual(gaps[0]["symbol"], "compute_total")
        self.assertEqual(gaps[0]["file"], "pricing.py")
        # Real GhostVerify shape: `gaps` is the hard-gap list, and
        # a non-passing verdict + exit_code is what Review cites.
        self.assertEqual(data["verdict"], "gaps_found")
        self.assertEqual(data["exit_code"], 1)

    def test_scope_fixture_shape(self):
        data = json.loads((helpers.REPORTS / "scope.json").read_text())
        self.assertEqual(data["tool"], "ghostscope")
        # GhostScope scope.json shape: a files list with risk reasons.
        files = data["files"]
        self.assertEqual(files[0]["path"], "pricing.py")
        reasons = " ".join(files[0]["risk_reasons"])
        self.assertIn("blast radius", reasons)
        self.assertIn("6 callers", reasons)

    def test_config_fixture_touches_config_and_dependency(self):
        info = helpers.parse_diff(D / "config_change.diff")
        paths = [f["new"] for f in info["files"]]
        self.assertIn("pyproject.toml", paths)
        self.assertIn(".github/workflows/ci.yml", paths)

    def test_symbol_removed_fixture_removes_a_def(self):
        info = helpers.parse_diff(D / "symbol_removed.diff")
        self.assertIn("def compute_total", info["text"])
        self.assertGreater(info["deletions"], info["additions"])

    def test_binary_fixture_is_binary(self):
        info = helpers.parse_diff(D / "binary_change.diff")
        self.assertEqual(info["files"][0]["status"], "binary")
        self.assertEqual(info["files"][0]["new"], "logo.png")

    def test_deleted_test_fixture_deletes_a_test_file(self):
        info = helpers.parse_diff(D / "deleted_test.diff")
        self.assertEqual(info["files"][0]["status"], "deleted")
        self.assertTrue(helpers.is_test_path(info["files"][0]["new"]))

    def test_secret_shaped_line_fixture(self):
        info = helpers.parse_diff(D / "secret_shaped_line.diff")
        self.assertEqual([f["new"] for f in info["files"]], ["settings.py"])
        self.assertFalse(helpers.is_secret_path("settings.py"))
        self.assertIn(helpers.FAKE_SECRET, info["text"])


class TestSampleProject(unittest.TestCase):
    def test_sample_project_is_consistent(self):
        proj = helpers.SAMPLE_PROJECT
        self.assertTrue((proj / "pricing.py").exists())
        self.assertTrue((proj / "app.py").exists())
        text = (proj / "pricing.py").read_text()
        self.assertIn("def compute_total", text)
        test_text = (proj / "tests" / "test_pricing.py").read_text()
        self.assertIn("compute_total", test_text)


if __name__ == "__main__":
    unittest.main()
