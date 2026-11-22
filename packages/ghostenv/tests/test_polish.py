"""Polish-round regression tests (Oct 14, 2026).

Every test here pins a bug demonstrated before the fix:

Pass 1 (doctor verdicts):
- A duplicate-only project exited 1 while its verdict read
  "contract complete: no missing names found".
- A case-mismatch-only project exited 1 with a verdict claiming
  "hard findings present" when the hard count was 0.
- Both spellings of a name present identically in all three sets
  (TOKEN + Token) fired a blocking case-mismatch, contradicting
  the PLAN definition (a name in ONE set vs a name in ANOTHER).
- Malformed .env lines were silently dropped: no finding at all,
  despite the README listing them as reported.

Pass 2 (parser-lite accuracy):
- Python setdefault("X", default) and `get(...) or fallback`
  classified hard; bare environ.get(...) not scanned at all.
- JS `??` fallback classified hard; `//` comment lines scanned.
- Rust var_os not scanned; .unwrap_or(...) classified hard.
- Shell ${NAME-default} (POSIX, no colon) not matched at all;
  `#` comment lines scanned.
- f-string env names vanished instead of counting as dynamic.

The malformed test doubles as leak coverage for the new surface:
a malformed line's content may be a bare value, so the report
carries its line number only and the content must never appear
in any output (PLAN names-only bar, same as the canary test).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

MALFORMED_CANARY = "MALFORMED_CANARY_do_not_print"


def make_project(root, files):
    proj = Path(root) / "proj"
    proj.mkdir(parents=True)
    for name, text in files.items():
        (proj / name).write_text(text, encoding="utf-8")
    return proj


@unittest.skipUnless(helpers.cli_available(),
                     "ghostenv CLI not discoverable (see REPORT_B.md)")
class PolishBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ge-polish-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp,
                                              ignore_errors=True))

    def check_json(self, proj):
        proc = helpers.run_cli(["check", str(proj), "--json"])
        return proc, json.loads(proc.stdout)

    def scan_json(self, proj):
        proc = helpers.run_cli(["scan", str(proj), "--json"])
        return proc, json.loads(proc.stdout)


class TestVerdictWording(PolishBase):
    def test_duplicate_only_verdict_names_the_duplicate(self):
        proj = make_project(self.tmp, {
            "app.py": 'import os\nX = os.environ.get("ONLY_DUP", "d")\n',
            ".env": "ONLY_DUP=fake_one\nONLY_DUP=fake_two\n",
            ".env.example": "ONLY_DUP=\n"})
        proc, rep = self.check_json(proj)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("duplicate", rep["verdict"])
        self.assertNotIn("contract complete", rep["verdict"])
        self.assertTrue(any("duplicate" in r
                            for r in rep["blocking_reasons"]))
        # Text surface agrees with the JSON verdict.
        text = helpers.run_cli(["check", str(proj)])
        self.assertIn(rep["verdict"], text.stdout)

    def test_case_mismatch_only_verdict_names_case_not_hard(self):
        proj = make_project(self.tmp, {
            "app.py": 'import os\nX = os.environ.get("API_URL", "d")\n',
            ".env": "API_URL=fake\n",
            ".env.example": "Api_Url=\n"})
        proc, rep = self.check_json(proj)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(rep["counts"]["missing_in_env_hard"], 0)
        self.assertIn("case-mismatch", rep["verdict"])
        self.assertNotIn("missing from .env, with no default",
                         rep["verdict"])

    def test_verdict_enumerates_every_blocking_reason(self):
        proj = make_project(self.tmp, {
            "app.py": 'import os\nX = os.environ["HARD_ONE"]\n',
            ".env": "DUP=fake_one\nDUP=fake_two\n",
            ".env.example": "DUP=\nHARD_ONE=\n"})
        proc, rep = self.check_json(proj)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("missing from .env", rep["verdict"])
        self.assertIn("duplicate", rep["verdict"])
        self.assertEqual(len(rep["blocking_reasons"]), 2)

    def test_both_spellings_everywhere_is_not_a_mismatch(self):
        proj = make_project(self.tmp, {
            "app.py": 'import os\nA = os.environ.get("TOKEN")\n'
                      'B = os.environ.get("Token")\n',
            ".env": "TOKEN=fake\nToken=fake\n",
            ".env.example": "TOKEN=\nToken=\n"})
        proc, rep = self.check_json(proj)
        self.assertEqual(proc.returncode, 0, rep["verdict"])
        self.assertEqual(rep["findings"]["case_mismatch"], [])
        self.assertTrue(rep["verdict"].startswith("contract complete"))

    def test_clean_fixture_verdict_and_empty_reasons(self):
        proj = helpers.copy_fixture("clean_project", self.tmp)
        proc, rep = self.check_json(proj)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(rep["blocking_reasons"], [])
        self.assertTrue(rep["verdict"].startswith("contract complete"))


class TestMalformedLines(PolishBase):
    def test_malformed_reported_by_line_number_and_blocks(self):
        proj = make_project(self.tmp, {
            "app.py": 'import os\nX = os.environ.get("FINE", "d")\n',
            ".env": "FINE=fake\n"
                    f"this line is {MALFORMED_CANARY} here\n",
            ".env.example": "FINE=\n"})
        proc, rep = self.check_json(proj)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(rep["findings"]["malformed"],
                         [{"where": "env", "lines": [2]}])
        self.assertEqual(rep["counts"]["malformed"], 1)
        self.assertIn("malformed", rep["verdict"])

    def test_malformed_line_content_never_leaks(self):
        proj = make_project(self.tmp, {
            "app.py": 'import os\nX = os.environ.get("FINE", "d")\n',
            ".env": "FINE=fake\n"
                    f"this line is {MALFORMED_CANARY} here\n",
            ".env.example": "FINE=\n"})
        for args in (["check", str(proj)], ["check", str(proj), "--json"],
                     ["scan", str(proj)], ["scan", str(proj), "--json"],
                     ["example", str(proj), "--stdout"]):
            proc = helpers.run_cli(args)
            self.assertNotIn(MALFORMED_CANARY, proc.stdout, str(args))
            self.assertNotIn(MALFORMED_CANARY, proc.stderr, str(args))


class TestParserAccuracy(PolishBase):
    def soft_hard(self, rep):
        f = rep["findings"]
        return ({x["name"] for x in f["missing_in_env_soft"]},
                {x["name"] for x in f["missing_in_env_hard"]})

    def test_python_setdefault_or_fallback_and_bare_get(self):
        proj = make_project(self.tmp, {
            "app.py": "import os\nfrom os import environ\n"
                      'A = os.environ.setdefault("PY_SETDEFAULT", "d")\n'
                      'B = os.environ.get("PY_OR") or "d"\n'
                      'C = environ.get("PY_BARE_GET", "d")\n'
                      'D = os.getenv("PY_PLAIN")\n',
            ".env": "", ".env.example": ""})
        _, rep = self.check_json(proj)
        soft, hard = self.soft_hard(rep)
        self.assertIn("PY_SETDEFAULT", soft)
        self.assertIn("PY_OR", soft)
        self.assertIn("PY_BARE_GET", soft)
        self.assertIn("PY_PLAIN", hard)

    def test_js_nullish_fallback_and_comment_lines(self):
        proj = make_project(self.tmp, {
            "app.js": 'const a = process.env.JS_NULLISH ?? "d";\n'
                      'const b = process.env.JS_PLAIN;\n'
                      '// const c = process.env.JS_COMMENTED;\n',
            ".env": "", ".env.example": ""})
        _, rep = self.check_json(proj)
        soft, hard = self.soft_hard(rep)
        self.assertIn("JS_NULLISH", soft)
        self.assertIn("JS_PLAIN", hard)
        self.assertNotIn("JS_COMMENTED", rep["sets"]["used_in_code"])

    def test_rust_var_os_and_unwrap_or(self):
        proj = make_project(self.tmp, {
            "main.rs": 'fn main() { '
                       'let a = env::var_os("RS_VAR_OS"); '
                       'let b = env::var("RS_UNWRAP")'
                       '.unwrap_or("d".into()); '
                       'let c = env::var("RS_PLAIN"); }\n',
            ".env": "", ".env.example": ""})
        _, rep = self.check_json(proj)
        soft, hard = self.soft_hard(rep)
        self.assertIn("RS_VAR_OS", hard)
        self.assertIn("RS_UNWRAP", soft)
        self.assertIn("RS_PLAIN", hard)

    def test_shell_posix_default_and_comment_lines(self):
        proj = make_project(self.tmp, {
            "run.sh": "#!/bin/sh\n"
                      "# docs mention $SHELL_COMMENTED here\n"
                      'echo "${SHELL_DEFAULTED-default}"\n'
                      'echo "$SHELL_PLAIN"\n',
            ".env": "", ".env.example": ""})
        _, rep = self.scan_json(proj)
        by_name = {u["name"]: u for u in rep["usages"]}
        self.assertIn("SHELL_DEFAULTED", by_name)
        self.assertTrue(by_name["SHELL_DEFAULTED"]["has_default"])
        self.assertIn("SHELL_PLAIN", by_name)
        self.assertFalse(by_name["SHELL_PLAIN"]["has_default"])
        self.assertNotIn("SHELL_COMMENTED", by_name)

    def test_fstring_name_counts_as_dynamic_site(self):
        proj = make_project(self.tmp, {
            "app.py": 'import os\nK = os.getenv(f"{PREFIX}_KEY")\n',
            ".env": "", ".env.example": ""})
        _, rep = self.scan_json(proj)
        self.assertGreaterEqual(len(rep["dynamic_sites"]), 1)
        self.assertEqual(rep["used_in_code"], [])


if __name__ == "__main__":
    unittest.main()
