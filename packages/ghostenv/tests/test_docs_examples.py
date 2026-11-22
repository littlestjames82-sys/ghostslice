"""Docs / examples guards: no CLI needed.

- README.md exists, states the names-only rule, and shows both
  the check flow and the generate flow.
- examples/mini_project is self-consistent under the reference
  parsers: code usage matches its .env.example names.
- Every value in examples/ is empty or a clearly labelled FAKE /
  placeholder. Examples must never model putting a real-looking
  secret in a file that ships.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

EXAMPLES = helpers.REPO_ROOT / "examples"
MINI = EXAMPLES / "mini_project"


class TestReadme(unittest.TestCase):
    def setUp(self):
        self.readme = helpers.REPO_ROOT / "README.md"
        self.assertTrue(self.readme.exists(), "README.md missing")
        self.text = self.readme.read_text(encoding="utf-8")
        self.low = self.text.lower()

    def test_states_names_only_rule(self):
        self.assertIn("names only", self.low)
        self.assertIn("never", self.low)
        self.assertTrue("value" in self.low)

    def test_documents_check_and_generate(self):
        self.assertTrue(any(w in self.low for w in
                            ("check", "scan", "doctor")))
        self.assertIn(".env.example", self.text)

    def test_no_guarantee_wording(self):
        # A static name comparison is evidence, not proof an app
        # will run. The README must not promise otherwise.
        self.assertNotIn("guarantees your app will run", self.low)
        self.assertNotIn("certified", self.low)


class TestExamples(unittest.TestCase):
    def test_mini_project_is_consistent(self):
        used = helpers.used_env_names(MINI)
        ex_names, _, malformed = helpers.parse_env_file(
            MINI / ".env.example")
        self.assertEqual(malformed, [])
        self.assertEqual(used, set(ex_names),
                         f"used={used} example={ex_names}")

    def test_example_values_are_empty_or_fake(self):
        for env_path in EXAMPLES.rglob(".env*"):
            names, _, _ = helpers.parse_env_file(env_path)
            for line in env_path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                value = s.split("=", 1)[1].strip()
                if value:
                    low = value.lower()
                    self.assertTrue(
                        "fake" in low or "placeholder" in low
                        or "example" in low,
                        f"{env_path}: non-fake value on {s.split('=')[0]}")

    def test_examples_readme_exists(self):
        self.assertTrue((EXAMPLES / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
