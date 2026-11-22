"""Hardening regression tests (Oct 18, 2026, harden lane).

Every test pins a defect first demonstrated with a probe against
the unmodified tree (demonstrate-then-fix): crashes on valid JSON
with the wrong shape, invented gap/reason counts, a /dev/null path
bug on traditional diff -u headers, quoted copy paths left quoted,
case-sensitive secret extensions, a secretary.py false positive,
an MCP server killed by a non-object line, and a CLI traceback
(exit 1, i.e. "needs-attention") for an unwritable output dir.

Unit-level like test_polish.py: imports the package from src/
directly. No pre-existing test is touched.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostreview.core import build_review            # noqa: E402
from ghostreview.diffparse import parse_diff         # noqa: E402
from ghostreview.inputs import (load_scope_pack,     # noqa: E402
                                load_verify_report)
from ghostreview.mcp_server import serve             # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src"


def _proj(files):
    td = Path(tempfile.mkdtemp(prefix="gr-harden-"))
    for rel, content in files.items():
        fp = td / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    return td


def _one_file_diff(path, old="-x = 1", new="+x = 2"):
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -1,1 +1,1 @@\n{old}\n{new}\n")


class TestOptionalReportsWrongShape(unittest.TestCase):
    def setUp(self):
        self.proj = _proj({"a.py": "x = 1\n"})
        self.addCleanup(lambda: shutil.rmtree(self.proj,
                                              ignore_errors=True))
        self.diff = _one_file_diff("a.py")

    def _write(self, name, content):
        p = self.proj / name
        p.write_text(content)
        return str(p)

    def test_verify_non_object_json_is_unreadable_not_a_crash(self):
        # Pre-fix: AttributeError ('list' object has no attribute
        # 'get') propagated out of build_review as a traceback.
        path = self._write("verify.json", "[1, 2]")
        rec = load_verify_report(path)
        self.assertFalse(rec["present"])
        self.assertIn("unreadable", rec)
        rep = build_review(self.proj, self.diff, "file:x",
                           verify_report=path)
        self.assertTrue(any("Verify report" in n for n in rep["notes"]))

    def test_verify_non_object_post_and_tests_do_not_crash(self):
        path = self._write("verify.json", json.dumps(
            {"verdict": "pass", "exit_code": 0,
             "post": {"verdict": "pass", "tests": ["not", "a", "dict"]}}))
        rec = load_verify_report(path)
        self.assertTrue(rec["present"])
        self.assertIsNone(rec["post_tests_status"])
        path2 = self._write("verify2.json", json.dumps(
            {"verdict": "pass", "post": "a string, not an object"}))
        self.assertTrue(load_verify_report(path2)["present"])

    def test_verify_gap_counts_only_count_real_lists(self):
        # Pre-fix: len("abc") reported 3 hard gaps that do not exist.
        path = self._write("verify.json", json.dumps(
            {"verdict": "pass", "gaps": "abc", "soft_gaps": 7}))
        rec = load_verify_report(path)
        self.assertEqual(rec["hard_gaps"], 0)
        self.assertEqual(rec["soft_gaps"], 0)

    def test_scope_non_object_json_is_unreadable_not_a_crash(self):
        path = self._write("scope.json", "[1, 2]")
        rec = load_scope_pack(path)
        self.assertFalse(rec["present"])
        self.assertIn("unreadable", rec)

    def test_scope_reason_string_is_not_split_into_characters(self):
        # Pre-fix: risk_reasons "oops" was cited as the three
        # reasons 'o', 'p', 's' - reasons the pack never recorded.
        path = self._write("scope.json", json.dumps(
            {"files": [{"path": "a.py", "risk_reasons": "oops"}]}))
        rec = load_scope_pack(path)
        self.assertTrue(rec["present"])
        self.assertEqual(rec["risk_reasons"], [])
        self.assertEqual(rec["risk_reasons_by_file"], {})

    def test_scope_reason_dict_is_not_iterated_as_keys(self):
        path = self._write("scope.json", json.dumps(
            {"files": [{"path": "a.py", "risks": {"planted": 1}}]}))
        rec = load_scope_pack(path)
        self.assertEqual(rec["risk_reasons"], [])


class TestDiffParseHardening(unittest.TestCase):
    def test_out_of_range_octal_escape_in_quoted_path_does_not_crash(self):
        # Pre-fix: _c_unquote raised ValueError (byte must be in
        # range(0, 256)) on a \777 escape and killed the parse.
        diff = ('diff --git "a/we\\777ird.py" "b/we\\777ird.py"\n'
                '--- "a/we\\777ird.py"\n+++ "b/we\\777ird.py"\n'
                "@@ -1,1 +1,1 @@\n-x\n+y\n")
        (c,) = parse_diff(diff)
        self.assertEqual(c.added_count, 1)
        self.assertNotIn("\\777", c.path)

    def test_quoted_copy_paths_are_unquoted(self):
        # Pre-fix: copy from/to were taken verbatim, quotes and all,
        # unlike rename from/to which were unquoted.
        diff = ('diff --git "a/orig file.py" "b/copy file.py"\n'
                "similarity index 90%\n"
                'copy from "orig file.py"\ncopy to "copy file.py"\n'
                '--- "a/orig file.py"\n+++ "b/copy file.py"\n'
                "@@ -1,1 +1,1 @@\n-x\n+y\n")
        (c,) = parse_diff(diff)
        self.assertEqual(c.status, "copied")
        self.assertEqual(c.old_path, "orig file.py")
        self.assertEqual(c.new_path, "copy file.py")

    def test_tabbed_dev_null_marks_deleted_file(self):
        # Traditional diff -u output carries a timestamp after a
        # tab. Pre-fix the deleted file's path came out as
        # "/dev/null" and its status as "renamed".
        diff = ("--- a/foo.py\t2024-01-01 00:00:00\n"
                "+++ /dev/null\t2024-01-01 00:00:00\n"
                "@@ -1,1 +0,0 @@\n-x = 1\n")
        (c,) = parse_diff(diff)
        self.assertEqual(c.path, "foo.py")
        self.assertEqual(c.status, "deleted")

    def test_tabbed_dev_null_marks_added_file(self):
        diff = ("--- /dev/null\t2024-01-01 00:00:00\n"
                "+++ b/foo.py\t2024-01-01 00:00:00\n"
                "@@ -0,0 +1,1 @@\n+x = 1\n")
        (c,) = parse_diff(diff)
        self.assertEqual(c.path, "foo.py")
        self.assertEqual(c.status, "added")

    def test_tabbed_dev_null_deletion_reaches_the_review(self):
        proj = _proj({})
        self.addCleanup(lambda: shutil.rmtree(proj, ignore_errors=True))
        diff = ("--- a/foo.py\t2024-01-01 00:00:00\n"
                "+++ /dev/null\t2024-01-01 00:00:00\n"
                "@@ -1,1 +0,0 @@\n-x = 1\n")
        rep = build_review(proj, diff, "file:x")
        row = rep["changes"][0]
        self.assertEqual((row["path"], row["status"]), ("foo.py", "deleted"))
        self.assertIn("LARGE-DELETION", [r["rule"] for r in rep["risks"]])


class TestSecretPathHardening(unittest.TestCase):
    def _rules(self, path):
        proj = _proj({path: "x = 1\n"})
        self.addCleanup(lambda: shutil.rmtree(proj, ignore_errors=True))
        rep = build_review(proj, _one_file_diff(path), "file:x")
        return [r["rule"] for r in rep["risks"]]

    def test_uppercase_secret_extension_is_flagged(self):
        # Pre-fix: the extension check was case-sensitive, so
        # cert.PEM / cert.Key drew no SECRET-PATH flag at all.
        self.assertIn("SECRET-PATH", self._rules("cert.PEM"))
        self.assertIn("SECRET-PATH", self._rules("cert.Key"))

    def test_secretary_is_not_a_secret_path(self):
        # Pre-fix: "secretary.py" matched .*secret.* and drew a
        # high flag for an ordinary word.
        self.assertNotIn("SECRET-PATH", self._rules("secretary.py"))

    def test_secret_token_paths_still_flagged(self):
        self.assertIn("SECRET-PATH", self._rules("secret_key.py"))
        self.assertIn("SECRET-PATH", self._rules("config/credentials.json"))
        self.assertIn("SECRET-PATH", self._rules("app_secret.py"))


class TestMcpServerHardening(unittest.TestCase):
    def test_non_object_lines_do_not_kill_the_server(self):
        # Pre-fix: a JSON array line raised AttributeError inside
        # the error handler itself and ended serve(); the ping
        # after it was never answered.
        out = io.StringIO()
        rc = serve(stdin=io.StringIO(
            '[1, 2, 3]\n42\n'
            '{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n'),
            stdout=out)
        self.assertEqual(rc, 0)
        lines = [json.loads(ln) for ln in out.getvalue().splitlines()]
        self.assertTrue(any(ln.get("error", {}).get("code") == -32600
                            for ln in lines))
        self.assertTrue(any(ln.get("id") == 1 and ln.get("result") == {}
                            for ln in lines))


class TestCliHardening(unittest.TestCase):
    def test_unwritable_out_dir_is_a_clean_exit_2(self):
        # Pre-fix: write_reports raised through main() as a raw
        # traceback with exit 1 - the needs-attention code - for a
        # purely operational failure.
        proj = _proj({"a.py": "x = 1\n"})
        self.addCleanup(lambda: shutil.rmtree(proj, ignore_errors=True))
        diff = proj / "change.diff"
        diff.write_text(_one_file_diff("a.py"))
        blocker = proj / "blocker"
        blocker.write_text("a file, not a directory")
        env = dict(os.environ, PYTHONPATH=str(SRC))
        proc = subprocess.run(
            [sys.executable, "-m", "ghostreview", "review", str(proj),
             "--diff", str(diff), "-o", str(blocker)],
            capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("could not write reports", proc.stderr)


if __name__ == "__main__":
    unittest.main()
