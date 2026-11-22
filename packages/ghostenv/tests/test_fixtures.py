"""Fixture-validity tests: no CLI needed, always run.

These prove the fixtures encode exactly the differences the CLI
tests rely on, using the test-side reference parsers in helpers:
- clean_project: code usage == .env names == .env.example names
- missing_project: the intended missing / stale / unused sets
- canary_project: the canary value is really in the .env (so the
  leak test has something to catch) and its name is used in code
- malformed_project: malformed lines and a duplicate are present
- every fixture value is FAKE-labelled or empty (no real secrets)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402


class TestCleanFixture(unittest.TestCase):
    def setUp(self):
        self.proj = helpers.FIXTURES / "clean_project"

    def test_usage_matches_env_and_example(self):
        used = helpers.used_env_names(self.proj)
        env_names, dups, malformed = helpers.parse_env_file(self.proj / ".env")
        ex_names, _, _ = helpers.parse_env_file(self.proj / ".env.example")
        self.assertEqual(used, set(env_names), f"used={used} env={env_names}")
        self.assertEqual(used, set(ex_names), f"used={used} example={ex_names}")
        self.assertEqual(dups, [])
        self.assertEqual(malformed, [])

    def test_usage_spans_python_and_js(self):
        used = helpers.used_env_names(self.proj)
        self.assertIn("DATABASE_URL", used)   # python os.environ[...]
        self.assertIn("DEMO_API_KEY", used)   # python os.getenv
        self.assertIn("APP_REGION", used)     # js process.env.X
        self.assertIn("APP_PORT", used)       # both


class TestMissingFixture(unittest.TestCase):
    def setUp(self):
        self.proj = helpers.FIXTURES / "missing_project"

    def test_intended_differences(self):
        used = helpers.used_env_names(self.proj)
        env_names, _, _ = helpers.parse_env_file(self.proj / ".env")
        ex_names, _, _ = helpers.parse_env_file(self.proj / ".env.example")
        self.assertEqual(used - set(env_names) - set(ex_names),
                         {"REQUIRED_IN_CODE_ONLY"})
        self.assertIn("IN_ENV_NOT_EXAMPLE", set(env_names) - set(ex_names))
        self.assertIn("IN_ENV_NOT_EXAMPLE", used)
        self.assertEqual(set(ex_names) - used, {"STALE_IN_EXAMPLE"})
        self.assertEqual(set(env_names) - used, {"UNUSED_IN_ENV"})
        self.assertIn("SHARED_OK", used & set(env_names) & set(ex_names))


class TestCanaryFixture(unittest.TestCase):
    def setUp(self):
        self.proj = helpers.FIXTURES / "canary_project"

    def test_canary_is_really_planted(self):
        # Without this, the leak test would be vacuous.
        env_text = (self.proj / ".env").read_text(encoding="utf-8")
        self.assertIn(helpers.CANARY, env_text)
        self.assertIn(helpers.CANARY_NAME, helpers.used_env_names(self.proj))

    def test_canary_not_in_example_or_code(self):
        for rel in ("app.py", ".env.example"):
            text = (self.proj / rel).read_text(encoding="utf-8")
            self.assertNotIn(helpers.CANARY, text, rel)

    def test_default_and_comment_canaries_are_planted(self):
        code = (self.proj / "app.py").read_text(encoding="utf-8")
        example = (self.proj / ".env.example").read_text(encoding="utf-8")
        env_text = (self.proj / ".env").read_text(encoding="utf-8")
        self.assertIn(helpers.CANARY_DEFAULT, code)
        self.assertIn(helpers.CANARY_COMMENT, example)
        # Neither secondary canary may hide in the .env itself:
        # each leak assertion must point at its own surface.
        self.assertNotIn(helpers.CANARY_DEFAULT, env_text)
        self.assertNotIn(helpers.CANARY_COMMENT, env_text)


class TestMalformedFixture(unittest.TestCase):
    def test_malformed_and_duplicate_detected_by_reference_parser(self):
        proj = helpers.FIXTURES / "malformed_project"
        names, dups, malformed = helpers.parse_env_file(proj / ".env")
        self.assertIn("WELL_FORMED", names)
        self.assertEqual(dups, ["DUPLICATED_NAME"])
        self.assertGreaterEqual(len(malformed), 2, malformed)


class TestNoRealSecretsInFixtures(unittest.TestCase):
    def test_fixture_env_values_are_fake_or_empty(self):
        for env_path in helpers.FIXTURES.rglob(".env*"):
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if not helpers.ENV_NAME_RE.match(
                        line.split("=", 1)[0].strip()):
                    continue  # malformed fixture line, no name to check
                value = line.split("=", 1)[1].strip()
                if not value:
                    continue
                low = value.lower()
                self.assertTrue(
                    "fake" in low or "canary" in low or low in (
                        "false", "8000", "us-east-1",
                        "ordinary_fake_setting"),
                    f"{env_path}: value not labelled fake: {line.split('=')[0]}")


if __name__ == "__main__":
    unittest.main()
