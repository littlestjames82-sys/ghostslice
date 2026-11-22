"""THE leak test: canary values must never appear in any output.

Three FAKE canaries are planted, each on a different surface the
plan's verification bar names:

- ``CANARY`` in canary_project/.env (a value in an env file),
- ``CANARY_DEFAULT`` in a code default argument in app.py
  (GhostEnv records a has_default boolean, never the literal),
- ``CANARY_COMMENT`` in a comment in canary_project/.env.example
  (generated examples regenerate comments from names alone).

None of them is, or has ever been, a real credential.

Method: run every output surface (check, check --json, scan,
scan --json, example -o, example --stdout), capture stdout and
stderr, and read every file the run CREATES OR CHANGES (diffed
against a pre-run hash snapshot). The fixture's own source files
are excluded by that diff: they are the one place a canary is
allowed to exist, and the fixture tests prove each canary really
is planted there, so a pass here is not vacuous.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402


def changed_texts(root, before):
    """Texts of files under root that are new or changed vs before."""
    after = helpers.tree_hashes(root)
    out = {}
    for rel, digest in after.items():
        if before.get(rel) != digest:
            try:
                out[rel] = (Path(root) / rel).read_text(encoding="utf-8")
            except (UnicodeDecodeError, ValueError):
                continue
    return out


@unittest.skipUnless(helpers.cli_available(),
                     "ghostenv CLI not discoverable (see REPORT_B.md)")
class TestCanaryNeverLeaks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ge-leak-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.proj = helpers.copy_fixture("canary_project", self.tmp)
        # Sanity: all three canaries start in their source files.
        self.assertIn(helpers.CANARY,
                      (self.proj / ".env").read_text(encoding="utf-8"))
        self.assertIn(helpers.CANARY_DEFAULT,
                      (self.proj / "app.py").read_text(encoding="utf-8"))
        self.assertIn(helpers.CANARY_COMMENT,
                      (self.proj / ".env.example").read_text(
                          encoding="utf-8"))

    def _assert_no_canary(self, where, blob):
        for canary in helpers.ALL_CANARIES:
            self.assertNotIn(canary, blob,
                             f"canary value leaked into {where}")

    def test_check_output_and_written_files_have_no_canary(self):
        before = helpers.tree_hashes(self.tmp)
        proc = helpers.run_check(self.proj)
        self._assert_no_canary("check stdout", proc.stdout)
        self._assert_no_canary("check stderr", proc.stderr)
        for rel, text in changed_texts(self.tmp, before).items():
            self._assert_no_canary(f"file {rel} written by check", text)

    def test_scan_lists_the_name_but_never_any_canary(self):
        proc = helpers.run_cli(["scan", str(self.proj)])
        self._assert_no_canary("scan stdout", proc.stdout)
        self._assert_no_canary("scan stderr", proc.stderr)
        # The NAME is the whole point of scan; only values are banned.
        self.assertIn(helpers.CANARY_NAME, proc.stdout)

    def test_generate_output_and_files_have_no_canary(self):
        before = helpers.tree_hashes(self.tmp)
        out = self.tmp / "generated.env.example"
        proc, generated = helpers.run_generate(self.proj, out)
        self._assert_no_canary("generate stdout", proc.stdout)
        self._assert_no_canary("generate stderr", proc.stderr)
        self.assertIsNotNone(generated, "no generated example found")
        self._assert_no_canary(
            "generated example",
            Path(generated).read_text(encoding="utf-8"))
        for rel, text in changed_texts(self.tmp, before).items():
            self._assert_no_canary(f"file {rel} after generate", text)
        # ...while the original .env is untouched and still holds it.
        self.assertIn(helpers.CANARY,
                      (self.proj / ".env").read_text(encoding="utf-8"))

    def test_scan_and_json_and_stdout_surfaces_have_no_canary(self):
        # PLAN verification bar: each output surface separately.
        surfaces = [
            ["scan", str(self.proj)],
            ["scan", str(self.proj), "--json"],
            ["check", str(self.proj), "--json"],
            ["example", str(self.proj), "--stdout"],
        ]
        for args in surfaces:
            proc = helpers.run_cli(args)
            self._assert_no_canary(f"{args} stdout", proc.stdout)
            self._assert_no_canary(f"{args} stderr", proc.stderr)

    def test_help_and_version_have_no_canary(self):
        for args in (["--help"], ["--version"]):
            proc = helpers.run_cli(args)
            self._assert_no_canary(f"{args} stdout", proc.stdout)
            self._assert_no_canary(f"{args} stderr", proc.stderr)


class TestDocsHaveNoCanary(unittest.TestCase):
    """The shipped docs/examples must not carry the canaries either."""

    def test_readme_and_examples_are_canary_free(self):
        for base in (helpers.REPO_ROOT / "README.md",
                     helpers.REPO_ROOT / "examples"):
            if not Path(base).exists():
                continue
            paths = [base] if Path(base).is_file() else [
                p for p in Path(base).rglob("*") if p.is_file()]
            for path in paths:
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, ValueError):
                    continue
                for canary in helpers.ALL_CANARIES:
                    self.assertNotIn(canary, text, str(path))


if __name__ == "__main__":
    unittest.main()
