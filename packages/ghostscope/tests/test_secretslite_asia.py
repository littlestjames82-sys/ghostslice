"""Regression tests for the secretslite canonical-alignment fix.

Background (Oct 14, 2026 ecosystem pass, SEAM_FIX_REPORT.md): the
ecosystem pass aligned AKIA-only AWS patterns in four sibling tools
but undercounted - GhostScope's secretslite still carried the
AKIA-only form, so ASIA temporary session keys (the shape
GhostSlice's canonical guard covers) escaped Scope's risk scan.
The lite SET stays deliberately small (see the module docstring);
these tests pin that every shape the set carries tracks the
canonical pattern for that shape, and that an ASIA canary is caught
end to end: scan_added_lines -> scope.json finding -> REVIEW.md
risk reason, with the value itself never stored or printed.

All canaries below are fake, planted, test-only literals in secret
shapes. None is, or has ever been, a real credential.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostscope.secretslite import scan_added_lines  # noqa: E402

from tests.helpers import (  # noqa: E402
    find_pack_file, git, load_json_recursive, run_pack,
)

# ASIA + exactly 16 chars of [0-9A-Z]: the temporary-session-key shape.
ASIA_CANARY = "ASIA1234567890ABCDEF"
AKIA_CANARY = "AKIA1234567890ABCDEF"


def findings_for(text, lineno=1, path="config.py"):
    return scan_added_lines(path, [(lineno, text)])


class TestAwsAlignment(unittest.TestCase):
    def test_asia_temp_key_is_caught(self):
        got = findings_for(f'KEY = "{ASIA_CANARY}"', lineno=7)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["type"], "aws-access-key")
        self.assertEqual(got[0]["line"], 7)
        self.assertEqual(got[0]["path"], "config.py")

    def test_akia_still_caught(self):
        got = findings_for(f'KEY = "{AKIA_CANARY}"')
        self.assertEqual([f["type"] for f in got], ["aws-access-key"])

    def test_finding_carries_no_value(self):
        got = findings_for(f'KEY = "{ASIA_CANARY}"')
        self.assertEqual(set(got[0].keys()), {"path", "line", "type"})
        self.assertNotIn(ASIA_CANARY, repr(got))

    def test_lookalikes_not_caught(self):
        for text in (
            'KEY = "ASIA123"',                    # too short
            'KEY = "asia1234567890abcdef"',       # lowercase is not the shape
            'KEY = "AKIA1234567890ABCDE"',        # 15-char tail, shape is 16
        ):
            self.assertEqual(findings_for(text), [], text)


class TestOtherAlignedShapes(unittest.TestCase):
    def test_github_token_with_underscore_body_is_caught(self):
        # Canonical class is [A-Za-z0-9_]: a body whose alnum runs are
        # split by an underscore (10 + 12, neither reaching 20 alone)
        # escaped the lite copy, which omitted the underscore.
        got = findings_for('TOKEN = "ghp_abcdefghij_klmnopqrstuv"')
        self.assertEqual([f["type"] for f in got], ["github-token"])

    def test_openai_key_at_canonical_minimum_is_caught(self):
        # Canonical tail minimum is 16; the lite copy had drifted to 20.
        got = findings_for('KEY = "sk-abcdefghijklmnop"')
        self.assertEqual([f["type"] for f in got], ["openai-or-anthropic-key"])

    def test_private_key_dsa_and_pgp_headers_are_caught(self):
        for header in ("-----BEGIN DSA PRIVATE KEY-----",
                       "-----BEGIN PGP PRIVATE KEY-----",
                       "-----BEGIN RSA PRIVATE KEY-----",
                       "-----BEGIN PRIVATE KEY-----"):
            got = findings_for(header)
            self.assertEqual([f["type"] for f in got], ["private-key"], header)


class TestUntouchedShapesStillCaught(unittest.TestCase):
    """Parity controls: the alignment must not break the rest of the set."""

    def test_slack_token(self):
        got = findings_for('T = "xoxb-1234567890ab"')
        self.assertEqual([f["type"] for f in got], ["slack-token"])

    def test_anthropic_key(self):
        got = findings_for('KEY = "sk-ant-abcdefghijklmnopqrst"')
        self.assertEqual([f["type"] for f in got], ["openai-or-anthropic-key"])

    def test_password_in_url(self):
        got = findings_for('DB = "https://user:secretpass@db.internal/x"')
        self.assertEqual([f["type"] for f in got], ["password-in-url"])

    def test_sensitive_assignment(self):
        got = findings_for('api_key = "abcdefgh123"')
        self.assertEqual([f["type"] for f in got], ["sensitive-assignment"])


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk(v)


class TestAsiaCanaryThroughPack(unittest.TestCase):
    """End to end: wherever secretslite is used (the pack flow), an
    added ASIA line raises the risk reason and lands in scope.json
    as a type-only finding; the value appears in neither artifact."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.proj = tmp / "proj"
        self.proj.mkdir()
        subprocess.run(["git", "init", "-q", str(self.proj)], check=True)
        git(self.proj, "config", "user.email", "test@example.com")
        git(self.proj, "config", "user.name", "GhostScope Tests")
        (self.proj / "app.py").write_text("def main():\n    return 1\n")
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-qm", "base")
        (self.proj / "deploy.py").write_text(
            f'AWS_TEMP_KEY = "{ASIA_CANARY}"\n')
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-qm", "change")
        self.out = tmp / "pack"
        run_pack(self.proj, self.out)
        self.scope_path = find_pack_file(self.out, self.proj, "scope.json")
        self.review_path = find_pack_file(self.out, self.proj, "REVIEW.md")

    def test_asia_finding_lands_in_scope_json(self):
        self.assertIsNotNone(self.scope_path, "pack has no scope.json")
        scope = load_json_recursive(self.scope_path)
        hits = [d for d in _walk(scope) if d.get("type") == "aws-access-key"]
        self.assertTrue(hits, "no aws-access-key finding in scope.json")
        self.assertTrue(any("deploy.py" in str(d.get("path", ""))
                            for d in hits))

    def test_review_states_secret_shaped_reason(self):
        self.assertIsNotNone(self.review_path, "pack has no REVIEW.md")
        review = self.review_path.read_text()
        self.assertIn("secret-shaped line added", review)

    def test_canary_value_nowhere_in_findings_artifacts(self):
        scope_text = self.scope_path.read_text()
        review_text = self.review_path.read_text()
        self.assertNotIn(ASIA_CANARY, scope_text)
        self.assertNotIn(ASIA_CANARY, review_text)


if __name__ == "__main__":
    unittest.main()
