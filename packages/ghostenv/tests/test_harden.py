"""Harden-round regression tests (improve 2026-10-18).

Every test pins a bug demonstrated before the fix:

- ``example -o <existing file>`` silently overwrote the file (the
  overwrite guard exempted -o), including the project's real
  ``.env`` - destroying its values despite the README promise that
  generation never modifies a real .env.
- A symlinked .env.example pointing at .env had the same effect
  with --force (no resolved-path check).
- The scanner followed symlinked source files out of the project,
  reading files PLAN says it must not read.
- A UTF-8 BOM on a .env file made its first name parse as
  malformed (blocking) and missing.
- Interior lines of a multi-line /* ... */ block comment were
  scanned as real reads.
- Bare dynamic reads (getenv(k), environ[k], environ.get(k)) were
  not counted as dynamic sites, unlike their os.* forms.
- Patterns fired cross-language: a Python pattern in a .js file
  (and vice versa) reported a "static" read.
- An OSError during a scan surfaced as a traceback instead of
  the documented exit 2 ("could not scan").
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

SENTINEL = "HARDEN_SENTINEL_do_not_print_or_destroy"


def make_project(root, files):
    proj = Path(root) / "proj"
    proj.mkdir(parents=True)
    for name, data in files.items():
        path = proj / name
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
    return proj


@unittest.skipUnless(helpers.cli_available(),
                     "ghostenv CLI not discoverable")
class HardenBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ge-harden-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp,
                                              ignore_errors=True))

    def check_json(self, proj):
        proc = helpers.run_cli(["check", str(proj), "--json"])
        return proc, json.loads(proc.stdout)

    def scan_json(self, proj):
        proc = helpers.run_cli(["scan", str(proj), "--json"])
        return proc, json.loads(proc.stdout)


class TestExampleOverwrite(HardenBase):
    BASE = {
        "app.py": 'import os\nX = os.environ["FOO"]\n',
        ".env": f"FOO={SENTINEL}\n",
        ".env.example": "FOO=\n",
    }

    def test_output_path_does_not_clobber_existing_file(self):
        proj = make_project(self.tmp, self.BASE)
        victim = self.tmp / "victim.txt"
        victim.write_text("important\n", encoding="utf-8")
        proc = helpers.run_cli(
            ["example", str(proj), "-o", str(victim)])
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(victim.read_text(encoding="utf-8"),
                         "important\n")

    def test_output_to_real_dotenv_refused_even_with_force(self):
        proj = make_project(self.tmp, self.BASE)
        proc = helpers.run_cli(
            ["example", str(proj), "-o", str(proj / ".env"),
             "--force"])
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual((proj / ".env").read_text(encoding="utf-8"),
                         f"FOO={SENTINEL}\n")

    def test_symlinked_example_pointing_at_dotenv_refused(self):
        proj = make_project(self.tmp, self.BASE)
        (proj / ".env.example").unlink()
        os.symlink(proj / ".env", proj / ".env.example")
        proc = helpers.run_cli(["example", str(proj), "--force"])
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual((proj / ".env").read_text(encoding="utf-8"),
                         f"FOO={SENTINEL}\n")

    def test_force_still_overwrites_a_plain_example_target(self):
        proj = make_project(self.tmp, self.BASE)
        proc = helpers.run_cli(["example", str(proj), "--force"])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = (proj / ".env.example").read_text(encoding="utf-8")
        self.assertIn("FOO=", text)
        self.assertNotIn(SENTINEL, text)


class TestSymlinkedSources(HardenBase):
    def test_symlink_outside_project_not_scanned_inside_is(self):
        proj = make_project(self.tmp, {
            "real.py": 'import os\nX = os.environ["INSIDE_NAME"]\n',
            ".env": "", ".env.example": ""})
        outside = self.tmp / "outside.py"
        outside.write_text(
            'import os\nY = os.environ["OUTSIDE_ONLY_NAME"]\n',
            encoding="utf-8")
        os.symlink(outside, proj / "escape.py")
        os.symlink(proj / "real.py", proj / "alias.py")
        _, rep = self.scan_json(proj)
        self.assertNotIn("OUTSIDE_ONLY_NAME", rep["used_in_code"])
        self.assertIn("INSIDE_NAME", rep["used_in_code"])


class TestBomEnvFile(HardenBase):
    def test_bom_first_name_parsed_not_malformed_and_no_leak(self):
        proj = make_project(self.tmp, {
            "app.py": 'import os\nX = os.environ["BOMKEY"]\n',
            ".env": b"\xef\xbb\xbfBOMKEY=" +
                    SENTINEL.encode() + b"\n",
            ".env.example": "BOMKEY=\n"})
        proc, rep = self.check_json(proj)
        self.assertEqual(proc.returncode, 0, rep.get("verdict"))
        self.assertEqual(rep["sets"]["defined_in_env"], ["BOMKEY"])
        self.assertEqual(rep["findings"]["malformed"], [])
        self.assertNotIn(SENTINEL, proc.stdout)
        self.assertNotIn(SENTINEL, proc.stderr)


class TestBlockComments(HardenBase):
    def test_block_comment_interior_not_scanned(self):
        proj = make_project(self.tmp, {
            "app.js": "/*\nconst a = process.env.IN_BLOCK_COMMENT;\n"
                      "*/ const b = process.env.AFTER_CLOSE;\n"
                      "const c = process.env.REAL_ONE;\n",
            ".env": "", ".env.example": ""})
        _, rep = self.scan_json(proj)
        self.assertNotIn("IN_BLOCK_COMMENT", rep["used_in_code"])
        self.assertIn("AFTER_CLOSE", rep["used_in_code"])
        self.assertIn("REAL_ONE", rep["used_in_code"])


class TestBareDynamicReads(HardenBase):
    def test_bare_dynamic_forms_count_as_dynamic_sites(self):
        proj = make_project(self.tmp, {
            "app.py": "from os import environ, getenv\n"
                      "a = getenv(k)\nb = environ[k]\n"
                      "c = environ.get(k)\n",
            ".env": "", ".env.example": ""})
        _, rep = self.scan_json(proj)
        self.assertEqual(rep["used_in_code"], [])
        self.assertEqual(len(rep["dynamic_sites"]), 3)


class TestCrossLanguagePatterns(HardenBase):
    def test_patterns_only_fire_in_their_own_language(self):
        proj = make_project(self.tmp, {
            "app.py": 's = "process.env.PYFILE_JS_NAME"\n'
                      'import os\nx = os.environ["PYFILE_PY_NAME"]\n',
            "app.js": 'const s = "os.environ.get(\\"JSFILE_PY_NAME\\")";\n'
                      "const y = process.env.JSFILE_JS_NAME;\n",
            ".env": "", ".env.example": ""})
        _, rep = self.scan_json(proj)
        self.assertNotIn("PYFILE_JS_NAME", rep["used_in_code"])
        self.assertNotIn("JSFILE_PY_NAME", rep["used_in_code"])
        self.assertIn("PYFILE_PY_NAME", rep["used_in_code"])
        self.assertIn("JSFILE_JS_NAME", rep["used_in_code"])


class TestScanErrorIsExit2(unittest.TestCase):
    """In-process: patch build_report to raise, as an unreadable
    file mid-scan would; main must return 2, not raise."""

    def test_oserror_from_build_report_returns_2(self):
        src = helpers.REPO_ROOT / "src"
        sys.path.insert(0, str(src))
        try:
            from ghostenv import cli
        finally:
            sys.path.remove(str(src))
        tmp = Path(tempfile.mkdtemp(prefix="ge-harden-err-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        err = io.StringIO()
        with mock.patch.object(cli, "build_report",
                               side_effect=OSError("fake io error")):
            with redirect_stderr(err):
                code = cli.main(["check", str(tmp)])
        self.assertEqual(code, 2)
        self.assertIn("could not scan", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main()
