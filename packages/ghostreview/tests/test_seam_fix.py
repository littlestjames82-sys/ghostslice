"""Seam-fix regression tests (Oct 14, 2026).

The ecosystem pass found GhostReview's secret line shapes had drifted
from GhostSlice's canonical guard list (ghostslice/secrets_scan.py):
an ASIA temporary session key in a reviewed diff escaped the risk scan
entirely because the AWS alternative was AKIA-only. These tests pin
the aligned shapes. The pre-fix probe: a diff adding
SESSION = "ASIA..." and LONGTERM = "AKIA..." lines flagged only the
AKIA line; the ASIA line drew no flag at all.

Unit-level like test_polish.py: imports the package from src/
directly. No pre-existing test is touched.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostreview.core import build_review      # noqa: E402
from ghostreview.reports import render_markdown  # noqa: E402

ASIA_KEY = "ASIA1234567890ABCDEF"        # ASIA + 16 [0-9A-Z]: temp session key
AKIA_KEY = "AKIA1234567890ABCDEF"        # AKIA + 16: long-term key (control)
ASIA_SHORT = "ASIA1234567890ABCDE"       # ASIA + 15: near miss, must not flag
GHO_TOKEN = "gho_1234567890ABCDEFGHIJ"   # gho_ + 20: GitHub OAuth token
SK_ANT_KEY = "sk-ant-api03-X7k9Qw2Zt8Lp4Mn6Rs"  # Anthropic key shape
BARE_40 = "Kx9Qw2Zt" * 5                 # exactly 40 base64-ish chars
DB_URL = "postgres://svc_user:sup3rsecret@db.internal:5432/app"


def _proj(files):
    td = Path(tempfile.mkdtemp(prefix="gr-seam-"))
    for rel, content in files.items():
        fp = td / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    return td


def _review_added(added_lines, path="app.py"):
    """Review a diff whose only change adds `added_lines` to a file.

    Returns (report, secret_flags) where secret_flags are the
    SECRET-SHAPED-LINE risks. Added lines are new-file lines 1..n.
    """
    proj = _proj({path: "old\n"})
    body = "".join(f"+{line}\n" for line in added_lines)
    diff = (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -1,1 +1,{len(added_lines)} @@\n-old\n{body}")
    try:
        rep = build_review(proj, diff, "file:x")
    finally:
        shutil.rmtree(proj, ignore_errors=True)
    flags = [r for r in rep["risks"] if r["rule"] == "SECRET-SHAPED-LINE"]
    return rep, flags


class TestAwsKeyParity(unittest.TestCase):
    def test_asia_temp_key_in_diff_is_flagged(self):
        rep, flags = _review_added(
            ["KNOWN_KEYS = [", f'    "{ASIA_KEY}",', "]"])
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["level"], "high")
        self.assertEqual(flags[0]["line"], 2)
        self.assertIn("token-prefix", flags[0]["detail"])
        blob = json.dumps(rep) + render_markdown(rep)
        self.assertNotIn(ASIA_KEY, blob)

    def test_akia_long_term_key_still_flagged(self):
        rep, flags = _review_added(
            ["KNOWN_KEYS = [", f'    "{AKIA_KEY}",', "]"])
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["line"], 2)
        blob = json.dumps(rep) + render_markdown(rep)
        self.assertNotIn(AKIA_KEY, blob)

    def test_asia_near_miss_is_not_flagged(self):
        # 15 chars after the prefix is not the AWS shape; Slice's
        # canonical pattern requires exactly 16 plus a word boundary.
        _, flags = _review_added(
            ["KNOWN_KEYS = [", f'    "{ASIA_SHORT}",', "]"])
        self.assertEqual(flags, [])


class TestAlignedTokenShapes(unittest.TestCase):
    def test_github_oauth_token_is_flagged(self):
        # List construction, so no labelled assignment can fire
        # first: only the token shape itself can catch this line.
        rep, flags = _review_added(
            ["ITEMS = [", f'    "{GHO_TOKEN}",', "]"])
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["line"], 2)
        self.assertIn("token-prefix", flags[0]["detail"])
        self.assertNotIn(GHO_TOKEN, json.dumps(rep) + render_markdown(rep))

    def test_anthropic_sk_key_is_flagged(self):
        rep, flags = _review_added(
            ["ITEMS = [", f'    "{SK_ANT_KEY}",', "]"])
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["line"], 2)
        self.assertIn("token-prefix", flags[0]["detail"])
        self.assertNotIn(SK_ANT_KEY, json.dumps(rep) + render_markdown(rep))

    def test_dsa_and_pgp_private_key_headers_are_flagged(self):
        _, flags = _review_added(
            ["-----BEGIN DSA PRIVATE KEY-----",
             "-----BEGIN PGP PRIVATE KEY BLOCK-----"])
        self.assertEqual(len(flags), 2)
        self.assertTrue(all("private-key-header" in f["detail"]
                            for f in flags))

    def test_password_in_url_is_flagged(self):
        rep, flags = _review_added([f'DATABASE_URL = "{DB_URL}"'])
        self.assertEqual(len(flags), 1)
        self.assertIn("password-in-url", flags[0]["detail"])
        self.assertNotIn("sup3rsecret",
                         json.dumps(rep) + render_markdown(rep))

    def test_credentials_labelled_assignment_is_flagged(self):
        rep, flags = _review_added(['credentials = "sup3rsecretvalue"'])
        self.assertEqual(len(flags), 1)
        self.assertIn("labelled-secret-assignment", flags[0]["detail"])
        self.assertNotIn("sup3rsecretvalue",
                         json.dumps(rep) + render_markdown(rep))


class TestAwsSecretContextGate(unittest.TestCase):
    def test_bare_40_with_aws_secret_context_is_flagged(self):
        rep, flags = _review_added([f"# rotated aws secret {BARE_40}"])
        self.assertEqual(len(flags), 1)
        self.assertIn("aws-secret-context", flags[0]["detail"])
        self.assertNotIn(BARE_40, json.dumps(rep) + render_markdown(rep))

    def test_bare_40_without_context_is_not_flagged(self):
        # Slice gates this shape on AWS-secret context; a bare
        # 40-char token alone (a checksum, a hash) is not flagged.
        _, flags = _review_added([f'CHECKSUM = "{BARE_40}"'])
        self.assertEqual(flags, [])


if __name__ == "__main__":
    unittest.main()
