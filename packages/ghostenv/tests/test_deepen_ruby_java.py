"""Deepen round: Ruby and Java/Kotlin env-read scanning.

PLAN named Ruby ``ENV[...]`` and Java (incl. Spring ``@Value``) as
the v0.2 language candidates, "labelled parser-lite if added".
This file pins that capability:

- Ruby: ``ENV["NAME"]``, ``ENV.fetch`` with a default argument
  (soft), with a block fallback (soft), or bare (hard), and a
  trailing ``||`` fallback (soft). ``#`` comment lines are not
  reads. Dynamic reads (``ENV[var]``, ``ENV["#{p}_KEY"]``) count
  as dynamic sites, names never guessed.
- Java/Kotlin: ``System.getenv("NAME")`` (hard, no default exists
  at that call), ``System.getenv().getOrDefault(..., default)``
  (soft), Kotlin ``?:`` elvis fallback (soft), Spring
  ``@Value("${NAME}")`` (hard) and ``@Value("${NAME:default}")``
  (soft). ``//`` comment lines are not reads. All new findings
  carry confidence ``parser-lite``.

Names-only invariant for the NEW capability: every default literal
in the fixtures below is a distinct FAKE canary. The canary test
asserts none of them appears on any output surface (scan / check,
text and JSON, example --stdout and the generated file), while the
NAMES do appear - the same bar as tests/test_leak.py, applied to
the new patterns whose whole job involves standing next to a
default value in source code.
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

RUBY_CANARY = "RUBY_CANARY_DEFAULT_do_not_print"
JAVA_CANARY = "JAVA_CANARY_DEFAULT_do_not_print"
SPRING_CANARY = "SPRING_CANARY_DEFAULT_do_not_print"
KOTLIN_CANARY = "KOTLIN_CANARY_DEFAULT_do_not_print"
BLOCK_CANARY = "BLOCK_CANARY_DEFAULT_do_not_print"
NEW_CANARIES = (RUBY_CANARY, JAVA_CANARY, SPRING_CANARY,
                KOTLIN_CANARY, BLOCK_CANARY)

RUBY_SRC = (
    'key = ENV["RUBY_PLAIN"]\n'
    f'd1 = ENV.fetch("RUBY_FETCH_DEFAULT", "{RUBY_CANARY}")\n'
    'd2 = ENV.fetch("RUBY_FETCH_PLAIN")\n'
    f'd3 = ENV.fetch("RUBY_FETCH_BLOCK") {{ "{BLOCK_CANARY}" }}\n'
    f'o = ENV["RUBY_OR"] || "{RUBY_CANARY}"\n'
    '# commented = ENV["RUBY_COMMENTED"]\n'
    'dyn = ENV[some_var]\n'
    'interp = ENV["#{prefix}_KEY"]\n'
)

JAVA_SRC = (
    'class App {\n'
    '  String a = System.getenv("JAVA_PLAIN");\n'
    f'  String b = System.getenv().getOrDefault("JAVA_DEFAULTED", '
    f'"{JAVA_CANARY}");\n'
    '  // String c = System.getenv("JAVA_COMMENTED");\n'
    '  @Value("${JAVA_SPRING}") String s;\n'
    f'  @Value("${{JAVA_SPRING_DEFAULT:{SPRING_CANARY}}}") String t;\n'
    '  String dyn = System.getenv(someVar);\n'
    '}\n'
)

KOTLIN_SRC = (
    f'val k = System.getenv("KOTLIN_ELVIS") ?: "{KOTLIN_CANARY}"\n'
    'val p = System.getenv("KOTLIN_PLAIN")\n'
)


def make_project(root, files):
    proj = Path(root) / "proj"
    proj.mkdir(parents=True)
    for name, text in files.items():
        (proj / name).write_text(text, encoding="utf-8")
    return proj


@unittest.skipUnless(helpers.cli_available(),
                     "ghostenv CLI not discoverable (see REPORT_B.md)")
class DeepenBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ge-deepen-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp,
                                              ignore_errors=True))

    def scan_json(self, proj):
        proc = helpers.run_cli(["scan", str(proj), "--json"])
        return proc, json.loads(proc.stdout)

    def check_json(self, proj):
        proc = helpers.run_cli(["check", str(proj), "--json"])
        return proc, json.loads(proc.stdout)

    def soft_hard(self, rep):
        f = rep["findings"]
        return ({x["name"] for x in f["missing_in_env_soft"]},
                {x["name"] for x in f["missing_in_env_hard"]})


class TestRubyScanning(DeepenBase):
    def project(self):
        return make_project(self.tmp, {
            "app.rb": RUBY_SRC, ".env": "", ".env.example": ""})

    def test_ruby_names_kinds_and_defaults(self):
        _, rep = self.scan_json(self.project())
        by_name = {u["name"]: u for u in rep["usages"]}
        self.assertEqual(by_name["RUBY_PLAIN"]["kind"],
                         "ruby-env-subscript")
        self.assertFalse(by_name["RUBY_PLAIN"]["has_default"])
        self.assertTrue(by_name["RUBY_FETCH_DEFAULT"]["has_default"])
        self.assertEqual(by_name["RUBY_FETCH_DEFAULT"]["kind"],
                         "ruby-env-fetch")
        self.assertFalse(by_name["RUBY_FETCH_PLAIN"]["has_default"])
        self.assertTrue(by_name["RUBY_FETCH_BLOCK"]["has_default"])
        self.assertTrue(by_name["RUBY_OR"]["has_default"])
        for u in by_name.values():
            self.assertEqual(u["confidence"], "parser-lite")

    def test_ruby_comment_line_is_not_a_read(self):
        _, rep = self.scan_json(self.project())
        self.assertNotIn("RUBY_COMMENTED", rep["used_in_code"])

    def test_ruby_dynamic_reads_counted_not_guessed(self):
        _, rep = self.scan_json(self.project())
        self.assertGreaterEqual(len(rep["dynamic_sites"]), 2)
        self.assertNotIn("KEY", rep["used_in_code"])

    def test_ruby_soft_hard_classification(self):
        _, rep = self.check_json(self.project())
        soft, hard = self.soft_hard(rep)
        self.assertIn("RUBY_FETCH_DEFAULT", soft)
        self.assertIn("RUBY_FETCH_BLOCK", soft)
        self.assertIn("RUBY_OR", soft)
        self.assertIn("RUBY_PLAIN", hard)
        self.assertIn("RUBY_FETCH_PLAIN", hard)


class TestJavaKotlinScanning(DeepenBase):
    def project(self):
        return make_project(self.tmp, {
            "App.java": JAVA_SRC, "main.kt": KOTLIN_SRC,
            ".env": "", ".env.example": ""})

    def test_java_names_kinds_and_defaults(self):
        _, rep = self.scan_json(self.project())
        by_name = {u["name"]: u for u in rep["usages"]}
        self.assertFalse(by_name["JAVA_PLAIN"]["has_default"])
        self.assertTrue(by_name["JAVA_DEFAULTED"]["has_default"])
        self.assertEqual(by_name["JAVA_DEFAULTED"]["kind"],
                         "java-getenv-or-default")
        self.assertEqual(by_name["JAVA_SPRING"]["kind"],
                         "java-spring-value")
        self.assertFalse(by_name["JAVA_SPRING"]["has_default"])
        self.assertTrue(
            by_name["JAVA_SPRING_DEFAULT"]["has_default"])
        self.assertTrue(by_name["KOTLIN_ELVIS"]["has_default"])
        self.assertFalse(by_name["KOTLIN_PLAIN"]["has_default"])
        for u in by_name.values():
            self.assertEqual(u["confidence"], "parser-lite")

    def test_java_comment_line_is_not_a_read(self):
        _, rep = self.scan_json(self.project())
        self.assertNotIn("JAVA_COMMENTED", rep["used_in_code"])

    def test_java_dynamic_read_counted_not_guessed(self):
        _, rep = self.scan_json(self.project())
        dyn_files = {d["file"] for d in rep["dynamic_sites"]}
        self.assertIn("App.java", dyn_files)

    def test_java_soft_hard_classification(self):
        _, rep = self.check_json(self.project())
        soft, hard = self.soft_hard(rep)
        self.assertIn("JAVA_DEFAULTED", soft)
        self.assertIn("JAVA_SPRING_DEFAULT", soft)
        self.assertIn("KOTLIN_ELVIS", soft)
        self.assertIn("JAVA_PLAIN", hard)
        self.assertIn("JAVA_SPRING", hard)
        self.assertIn("KOTLIN_PLAIN", hard)

    def test_defined_ruby_java_names_pass_check(self):
        proj = make_project(self.tmp, {
            "app.rb": 'x = ENV["SHARED_RB"]\n',
            "App.java": 'class A { String s = '
                        'System.getenv("SHARED_JAVA"); }\n',
            ".env": "SHARED_RB=fake\nSHARED_JAVA=fake\n",
            ".env.example": "SHARED_RB=\nSHARED_JAVA=\n"})
        proc, rep = self.check_json(proj)
        self.assertEqual(proc.returncode, 0, rep["verdict"])


class TestNewLanguageCanariesNeverLeak(DeepenBase):
    """Default literals in Ruby/Java/Kotlin/Spring source are
    values standing right next to the names GhostEnv reports.
    None may reach any output surface; the names must."""

    def project(self):
        proj = make_project(self.tmp, {
            "app.rb": RUBY_SRC, "App.java": JAVA_SRC,
            "main.kt": KOTLIN_SRC, ".env": "", ".env.example": ""})
        # Sanity: the canaries really are planted in the sources.
        blob = "".join(p.read_text(encoding="utf-8")
                       for p in proj.iterdir() if p.is_file())
        for canary in NEW_CANARIES:
            self.assertIn(canary, blob)
        return proj

    def test_no_new_canary_on_any_surface(self):
        proj = self.project()
        surfaces = [
            ["scan", str(proj)], ["scan", str(proj), "--json"],
            ["check", str(proj)], ["check", str(proj), "--json"],
            ["example", str(proj), "--stdout"],
        ]
        for args in surfaces:
            proc = helpers.run_cli(args)
            for canary in NEW_CANARIES:
                self.assertNotIn(canary, proc.stdout, str(args))
                self.assertNotIn(canary, proc.stderr, str(args))
        out = self.tmp / "generated.example"
        proc, generated = helpers.run_generate(proj, out)
        self.assertIsNotNone(generated)
        text = Path(generated).read_text(encoding="utf-8")
        for canary in NEW_CANARIES:
            self.assertNotIn(canary, proc.stdout)
            self.assertNotIn(canary, proc.stderr)
            self.assertNotIn(canary, text)
        # And the names DO survive onto the safe surfaces.
        scan = helpers.run_cli(["scan", str(proj)])
        for name in ("RUBY_PLAIN", "JAVA_PLAIN", "JAVA_SPRING",
                     "KOTLIN_PLAIN"):
            self.assertIn(name, scan.stdout)
            self.assertIn(f"{name}=", text)


if __name__ == "__main__":
    unittest.main()
