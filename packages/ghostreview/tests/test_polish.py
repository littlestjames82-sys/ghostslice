"""Polish regression tests (Oct 14, 2026).

Every test here pins a defect that was first demonstrated with a
probe fixture before the fix (demonstrate-then-fix), or locks in
behaviour the probe showed was already correct. Unit-level: these
import the package from src/ directly. The 43 pre-existing
black-box tests are untouched.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostreview.core import build_review          # noqa: E402
from ghostreview.dependents import find_dependents  # noqa: E402
from ghostreview.diffparse import parse_diff        # noqa: E402
from ghostreview.inputs import load_scope_pack      # noqa: E402
from ghostreview.mcp_server import _capped          # noqa: E402
from ghostreview.reports import render_markdown     # noqa: E402

POLISH_FAKE = "FAKE-POLISH-SECRET-99999"


def _proj(files):
    td = Path(tempfile.mkdtemp(prefix="gr-polish-"))
    for rel, content in files.items():
        fp = td / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    return td


class TestParserPolish(unittest.TestCase):
    def test_quoted_paths_are_unquoted(self):
        diff = ('diff --git "a/my file.py" "b/my file.py"\n'
                '--- "a/my file.py"\n+++ "b/my file.py"\n'
                "@@ -1,1 +1,1 @@\n-old\n+new\n")
        (c,) = parse_diff(diff)
        self.assertEqual(c.path, "my file.py")
        self.assertNotIn('"', c.path)
        self.assertEqual(c.added_count, 1)

    def test_header_collision_inside_hunk_is_content(self):
        # A deleted line whose text starts with "-- " and an added
        # line whose text starts with "++ " appear as ---/+++ and
        # were parsed as file headers, corrupting both paths and
        # losing both lines.
        diff = ("diff --git a/cfg.txt b/cfg.txt\n--- a/cfg.txt\n"
                "+++ b/cfg.txt\n@@ -1,2 +1,2 @@\n"
                "--- old banner\n+++ new banner\n context\n")
        (c,) = parse_diff(diff)
        self.assertEqual(c.path, "cfg.txt")
        self.assertEqual(c.deleted, [(1, "-- old banner")])
        self.assertEqual(c.added, [(1, "++ new banner")])

    def test_headerless_second_file_still_parsed(self):
        diff = ("--- a/one.txt\n+++ b/one.txt\n@@ -1,1 +1,1 @@\n-a\n+b\n"
                "--- a/two.txt\n+++ b/two.txt\n@@ -1,1 +1,1 @@\n-c\n+d\n")
        changes = parse_diff(diff)
        self.assertEqual([c.path for c in changes], ["one.txt", "two.txt"])
        self.assertTrue(all(c.added_count == 1 for c in changes))

    def test_mode_only_change_is_recorded(self):
        diff = ("diff --git a/run.sh b/run.sh\nold mode 100644\n"
                "new mode 100755\n")
        (c,) = parse_diff(diff)
        self.assertEqual((c.old_mode, c.new_mode), ("100644", "100755"))
        self.assertTrue(c.mode_changed)

    def test_mode_change_reaches_the_review(self):
        proj = _proj({"run.sh": "echo hi\n"})
        self.addCleanup(lambda: shutil.rmtree(proj, ignore_errors=True))
        diff = ("diff --git a/run.sh b/run.sh\nold mode 100644\n"
                "new mode 100755\n")
        rep = build_review(proj, diff, "file:x")
        row = rep["changes"][0]
        self.assertTrue(row["mode_changed"])
        md = render_markdown(rep)
        self.assertIn("mode changed from 100644 to 100755", md)

    def test_copy_is_not_reported_as_rename(self):
        diff = ("diff --git a/orig.py b/copy.py\nsimilarity index 90%\n"
                "copy from orig.py\ncopy to copy.py\n--- a/orig.py\n"
                "+++ b/copy.py\n@@ -1,1 +1,1 @@\n-x\n+y\n")
        (c,) = parse_diff(diff)
        self.assertEqual(c.status, "copied")
        self.assertEqual(c.old_path, "orig.py")

    def test_no_newline_marker_keeps_counts_and_numbers(self):
        # Probe showed this was already correct; locked in.
        diff = ("diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n"
                "@@ -1,2 +1,2 @@\n-first\n\\ No newline at end of file\n"
                "+second\n\\ No newline at end of file\n")
        (c,) = parse_diff(diff)
        self.assertEqual(c.deleted, [(1, "first")])
        self.assertEqual(c.added, [(1, "second")])

    def test_secret_in_colliding_added_line_flags_without_value(self):
        diff = ("diff --git a/cfg.py b/cfg.py\n--- a/cfg.py\n"
                "+++ b/cfg.py\n@@ -1,1 +1,1 @@\n-old\n"
                f'+++ api_key = "{POLISH_FAKE}"\n')
        proj = _proj({"cfg.py": "old\n"})
        self.addCleanup(lambda: shutil.rmtree(proj, ignore_errors=True))
        rep = build_review(proj, diff, "file:x")
        rules = [r["rule"] for r in rep["risks"]]
        self.assertIn("SECRET-SHAPED-LINE", rules)
        blob = json.dumps(rep) + render_markdown(rep)
        self.assertNotIn(POLISH_FAKE, blob)


class TestDependentsPolish(unittest.TestCase):
    def _deps(self, files, changed):
        proj = _proj(files)
        self.addCleanup(lambda: shutil.rmtree(proj, ignore_errors=True))
        return find_dependents(proj, {changed}, {changed})[changed]["dependents"]

    def test_from_package_import_submodule(self):
        deps = self._deps(
            {"main.py": "from pkg import helper\n", "pkg/__init__.py": "",
             "pkg/helper.py": "x = 1\n"}, "pkg/helper.py")
        self.assertEqual(deps, ["main.py"])

    def test_import_package_finds_init(self):
        deps = self._deps(
            {"main.py": "import pkg\n", "pkg/__init__.py": "X = 1\n"},
            "pkg/__init__.py")
        self.assertEqual(deps, ["main.py"])

    def test_relative_dot_import(self):
        deps = self._deps(
            {"pkg/__init__.py": "", "pkg/main.py": "from . import helper\n",
             "pkg/helper.py": "x = 1\n"}, "pkg/helper.py")
        self.assertEqual(deps, ["pkg/main.py"])

    def test_comma_import(self):
        deps = self._deps(
            {"main.py": "import os, pricing\n", "pricing.py": "x = 1\n"},
            "pricing.py")
        self.assertEqual(deps, ["main.py"])

    def test_js_bare_side_effect_import(self):
        deps = self._deps(
            {"main.js": "import './util.js';\n",
             "util.js": "export const x = 1;\n"}, "util.js")
        self.assertEqual(deps, ["main.js"])

    def test_js_extensionless_mjs(self):
        deps = self._deps(
            {"main.js": "import {x} from './util';\n",
             "util.mjs": "export const x = 1;\n"}, "util.mjs")
        self.assertEqual(deps, ["main.js"])

    def test_js_extensionless_index_mjs(self):
        deps = self._deps(
            {"main.js": "import {x} from './lib';\n",
             "lib/index.mjs": "export const x = 1;\n"}, "lib/index.mjs")
        self.assertEqual(deps, ["main.js"])

    def test_negative_bare_stem_other_directory_not_claimed(self):
        deps = self._deps(
            {"other/main.py": "import helper\n", "pkg/helper.py": "x = 1\n"},
            "pkg/helper.py")
        self.assertEqual(deps, [])

    def test_negative_from_init_attribute_not_a_submodule_edge(self):
        deps = self._deps(
            {"main.py": "from pkg import thing\n",
             "pkg/__init__.py": "thing = 1\n", "pkg/helper.py": "x = 1\n"},
            "pkg/helper.py")
        self.assertEqual(deps, [])


class TestCitationsAndCapsPolish(unittest.TestCase):
    def setUp(self):
        self.proj = _proj({"a.py": "x = 1\n"})
        self.addCleanup(lambda: shutil.rmtree(self.proj, ignore_errors=True))
        self.diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                     "@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n")

    def test_verify_nonpass_verdict_without_exit_code_flags(self):
        vr = self.proj / "verify.json"
        vr.write_text(json.dumps({"verdict": "gaps_found",
                                  "gaps": [{"file": "a.py"}]}))
        rep = build_review(self.proj, self.diff, "file:x",
                           verify_report=str(vr))
        self.assertIn("VERIFY-FAILED", [r["rule"] for r in rep["risks"]])
        self.assertEqual(rep["verdict"], "needs-attention")

    def test_verify_pass_verdict_without_exit_code_does_not_flag(self):
        vr = self.proj / "verify.json"
        vr.write_text(json.dumps({"verdict": "sufficient", "gaps": []}))
        rep = build_review(self.proj, self.diff, "file:x",
                           verify_report=str(vr))
        self.assertNotIn("VERIFY-FAILED", [r["rule"] for r in rep["risks"]])

    def test_scope_changed_list_is_read(self):
        sp = self.proj / "scope.json"
        sp.write_text(json.dumps(
            {"changed": [{"path": "a.py", "risk_reasons": ["only here"]}]}))
        rec = load_scope_pack(str(sp))
        self.assertTrue(rec["present"])
        self.assertEqual(rec["risk_reasons_by_file"], {"a.py": ["only here"]})

    def test_scope_reasons_keep_file_attribution_and_entry_count(self):
        sp = self.proj / "scope.json"
        sp.write_text(json.dumps({"files": [
            {"path": "a.py", "risk_reasons": ["exported API", "6 callers"]},
            {"path": "b.py", "risk_reasons": ["exported API"]}]}))
        rep = build_review(self.proj, self.diff, "file:x", scope_pack=str(sp))
        self.assertEqual(rep["scope"]["risk_reason_entries"], 3)
        md = render_markdown(rep)
        self.assertIn("Scope risk reason for `b.py`: exported API", md)
        self.assertIn("with 3 risk reason(s) recorded", rep["verdict_summary"])

    def test_summary_caps_risk_listing_but_json_keeps_all(self):
        files = {f"cfg{i}.toml": "x = 1\n" for i in range(6)}
        proj = _proj(files)
        self.addCleanup(lambda: shutil.rmtree(proj, ignore_errors=True))
        diff = "".join(
            f"diff --git a/cfg{i}.toml b/cfg{i}.toml\n--- a/cfg{i}.toml\n"
            f"+++ b/cfg{i}.toml\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
            for i in range(6))
        rep = build_review(proj, diff, "file:x")
        self.assertGreaterEqual(len(rep["risks"]), 6)
        self.assertIn("more risk(s)", rep["verdict_summary"])

    def test_mcp_caps_changes_and_dependents(self):
        big = {"risks": [],
               "changes": [{"path": f"f{i}.py"} for i in range(300)],
               "dependents": {"a.py": {"dependents":
                                       [f"d{i}.py" for i in range(120)]}},
               "verdict_summary": "x"}
        cap = _capped(big)
        self.assertEqual(len(cap["changes"]), 50)
        self.assertEqual(cap["changes_total"], 300)
        self.assertEqual(len(cap["dependents"]["a.py"]["dependents"]), 50)
        self.assertTrue(cap["dependents"]["a.py"]["dependents_truncated"])

    def test_verdict_gloss_in_plain_words(self):
        rep = build_review(self.proj, self.diff, "file:x")
        md = render_markdown(rep)
        self.assertIn("In plain words:", md)


if __name__ == "__main__":
    unittest.main()
