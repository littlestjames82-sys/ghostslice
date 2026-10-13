"""v0.9 (G4): config slicing — the `structure` mode for YAML, TOML,
JSON, SQL, shell and PowerShell.

Golden tests per format, adversarial constructs (anchors, heredocs,
dollar-quoting, multi-row VALUES, dotted keys), the documented value
rule pinned in both directions (what is kept vs placeholdered), and
the security integration: planted secrets (assembled from fragments
so this file stays clean under the repo's own secret guard) must
never appear in structure/signatures output.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.cli import main as cli_main
from ghostslice.configslice import is_sensitive_key, render_scalar
from ghostslice.exporter import build_bundle, validate_bundle
from ghostslice.scanner import language_for
from ghostslice.selection import select_for_task_breakdown, symbols_for_source
from ghostslice.slicer import MODES, slice_text

# Planted secrets, assembled from fragments at runtime.
GH_TOKEN = "ghp_" + "a1B2c3D4e5F6" + "g7H8i9J0kLmNoPqRsTuVwXyZ"
LONG_SECRET = "corr" + "ect-horse-" + "battery-staple-" + "Tr0ub4dor&3-extra-long"
JWTISH = "eyJhbGciOi" + "JIUzI1NiIsInR5cCI6IkpXVCJ9" + ".payloadpart"
# Innocent-looking but scanner-shaped values used inside fixtures:
# written as @@ markers in the fixture text and substituted here,
# so no literal in this file trips the repo's own secret guard.
FAKE_TOKEN = "abcd" + "efghij" + "0123456789"
FAKE_SHORT = "abc123" + "def456" + "ghi789"


def _slice(path, text, mode):
    return slice_text(path, text, mode).text


class TestSensitiveKeyRule(unittest.TestCase):
    def test_sensitive_names(self):
        for name in ("password", "db_pass", "apiToken", "client-secret",
                     "aws_secret_access_key", "API_KEY", "auth_token",
                     "session_id", "credentials_file", "my_jwt",
                     "private", "master_password_hash"):
            self.assertTrue(is_sensitive_key(name), name)

    def test_innocent_names(self):
        for name in ("monkey", "keyboard", "tokenizer", "author",
                     "passage", "keylime", "hostname", "port", "timeout"):
            self.assertFalse(is_sensitive_key(name), name)

    def test_render_scalar_both_directions(self):
        self.assertEqual(render_scalar("5432", "port"), "5432")
        self.assertEqual(render_scalar("true", "enabled"), "true")
        self.assertEqual(render_scalar("production", "mode"), "production")
        self.assertEqual(render_scalar('"us-east-1"', "region"), '"us-east-1"')
        self.assertEqual(render_scalar('"${DB_URL}"', "url"), '"${DB_URL}"')
        # sensitive key: ALWAYS placeholdered, even a number / short word
        self.assertEqual(render_scalar("1234", "password"), '"…"')
        self.assertEqual(render_scalar("abc", "api_token"), '"…"')
        # free text and long strings under innocent keys
        self.assertEqual(render_scalar('"hello world, this is prose"', "note"), '"…"')
        self.assertEqual(render_scalar("a" * 40, "label"), '"…"')


YAML_GOLD = """\
# App configuration
# header line two

# Database settings
database:
  host: localhost
  port: 5432
  password: hunter2-is-wrong
  pool:
    size: 10
features:
  - auth
  - billing
  - reports
message: "a long free-text message that nobody needs"
mode: production
"""


class TestYaml(unittest.TestCase):
    def test_golden(self):
        out = _slice("config.yaml", YAML_GOLD, "structure")
        self.assertIn("# Database settings", out)
        self.assertIn("host: localhost", out)
        self.assertIn("port: 5432", out)
        self.assertIn('password: "…"', out)
        self.assertNotIn("hunter2", out)
        self.assertIn("size: 10", out)
        self.assertIn("mode: production", out)
        self.assertIn('message: "…"', out)
        # list of scalars: one exemplar + count
        self.assertIn("- auth", out)
        self.assertIn("- … (+2 more)", out)
        self.assertNotIn("- billing", out)

    def test_compound_sensitive_keys(self):
        src = "db_pass: abcdefghij\napiToken: abcdefghij\nclient-secret: abcdefghij\n"
        out = _slice("c.yaml", src, "structure")
        self.assertNotIn("abcdefghij", out)
        self.assertEqual(out.count('"…"'), 3)

    def test_list_of_maps_exemplar(self):
        src = ("servers:\n"
               "  - name: alpha\n"
               "    port: 8001\n"
               "  - name: beta\n"
               "    port: 8002\n")
        out = _slice("c.yaml", src, "structure")
        self.assertIn("- name: alpha", out)
        self.assertIn("port: 8001", out)
        self.assertIn("- … (+1 more)", out)
        self.assertNotIn("beta", out)

    def test_list_under_sensitive_key(self):
        src = "admin_passwords:\n  - first-secret-value\n  - second-secret-value\n"
        out = _slice("c.yaml", src, "structure")
        self.assertNotIn("secret-value", out)
        self.assertIn('- "…"', out)

    def test_block_scalar_placeholdered(self):
        src = ("notes: |\n"
               "  line one of prose\n"
               "  line two of prose\n"
               "after: 1\n")
        out = _slice("c.yaml", src, "structure")
        self.assertIn('notes: "…"', out)
        self.assertNotIn("line one of prose", out)
        self.assertIn("after: 1", out)

    def test_anchors_and_aliases(self):
        src = ("defaults: &defaults\n"
               "  retries: 3\n"
               "prod:\n"
               "  <<: *defaults\n"
               "level: &lvl production\n"
               "other: *lvl\n")
        out = _slice("c.yaml", src, "structure")
        self.assertIn("retries: 3", out)
        self.assertIn("*defaults", out)
        self.assertIn("&lvl production", out)
        self.assertIn("other: *lvl", out)

    def test_flow_map(self):
        src = 'limits: {retries: 3, label: "a long label that is prose"}\n'
        out = _slice("c.yaml", src, "structure")
        self.assertIn("retries: 3", out)
        self.assertNotIn("long label", out)

    def test_multi_document(self):
        src = "---\na: 1\n---\npassword: abcdefghij\n"
        out = _slice("c.yaml", src, "structure")
        self.assertIn("a: 1", out)
        self.assertNotIn("abcdefghij", out)
        self.assertEqual(out.count("---"), 2)

    def test_interfaces_placeholders_strings(self):
        out = _slice("c.yaml", "host: localhost\nport: 5432\n", "interfaces")
        self.assertIn('host: "…"', out)
        self.assertIn("port: 5432", out)

    def test_tab_indented_degrades_to_full(self):
        src = "a:\n\tb: 1\n"
        self.assertEqual(_slice("c.yaml", src, "structure"), src)

    def test_secret_in_yaml_never_leaks(self):
        src = (f"token: {GH_TOKEN}\n"
               f"wrapped: some text\n"
               f"  {GH_TOKEN}\n"
               f"cert: |\n"
               f"  {GH_TOKEN}\n"
               "list:\n"
               f"  - name: first\n"
               f"    value: {GH_TOKEN}\n")
        for mode in ("structure", "signatures"):
            out = _slice("c.yaml", src, mode)
            self.assertNotIn(GH_TOKEN, out, mode)


TOML_GOLD = """\
# Project file
[project]
name = "ghostslice"
version = "0.9.0"
level = 3

[tool.demo]
api_token = "@@FAKETOKEN@@"
greeting = "hello world this is a long greeting"
""".replace("@@FAKETOKEN@@", FAKE_TOKEN)


class TestToml(unittest.TestCase):
    def test_golden(self):
        out = _slice("pyproject.toml", TOML_GOLD, "structure")
        self.assertIn("[project]", out)
        self.assertIn('name = "ghostslice"', out)
        self.assertIn("level = 3", out)
        self.assertIn('api_token = "…"', out)
        self.assertNotIn("abcdefghij", out)
        self.assertIn('greeting = "…"', out)

    def test_dotted_key_sensitive_segment(self):
        src = 'tool.api.token_value = "abcdefghij0123456789"\n'
        out = _slice("c.toml", src, "structure")
        self.assertNotIn("abcdefghij", out)

    def test_arrays_and_inline_tables(self):
        src = ('ports = [8001, 8002]\n'
               'opts = { retries = 3, note = "long prose note here" }\n'
               'tags = ["alpha", "beta"]\n')
        out = _slice("c.toml", src, "structure")
        self.assertIn("ports = [8001, 8002]", out)
        self.assertIn("opts = {…}", out)
        self.assertNotIn("long prose", out)
        self.assertIn('tags = ["alpha", "beta"]', out)

    def test_multiline_string_and_array(self):
        src = ('desc = """\n'
               "a very long description\n"
               'spanning lines"""\n'
               "vals = [\n  1,\n  2,\n]\n"
               "after = 1\n")
        out = _slice("c.toml", src, "structure")
        self.assertIn('desc = "…"', out)
        self.assertNotIn("very long description", out)
        self.assertIn("vals = […]", out)
        self.assertIn("after = 1", out)

    def test_secret_in_toml_never_leaks(self):
        src = (f'api_key = "{GH_TOKEN}"\n'
               f'opts = {{ inner = "{GH_TOKEN}" }}\n'
               f'desc = """\n{GH_TOKEN}\n"""\n')
        out = _slice("c.toml", src, "structure")
        self.assertNotIn(GH_TOKEN, out)


JSON_GOLD = """{
  "name": "demo",
  "retries": 3,
  "enabled": true,
  "api_key": "@@FAKETOKEN@@",
  "items": [
    {"id": 1, "note": "first note is a long prose string"},
    {"id": 2, "note": "second"}
  ],
  "tags": ["alpha", "beta", "gamma"]
}
""".replace("@@FAKETOKEN@@", FAKE_TOKEN)


class TestJson(unittest.TestCase):
    def test_golden(self):
        out = _slice("data.json", JSON_GOLD, "structure")
        self.assertIn('"name": "demo"', out)
        self.assertIn('"retries": 3', out)
        self.assertIn('"enabled": true', out)
        self.assertIn('"api_key": "…"', out)
        self.assertNotIn("abcdefghij", out)
        self.assertIn('"id": 1', out)
        self.assertIn('"note": "…(len 33)"', out)
        self.assertIn("… (1 more items)", out)
        self.assertNotIn('"id": 2', out)
        self.assertIn('"alpha"', out)
        self.assertIn("… (2 more items)", out)

    def test_sensitive_container_replaced_wholesale(self):
        src = '{"credentials": {"user": "bob", "pass": "abcdefghij"}, "x": 1}'
        out = _slice("d.json", src, "structure")
        self.assertIn('"credentials": "…"', out)
        self.assertNotIn("abcdefghij", out)
        self.assertNotIn("bob", out)

    def test_invalid_json_degrades_to_full(self):
        src = "{not json at all"
        self.assertEqual(_slice("d.json", src, "structure"), src)
        self.assertEqual(_slice("d.json", src, "signatures"), src)

    def test_homogeneous_big_dict_collapses(self):
        deps = {f"pkg-{i:03d}": {"version": "1.0.0",
                                 "resolved": "https://registry.example.com/some/long/path.tgz",
                                 "integrity": "sha512-" + "A" * 80}
                for i in range(60)}
        import json as _json
        src = _json.dumps({"packages": deps}, indent=2)
        out = _slice("package-lock.json", src, "structure")
        self.assertIn("(+59 more entries)", out)
        self.assertLess(len(out), len(src) // 5)

    def test_secret_in_json_never_leaks(self):
        import json as _json
        src = _json.dumps({
            "plain": GH_TOKEN,
            "arr": [{"note": GH_TOKEN}, {"note": "ok"}],
            "nested": {"deep": {"value": LONG_SECRET}},
        })
        for mode in ("structure", "signatures"):
            out = _slice("d.json", src, mode)
            self.assertNotIn(GH_TOKEN, out, mode)
            self.assertNotIn(LONG_SECRET, out, mode)


SQL_GOLD = """\
-- widget schema
CREATE TABLE widgets (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL -- the name column
);
CREATE INDEX idx_widgets_name ON widgets (name);
INSERT INTO widgets (id, name) VALUES (1, 'a'), (2, 'b'), (3, 'c');
INSERT INTO backup SELECT * FROM widgets;
UPDATE widgets SET name = 'x' WHERE id = 1;
"""


class TestSql(unittest.TestCase):
    def test_golden_signatures(self):
        out = _slice("schema.sql", SQL_GOLD, "signatures")
        self.assertIn("CREATE TABLE widgets", out)
        self.assertIn("CREATE INDEX idx_widgets_name", out)
        self.assertIn("-- INSERT INTO widgets: 3 row(s) collapsed", out)
        self.assertIn("-- INSERT INTO backup (from SELECT", out)
        self.assertIn("-- UPDATE widgets: statement collapsed (1 line)", out)
        self.assertIn("-- widget schema", out)

    def test_interfaces_create_only(self):
        out = _slice("schema.sql", SQL_GOLD, "interfaces")
        self.assertIn("CREATE TABLE widgets", out)
        self.assertNotIn("INSERT", out)
        self.assertNotIn("UPDATE", out)

    def test_semicolons_inside_strings(self):
        src = "INSERT INTO t (a) VALUES ('x;y'), ('z');\nSELECT 1;\n"
        out = _slice("s.sql", src, "signatures")
        self.assertIn("2 row(s) collapsed", out)
        self.assertIn("-- SELECT: statement collapsed", out)

    def test_dollar_quoted_function_body(self):
        src = ("CREATE FUNCTION f() RETURNS void AS $$\n"
               "BEGIN\n  PERFORM 1;\n  PERFORM 2;\nEND;\n$$ LANGUAGE plpgsql;\n"
               "INSERT INTO t VALUES (1);\n")
        out = _slice("s.sql", src, "signatures")
        self.assertIn("PERFORM 2;", out)
        self.assertIn("-- INSERT INTO t: 1 row(s) collapsed", out)

    def test_insert_secret_values_collapse_away(self):
        src = f"INSERT INTO users (pw) VALUES ('{LONG_SECRET}');\n"
        out = _slice("s.sql", src, "signatures")
        self.assertNotIn(LONG_SECRET, out)


SHELL_GOLD = """\
#!/bin/bash
# deploy script
# (header block)

API_TOKEN="@@FAKESHORT@@"
REGION=us-east-1
export PATH=$PATH:/opt/bin

deploy() {
  echo "deploying to $REGION"
  curl -H "Authorization: Bearer @@FAKESHORT@@" https://example.com
}
# a trailing comment, dropped
echo "done"
""".replace("@@FAKESHORT@@", FAKE_SHORT)


class TestShell(unittest.TestCase):
    def test_golden_signatures(self):
        out = _slice("deploy.sh", SHELL_GOLD, "signatures")
        self.assertIn("#!/bin/bash", out)
        self.assertIn("# deploy script", out)
        self.assertIn('API_TOKEN="…"', out)
        self.assertIn("REGION=us-east-1", out)
        self.assertIn("export PATH=$PATH:/opt/bin", out)
        self.assertIn("deploy() { # ... }", out)
        self.assertNotIn("curl", out)
        self.assertNotIn("trailing comment", out)

    def test_top_level_heredoc_not_parsed(self):
        src = ("cat <<EOF\n"
               "FAKE_ASSIGNMENT=should-not-appear\n"
               "fake_func() {\n"
               "EOF\n"
               "REAL=production\n")
        out = _slice("s.sh", src, "signatures")
        self.assertNotIn("FAKE_ASSIGNMENT", out)
        self.assertNotIn("fake_func", out)
        self.assertIn("REAL=production", out)

    def test_one_line_function_collapses(self):
        # Audit F2: one-line bodies collapse like multi-line ones —
        # a body on one line can hold an assignment-shaped secret.
        src = "hi() { echo hi; }\nX=1\n"
        out = _slice("s.sh", src, "signatures")
        self.assertIn("hi() { # ... }", out)
        self.assertNotIn("echo hi", out)

    def test_one_line_function_secret_never_leaks(self):
        secret = "abc1" + "23def456" + "ghi789jkl012"
        src = f"f() {{ API_TOKEN={secret}; }}\nX=1\n"
        out = _slice("s.sh", src, "signatures")
        self.assertNotIn(secret, out)
        self.assertIn("X=1", out)

    def test_secret_in_shell_never_leaks(self):
        src = (f'TOKEN="{GH_TOKEN}"\n'
               f'curl -H "Authorization: Bearer {GH_TOKEN}" https://x.example\n')
        out = _slice("s.sh", src, "signatures")
        self.assertNotIn(GH_TOKEN, out)


PS_GOLD = """\
# Deploy script header
$ApiToken = "@@FAKESHORT@@"
$Region = "us-east-1"
$Count = 42
function Deploy-App {
  param($Target)
  Write-Host "deploying"
}
""".replace("@@FAKESHORT@@", FAKE_SHORT)


class TestPowerShell(unittest.TestCase):
    def test_golden_signatures(self):
        out = _slice("deploy.ps1", PS_GOLD, "signatures")
        self.assertIn("# Deploy script header", out)
        self.assertIn('$ApiToken = "…"', out)
        self.assertIn('$Region = "us-east-1"', out)
        self.assertIn("$Count = 42", out)
        self.assertIn("function Deploy-App { # ... }", out)
        self.assertNotIn("Write-Host", out)
        self.assertNotIn("param(", out)

    def test_here_string_placeholdered(self):
        src = ('$Body = @"\n'
               "some long body\n"
               "$Fake = 1\n"
               '"@\n'
               "$Real = 2\n")
        out = _slice("s.ps1", src, "signatures")
        self.assertIn('$Body = "…"', out)
        self.assertNotIn("some long body", out)
        self.assertNotIn("$Fake", out)
        self.assertIn("$Real = 2", out)


class TestAuditRegressions(unittest.TestCase):
    """G04 audit round 1 regressions (F1/F3/F4/F5)."""

    def test_f1_indentless_sensitive_sequence(self):
        src = ("admin_passwords:\n"
               "- first-secret-value\n"
               "- second-secret-value\n")
        out = _slice("c.yaml", src, "structure")
        self.assertNotIn("secret-value", out)
        self.assertIn('- "…"', out)

    def test_f1_indentless_plain_sequence_collapses(self):
        src = "features:\n- auth\n- billing\n- reports\n"
        out = _slice("c.yaml", src, "structure")
        self.assertIn("- auth", out)
        self.assertIn("- … (+2 more)", out)

    def test_f3_map_sequence_under_sensitive_key(self):
        src = ("credentials:\n"
               "  - user: bob\n"
               "    role: admin\n"
               "  - user: eve\n"
               "    role: user\n")
        out = _slice("c.yaml", src, "structure")
        self.assertNotIn("bob", out)
        self.assertNotIn("admin", out)
        self.assertIn('- "…"', out)

    def test_f4_blank_separated_list_collapses(self):
        src = ("features:\n"
               "  - auth\n"
               "\n"
               "  - billing\n"
               "  - reports\n")
        out = _slice("c.yaml", src, "structure")
        self.assertIn("- auth", out)
        self.assertIn("- … (+2 more)", out)
        self.assertNotIn("- billing", out)

    def test_g1_powershell_herestring_trailing_comment(self):
        src = ('$Body = @" # comment\n'
               "some body\n"
               "$Fake = 1\n"
               '"@\n'
               "$Real = 2\n")
        out = _slice("s.ps1", src, "signatures")
        self.assertIn('$Body = "…"', out)
        self.assertNotIn("$Fake", out)
        self.assertIn("$Real = 2", out)

    def test_g2_yaml_flow_list_item(self):
        src = ("items:\n"
               "  - {name: alpha, port: 8001}\n"
               "  - {name: beta, port: 8002}\n")
        out = _slice("c.yaml", src, "structure")
        self.assertIn("- { name: alpha, port: 8001 }", out)
        self.assertIn("- … (+1 more)", out)

    def test_f5_toml_trailing_comments(self):
        src = ('name = "ghostslice" # the name\n'
               "ports = [8001, 8002] # the ports\n")
        out = _slice("c.toml", src, "structure")
        self.assertIn('name = "ghostslice"', out)
        self.assertIn("ports = [8001, 8002]", out)


class TestWiring(unittest.TestCase):
    def test_modes_include_structure(self):
        self.assertIn("structure", MODES)

    def test_language_names(self):
        self.assertEqual(language_for("a.yaml"), "yaml")
        self.assertEqual(language_for("a.yml"), "yaml")
        self.assertEqual(language_for("a.toml"), "toml")
        self.assertEqual(language_for("a.sql"), "sql")
        self.assertEqual(language_for("a.sh"), "shell")
        self.assertEqual(language_for("a.ps1"), "powershell")
        self.assertEqual(language_for("a.json"), "json")

    def test_structure_on_code_is_full(self):
        src = "def f():\n    return 1\n"
        self.assertEqual(_slice("a.py", src, "structure"), src)

    def test_strip_tests_leaves_config_alone(self):
        src = "a: 1\n"
        self.assertEqual(_slice("c.yaml", src, "strip-tests"), src)

    def test_export_defaults_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config.yaml").write_text(YAML_GOLD)
            (root / "app.py").write_text("def f():\n    return 1\n")
            manifest = build_bundle(root, root / "out", record_history=False)
            modes = {f["path"]: f["mode"] for f in manifest["files"]}
            self.assertEqual(modes["config.yaml"], "full")
            self.assertEqual(modes["app.py"], "signatures")
            self.assertTrue(validate_bundle(root / "out")["ok"])

    def test_profile_can_opt_into_structure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config.yaml").write_text(YAML_GOLD)
            (root / ".ghostslice.json").write_text(
                '{"modes": {"*.yaml": "structure"}}')
            rc = cli_main(["export", str(root), "-o", str(root / "out")])
            self.assertEqual(rc, 0)
            manifest = build_bundle  # silence linter; manifest read below
            import json as _json
            m = _json.loads((root / "out" / "manifest.json").read_text())
            modes = {f["path"]: f["mode"] for f in m["files"]}
            self.assertEqual(modes["config.yaml"], "structure")
            sliced = (root / "out" / "files" / "config.yaml").read_text()
            self.assertNotIn("hunter2", sliced)

    def test_fit_with_structure_mode(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config.yaml").write_text(YAML_GOLD)
            (root / ".ghostslice.json").write_text(
                '{"modes": {"*.yaml": "structure"}}')
            rc = cli_main(["export", str(root), "-o", str(root / "out"),
                           "--fit", "100000"])
            self.assertEqual(rc, 0)
            import json as _json
            m = _json.loads((root / "out" / "manifest.json").read_text())
            modes = {f["path"]: f["mode"] for f in m["files"]}
            self.assertEqual(modes["config.yaml"], "structure")

    def test_cli_slice_tree_structure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config.yaml").write_text(YAML_GOLD)
            out = root / "sliced"
            rc = cli_main(["slice", str(root), "--mode", "structure", "-o", str(out)])
            self.assertEqual(rc, 0)
            text = (out / "config.yaml").read_text()
            self.assertIn('password: "…"', text)

    def test_config_keys_are_symbols(self):
        self.assertIn("billing_webhook",
                      symbols_for_source("yaml", "billing_webhook: x\n"))
        self.assertIn("deep_key",
                      symbols_for_source("json", '{"outer": {"deep_key": 1}}'))

    def test_task_selection_uses_config_symbols(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config.yaml").write_text("billing_webhook: enabled\nretries: 3\n")
            (root / "filler.py").write_text("X = 1\n")
            _r, _s, chosen, breakdown = select_for_task_breakdown(root, "webhook")
            self.assertIn("config.yaml", chosen)
            self.assertGreater(breakdown["config.yaml"]["symbol"], 0)


if __name__ == "__main__":
    unittest.main()
