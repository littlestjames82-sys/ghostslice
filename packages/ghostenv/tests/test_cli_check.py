"""CLI tests for the check / scan / doctor command.

Contract assumed from the task (exact subcommand name is
discovered from --help, see helpers / REPORT_B.md):
- Compares code env usage vs .env and .env.example.
- Reports NAMES ONLY, never values.
- A clean project passes (exit 0); a project with names used in
  code but missing from .env / .env.example fails (non-zero) and
  names the missing variables.
All tests skip cleanly while no ghostenv CLI is discoverable.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402


@unittest.skipUnless(helpers.cli_available(),
                     "ghostenv CLI not discoverable (see REPORT_B.md)")
class TestCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ge-check-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_clean_project_passes(self):
        proj = helpers.copy_fixture("clean_project", self.tmp)
        proc = helpers.run_check(proj)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_missing_names_fail_and_are_named(self):
        proj = helpers.copy_fixture("missing_project", self.tmp)
        proc = helpers.run_check(proj)
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        blob = proc.stdout + proc.stderr + "".join(
            helpers.collect_text(proj).values())
        self.assertIn("REQUIRED_IN_CODE_ONLY", blob)
        self.assertIn("IN_ENV_NOT_EXAMPLE", blob)

    def test_output_is_names_not_values(self):
        proj = helpers.copy_fixture("missing_project", self.tmp)
        proc = helpers.run_check(proj)
        blob = proc.stdout + proc.stderr
        # Names may appear; the FAKE values from the fixture .env
        # may not, in stdout/stderr or in any report file written.
        self.assertNotIn("FAKE_value_not_real_1111", blob)
        self.assertNotIn("FAKE_value_not_real_2222", blob)
        for rel, text in helpers.collect_text(proj).items():
            self.assertNotIn("FAKE_value_not_real_1111", text, rel)
            self.assertNotIn("FAKE_value_not_real_3333", text, rel)

    def test_malformed_env_is_reported_not_silent_pass(self):
        proj = helpers.copy_fixture("malformed_project", self.tmp)
        proc = helpers.run_check(proj)
        blob = proc.stdout + proc.stderr + "".join(
            helpers.collect_text(proj).values())
        # Either a non-zero exit or an explicit mention of the
        # problem lines / duplication; a silent clean pass is wrong.
        mentioned = any(word in blob.lower() for word in (
            "malformed", "duplicate", "no equals", "invalid",
            "parse", "duplicated_name"))
        self.assertTrue(proc.returncode != 0 or mentioned,
                        f"malformed .env silently passed: {blob[:400]}")

    def test_check_does_not_modify_project_sources(self):
        proj = helpers.copy_fixture("canary_project", self.tmp)
        before = helpers.tree_hashes(proj)
        helpers.run_check(proj)
        after = helpers.tree_hashes(proj)
        # Pre-existing files byte-identical; new report files are
        # allowed (leak tests scan those separately).
        for rel, digest in before.items():
            self.assertEqual(after.get(rel), digest,
                             f"check modified {rel}")

    def test_missing_project_is_an_error_not_a_pass(self):
        proc = helpers.run_check(self.tmp / "does-not-exist")
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
