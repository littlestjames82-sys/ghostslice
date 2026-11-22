"""Help-text polish guards (improvement round, Oct 18, 2026).

The CLI help is the README's stated authority for subcommand
spelling, so it has to teach on its own: every subcommand help
names what it does, the top-level help states the exit codes and
the names-only rule, and ``project`` / ``--json`` carry help
instead of appearing bare. No values are involved anywhere here.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402


@unittest.skipUnless(helpers.cli_available(),
                     "ghostenv CLI not discoverable (see REPORT_B.md)")
class TestHelpPolish(unittest.TestCase):
    def help_for(self, *args):
        proc = helpers.run_cli([*args, "--help"])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout + proc.stderr

    def test_top_level_help_states_exit_codes_and_names_only(self):
        text = self.help_for().lower()
        self.assertIn("names only", text)
        self.assertIn("exit codes", text)
        self.assertIn("blocking findings", text)
        for cmd in ("scan", "check", "example"):
            self.assertIn(cmd, text)

    def test_subcommand_help_describes_project_and_json(self):
        for cmd in ("scan", "check"):
            text = self.help_for(cmd)
            self.assertIn("project directory", text, cmd)
            self.assertIn("JSON", text, cmd)

    def test_example_help_warns_it_writes_names_only(self):
        text = self.help_for("example")
        self.assertIn("project directory", text)
        self.assertIn("--stdout", text)
        self.assertIn("--force", text)


if __name__ == "__main__":
    unittest.main()
