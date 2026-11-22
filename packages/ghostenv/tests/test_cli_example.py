"""CLI tests for generating a clean .env.example.

Contract assumed from the task:
- Generation produces a .env.example listing every name the code
  uses (plus names already in .env), with EMPTY values or clearly
  labelled placeholders - never the real .env values.
- Generation never overwrites or modifies the project's .env.
Skips cleanly while no CLI / no generate command is discoverable.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

PLACEHOLDER_WORDS = ("fake", "example", "placeholder", "replace",
                     "change-me", "changeme", "your-", "your_",
                     "todo", "xxx", "<", "not_real", "not-real")


def _value_is_clean(value):
    value = value.strip().strip('"').strip("'")
    if not value:
        return True
    low = value.lower()
    return any(word in low for word in PLACEHOLDER_WORDS)


@unittest.skipUnless(helpers.cli_available(),
                     "ghostenv CLI not discoverable (see REPORT_B.md)")
class TestGenerateExample(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ge-gen-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _generate(self, fixture):
        proj = helpers.copy_fixture(fixture, self.tmp)
        out = self.tmp / "generated.env.example"
        proc, generated = helpers.run_generate(proj, out)
        if generated is None and not (proc.stdout or "").strip():
            self.skipTest("no generate/example command discoverable")
        return proj, proc, generated

    def _generated_text(self, proc, generated):
        if generated is not None and Path(generated).exists():
            return Path(generated).read_text(encoding="utf-8")
        return proc.stdout

    def test_generated_example_lists_used_names(self):
        proj, proc, generated = self._generate("missing_project")
        text = self._generated_text(proc, generated)
        for name in ("REQUIRED_IN_CODE_ONLY", "IN_ENV_NOT_EXAMPLE",
                     "SHARED_OK"):
            self.assertIn(name, text)

    def test_generated_example_has_no_real_values(self):
        proj, proc, generated = self._generate("canary_project")
        text = self._generated_text(proc, generated)
        self.assertNotIn(helpers.CANARY, text)
        self.assertNotIn("ordinary_fake_setting", text)
        self.assertIn(helpers.CANARY_NAME, text)
        if generated is not None and Path(generated).exists():
            names, _, _ = helpers.parse_env_file(generated)
            self.assertIn(helpers.CANARY_NAME, names)
            for line in Path(generated).read_text(
                    encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    self.assertTrue(
                        _value_is_clean(line.split("=", 1)[1]),
                        f"generated example carries a value: {line}")

    def test_generate_does_not_touch_dotenv(self):
        proj, proc, generated = self._generate("canary_project")
        env_text = (proj / ".env").read_text(encoding="utf-8")
        self.assertIn(helpers.CANARY, env_text,
                      "generate modified the project's real .env")


if __name__ == "__main__":
    unittest.main()
