"""v0.4: secret guard, notebook/markdown slicers, duplicates,
parser-lite hardening, HTML report, explain.

Fake secret values are assembled from string fragments at runtime so
this file itself contains no credential-shaped literals.
"""
import contextlib
import io
import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from ghostslice.cli import main as cli_main
from ghostslice.duplicates import find_duplicates
from ghostslice.exporter import build_bundle
from ghostslice.graph import build_graph, recommendations
from ghostslice.mcp_server import handle_message
from ghostslice.report import build_report
from ghostslice.scanner import scan
from ghostslice.secrets_scan import scan_text
from ghostslice.server import make_server
from ghostslice.slicer import slice_source, slice_text

AWS_KEY = "AKIA" + "Q7X2K9P4LM8N3R5T"
GH_TOKEN = "ghp_" + "Ab3dF6hJ9kL2mN5pQ8rS1tV4wX7yZ0aBcDeF"
SK_KEY = "sk-" + "ant-" + "Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0Lz9Xy8"
SLACK = "xoxb-" + "1234567890ab" + "-cdef34567890ab"
PRIVKEY = "-----BEGIN " + "PRIVATE KEY-----"
DB_PASS = "hunter2-super-secret-value"
URL_PASS = "s3cr3tP4ssw0rd"


class TestSecretsScan(unittest.TestCase):
    def types_for(self, text, path="x.py"):
        return {f["type"] for f in scan_text(path, text)}

    def test_known_token_shapes_hit(self):
        src = "\n".join([
            f'aws = "{AWS_KEY}"',
            f'gh = "{GH_TOKEN}"',
            f'key = "{SK_KEY}"',
            f'slack = "{SLACK}"',
            PRIVKEY,
        ])
        types = self.types_for(src)
        self.assertIn("aws-access-key", types)
        self.assertIn("github-token", types)
        self.assertIn("openai-or-anthropic-key", types)
        self.assertIn("slack-token", types)
        self.assertIn("private-key", types)

    def test_sensitive_assignment_hits(self):
        types = self.types_for(f'DATABASE_PASSWORD = "{DB_PASS}"\n')
        self.assertIn("sensitive-assignment", types)
        types = self.types_for("API_TOKEN=abc123def456ghi789jkl\n", path=".env")
        self.assertIn("sensitive-assignment", types)

    def test_password_in_url_hits(self):
        types = self.types_for(f'dsn = "postgres://user:{URL_PASS}@db.internal:5432/app"\n')
        self.assertIn("password-in-url", types)

    def test_high_entropy_assignment_hits(self):
        types = self.types_for('SOME_SETTING = "aB3$xY9!mQ7#zR2&kW8%pN4@vH6jT1"\n')
        self.assertIn("high-entropy-assignment", types)

    def test_findings_redacted_with_line_numbers(self):
        findings = scan_text("a.py", f'x = 1\naws = "{AWS_KEY}"\n')
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f["line"], 2)
        self.assertTrue(f["redacted"].startswith("AKIA"))
        self.assertNotIn(AWS_KEY, str(f))

    def test_placeholders_do_not_flag(self):
        src = "\n".join([
            "API_KEY=your-key-here",
            'TOKEN = "example-token-value"',
            "SECRET_KEY=xxxxxxxxxxxxxxxx",
            "PASSWORD=",
            "API_KEY=${API_KEY}",
            'APP_SECRET = "changeme"',
            'SAMPLE_KEY = "dummy-value-for-tests"',
            'FIXTURE_TOKEN = "fixture-token-123456"',
        ])
        self.assertEqual(scan_text("config.py", src), [])

    def test_benign_code_does_not_flag(self):
        src = "def add(a, b):\n    return a + b\n\nNAME = 'ghostslice'\nDEBUG = True\n"
        self.assertEqual(scan_text("app.py", src), [])

    def test_code_dict_literals_and_yaml_bare_values(self):
        code = ('manifest = {"total_saved_tokens": total_before - total_after,\n'
                '            "api_token_count": estimate_tokens(text)}\n')
        self.assertEqual(scan_text("exporter.py", code), [])
        yaml_src = "api_token: abc123def456ghi789jkl\n"
        self.assertIn("sensitive-assignment", self.types_for(yaml_src, path="config.yaml"))

    def test_code_references_and_instructions_do_not_flag(self):
        src = "\n".join([
            "this.requireTokens = !!opts.requireTokens;",
            "GHOSTBUS_KEY=choose-a-long-secret",
            "GHOSTBUS_ADMIN_KEY=pick-a-long-admin-secret",
            "token = config.token",
            "a.tokenHash = sha256(rawToken);",
        ])
        self.assertEqual(scan_text("app.js", src), [])

    def test_comment_examples_do_not_flag_assignments(self):
        src = '# API_KEY = "abcd1234efgh5678ijkl"\n# use your own key\nx = 1\n'
        self.assertEqual(scan_text("app.py", src), [])


def make_secret_project(root: Path):
    (root / "app.py").write_text("def main():\n    return 1\n")
    (root / "settings.py").write_text(f'DATABASE_PASSWORD = "{DB_PASS}"\n')


class TestSecretsIntegration(unittest.TestCase):
    def test_secrets_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); make_secret_project(root)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli_main(["secrets", str(root)]), 1)
            clean = Path(td) / "clean"; clean.mkdir()
            (clean / "a.py").write_text("x = 1\n")
            self.assertEqual(cli_main(["secrets", str(clean)]), 0)

    def test_export_exclude_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"; root.mkdir(); make_secret_project(root)
            out = Path(td) / "bundle"
            manifest = build_bundle(root, out, exclude_secrets=True, record_history=False)
            modes = {f["path"]: f["mode"] for f in manifest["files"]}
            self.assertEqual(modes["settings.py"], "exclude")
            self.assertNotEqual(modes["app.py"], "exclude")
            self.assertFalse((out / "files" / "settings.py").exists())

    def test_export_cli_warns_but_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"; root.mkdir(); make_secret_project(root)
            out = Path(td) / "bundle"
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                rc = cli_main(["export", str(root), "-o", str(out), "--exclude-secrets"])
            self.assertEqual(rc, 0)
            self.assertIn("settings.py", err.getvalue())
            self.assertNotIn(DB_PASS, err.getvalue())
            manifest = json.loads((out / "manifest.json").read_text())
            modes = {f["path"]: f["mode"] for f in manifest["files"]}
            self.assertEqual(modes["settings.py"], "exclude")

    def test_mcp_check_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); make_secret_project(root)
            resp = handle_message({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                   "params": {"name": "check_secrets",
                                              "arguments": {"path": td}}})
            payload = json.loads(resp["result"]["content"][0]["text"])
            self.assertGreaterEqual(payload["count"], 1)
            self.assertNotIn(DB_PASS, resp["result"]["content"][0]["text"])
            names = {t["name"] for t in handle_message(
                {"jsonrpc": "2.0", "id": 10, "method": "tools/list"})["result"]["tools"]}
            self.assertIn("check_secrets", names)

    def test_dashboard_secrets_api(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); make_secret_project(root)
            server, _state = make_server(str(root), port=0)
            port = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/secrets", timeout=10) as r:
                    data = json.loads(r.read().decode())
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/graph", timeout=10) as r:
                    graph = json.loads(r.read().decode())
            finally:
                server.shutdown(); server.server_close()
            self.assertGreaterEqual(data["count"], 1)
            self.assertNotIn(DB_PASS, json.dumps(data))
            self.assertIn("duplicates", graph)


NB = {
    "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": ["# Title\n", "Some intro text.\n"]},
        {"cell_type": "code", "execution_count": 7, "metadata": {},
         "outputs": [{"output_type": "stream", "name": "stdout", "text": ["OUTPUT_SHOULD_NOT_APPEAR\n"]}],
         "source": ["print('hello')\n", "x = 1\n"]},
        {"cell_type": "code", "execution_count": 8, "metadata": {}, "outputs": [],
         "source": ["import pytest\n", "def test_thing():\n", "    assert True\n"]},
    ],
    "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
}


class TestNotebookSlicer(unittest.TestCase):
    def setUp(self):
        self.src = json.dumps(NB)

    def test_signatures_strips_outputs_keeps_code_and_markdown(self):
        out = slice_source(self.src, "notebook", "signatures", path="nb.ipynb")
        self.assertIn("print('hello')", out)
        self.assertIn("# Title", out)
        self.assertNotIn("OUTPUT_SHOULD_NOT_APPEAR", out)
        self.assertNotIn("execution_count", out)

    def test_strip_tests_removes_test_cells(self):
        out = slice_source(self.src, "notebook", "strip-tests", path="nb.ipynb")
        self.assertIn("print('hello')", out)
        self.assertNotIn("test_thing", out)
        self.assertNotIn("pytest", out)

    def test_malformed_notebook_no_crash(self):
        self.assertEqual(slice_source("{not json", "notebook", "signatures", path="nb.ipynb"), "")
        self.assertEqual(slice_source("{not json", "notebook", "full", path="nb.ipynb"), "{not json")
        self.assertEqual(slice_source('{"no": "cells"}', "notebook", "signatures", path="nb.ipynb"), "")

    def test_scanner_recognises_notebook(self):
        r = slice_text("nb.ipynb", self.src, "signatures")
        self.assertEqual(r.language, "notebook")
        self.assertLess(r.sliced_tokens, r.original_tokens)


MD = """# Alpha

First paragraph line one.
First paragraph line two.

Second paragraph must be dropped here.

## Beta

Beta first paragraph only.

Beta second paragraph dropped.
"""


class TestMarkdownSlicer(unittest.TestCase):
    def test_headings_golden(self):
        out = slice_source(MD, "markdown", "headings", path="doc.md")
        self.assertIn("# Alpha", out)
        self.assertIn("First paragraph line one.", out)
        self.assertIn("First paragraph line two.", out)
        self.assertIn("## Beta", out)
        self.assertIn("Beta first paragraph only.", out)
        self.assertNotIn("Second paragraph must be dropped", out)
        self.assertNotIn("Beta second paragraph dropped.", out)

    def test_full_unchanged_and_default(self):
        self.assertEqual(slice_source(MD, "markdown", "full", path="doc.md"), MD)
        r = slice_text("doc.markdown", MD, "headings")
        self.assertEqual(r.language, "markdown")
        self.assertIn("# Alpha", r.text)


class TestDuplicates(unittest.TestCase):
    def make(self, root: Path):
        body = "def compute_total(items):\n    total = 0\n    for it in items:\n        total += it\n    return total\n"
        (root / "a.py").write_text(body)
        (root / "b.py").write_text(body)
        (root / "c.py").write_text("def different():\n    return 'unique content here for c'\n")
        lines = [f"shared content line number {i:02d} with padding text" for i in range(20)]
        (root / "d.txt").write_text("\n".join(lines) + "\n")
        (root / "e.txt").write_text("\n".join(lines[:-1] + ["changed final line that differs"]) + "\n")

    def test_exact_and_near_and_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self.make(root)
            dups = find_duplicates(scan(root))
            exact_files = [set(g["files"]) for g in dups["exact"]]
            self.assertIn({"a.py", "b.py"}, exact_files)
            near_pairs = [set(p["files"]) for p in dups["near"]]
            self.assertIn({"d.txt", "e.txt"}, near_pairs)
            all_flagged = set().union(*[set(g["files"]) for g in dups["exact"]],
                                      *[set(p["files"]) for p in dups["near"]]) if (dups["exact"] or dups["near"]) else set()
            self.assertNotIn("c.py", all_flagged)
            for p in dups["near"]:
                self.assertGreaterEqual(p["similarity"], 0.85)

    def test_duplicate_is_prune_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            body = "def helper():\n    return 42\n"
            (root / "copy1.py").write_text(body)
            (root / "copy2.py").write_text(body)
            (root / "main.py").write_text("import copy1\nimport copy2\n\ndef main():\n    return copy1.helper()\n")
            result = scan(root)
            recs = {r["path"]: r for r in recommendations(result, build_graph(result))}
            self.assertIn("copy2.py", recs)
            self.assertIn("duplicate", recs["copy2.py"]["reason"])


TS_ADVERSARIAL = '''export function tricky(): string {
  const tpl = `value } and ${1 + 2} end`;
  const s = "brace { here";
  const q = 'another } brace';
  // line comment with } and {{
  /* block } comment
     still } in comment */
  return tpl + s + q;
}

export function after(): number {
  const bodyMarker = 1;
  return bodyMarker;
}
'''

TS_MULTILINE_TEMPLATE = '''export function templated(): string {
  const msg = `
    template line with } brace
    and { another one
  `;
  return msg;
}

export function nextOne(): number {
  return 7;
}
'''

GO_ADVERSARIAL = '''package shop

func Tricky() string {
	s := "brace } here"
	// comment with }
	/* block } comment */
	return s
}

func After() int {
	return 1
}
'''

RUST_LIFETIME = """pub fn with_lifetime<'a>(x: &'a str) -> &'a str {
    let s = "}";
    let bodyMarker = s;
    x
}

pub fn after_two() -> i32 {
    7
}
"""


class TestParserLiteHardening(unittest.TestCase):
    def test_ts_strings_comments_template(self):
        out = slice_source(TS_ADVERSARIAL, "typescript", "signatures", path="a.ts")
        self.assertIn("function tricky", out)
        self.assertIn("function after", out)
        self.assertNotIn("bodyMarker", out)
        self.assertNotIn("return tpl", out)

    def test_ts_multiline_template_literal(self):
        out = slice_source(TS_MULTILINE_TEMPLATE, "typescript", "signatures", path="a.ts")
        self.assertIn("function templated", out)
        self.assertIn("function nextOne", out)
        self.assertNotIn("return msg", out)
        self.assertNotIn("return 7", out)

    def test_go_string_and_comments(self):
        out = slice_source(GO_ADVERSARIAL, "go", "signatures", path="a.go")
        self.assertIn("func Tricky() string", out)
        self.assertIn("func After() int", out)
        self.assertNotIn("return s", out)

    def test_rust_lifetimes_and_strings(self):
        out = slice_source(RUST_LIFETIME, "rust", "signatures", path="a.rs")
        self.assertIn("pub fn with_lifetime", out)
        self.assertIn("pub fn after_two", out)
        self.assertNotIn("bodyMarker", out)


class TestReport(unittest.TestCase):
    def test_report_totals_escaping_and_redaction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "weird<name>.py").write_text("def odd():\n    return 1\n" * 10)
            (root / "settings.py").write_text(f'DATABASE_PASSWORD = "{DB_PASS}"\n')
            html = build_report(root)
            self.assertIn("GhostSlice Report", html)
            self.assertIn("Files: 2", html)
            self.assertIn("6716f3", html)
            self.assertIn("weird&lt;name&gt;.py", html)
            self.assertNotIn("weird<name>", html)
            self.assertNotIn(DB_PASS, html)
            self.assertIn("sensitive-assignment", html)

    def test_report_cli(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"; root.mkdir()
            (root / "app.py").write_text("def main():\n    return 1\n")
            out = Path(td) / "report.html"
            self.assertEqual(cli_main(["report", str(root), "-o", str(out)]), 0)
            self.assertIn("GhostSlice Report", out.read_text())


class TestExplain(unittest.TestCase):
    def run_explain(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = cli_main(["explain", *argv])
        return rc, buf.getvalue()

    def test_explain_included_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "util.py").write_text("def helper():\n    return 42\n")
            (root / "main.py").write_text("from util import helper\n\ndef main():\n    return helper()\n")
            rc, out = self.run_explain(str(root), "util.py")
            self.assertEqual(rc, 0)
            self.assertIn("util.py: included", out)
            self.assertIn("mode: signatures", out)
            self.assertIn("main.py", out)  # importer listed

    def test_explain_gitignored_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".gitignore").write_text("secret.py\n")
            (root / "secret.py").write_text("x = 1\n")
            (root / "keep.py").write_text("y = 2\n")
            rc, out = self.run_explain(str(root), "secret.py")
            self.assertEqual(rc, 0)
            self.assertIn("NOT included", out)
            self.assertIn("gitignore", out)

    def test_explain_test_file_mode(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "test_app.py").write_text("def test_x():\n    assert True\n")
            rc, out = self.run_explain(str(root), "test_app.py")
            self.assertEqual(rc, 0)
            self.assertIn("strip-tests", out)


if __name__ == "__main__":
    unittest.main()
