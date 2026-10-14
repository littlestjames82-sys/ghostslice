"""v0.11 (G6): context lint — rule engine over the exporter's own
mode resolution (exporter.resolve_modes, shared with build_bundle).

Every rule fires on a purpose-built fixture and stays silent on a
clean one; profile overrides (off / severity / thresholds) and the
exit-code contract (default: 1 only on error severity; --strict
promotes warnings; 2 for config/usage errors) are pinned. Secret
shapes are assembled from fragments so this file stays clean under
the repo's own guard.
"""
import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.cli import main as cli_main
from ghostslice.exporter import build_bundle, resolve_modes
from ghostslice.lint import RULES, lint_exit_code, lint_project
from ghostslice.mcp_server import handle_message
from ghostslice.profile import load_profile
from ghostslice.scanner import scan
from ghostslice.server import make_server

AKIA = "AK" + "IA" + "J7K9" + "Q2XZ" + "4B8N" + "6M3P"  # AKIA + 16


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def write_profile(root: Path, data: dict) -> None:
    write(root, ".ghostslice.json", json.dumps(data))


def lint(root: Path) -> dict:
    return lint_project(root, profile=load_profile(root))


def by_rule(payload: dict, rule: str) -> list[dict]:
    return [f for f in payload["findings"] if f["rule"] == rule]


def run_cli(argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main(argv)
    return code, out.getvalue(), err.getvalue()


def clean_project(root: Path) -> None:
    write(root, "main.py", "from helper import add\n\n\ndef main():\n    return add(1, 2)\n")
    write(root, "helper.py", "def add(a, b):\n    return a + b\n")


def fat_python(nfuncs: int = 80) -> str:
    parts = []
    for i in range(nfuncs):
        parts.append(f"def handler_{i}(request):")
        for j in range(12):
            parts.append(f"    value_{j} = request.field_{j} + {j} * {i}")
        parts.append("    return value_0")
        parts.append("")
    return "\n".join(parts)


class LintCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class TestCleanFixture(LintCase):
    def test_no_findings_and_exit_zero(self):
        clean_project(self.root)
        payload = lint(self.root)
        self.assertEqual(payload["findings"], [])
        self.assertEqual(payload["counts"], {"error": 0, "warn": 0, "info": 0})
        self.assertEqual(lint_exit_code(payload), 0)
        self.assertEqual(lint_exit_code(payload, strict=True), 0)

    def test_cli_clean(self):
        clean_project(self.root)
        code, out, _ = run_cli(["lint", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("No findings", out)
        code, out, _ = run_cli(["lint", str(self.root), "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["counts"]["error"], 0)
        self.assertEqual(data["token_method"], payload_method(data))

    def test_payload_modes_match_exporter_manifest(self):
        # The anti-divergence pin: lint's resolved modes must equal
        # the modes build_bundle writes into a real manifest.
        clean_project(self.root)
        write_profile(self.root, {"modes": {"helper.py": "full"}})
        payload = lint(self.root)
        manifest = build_bundle(self.root, self.root / "bundle",
                                profile=load_profile(self.root),
                                record_history=False)
        manifest_modes = {f["path"]: f["mode"] for f in manifest["files"]}
        self.assertEqual(payload["modes"], manifest_modes)
        self.assertEqual(payload["modes"]["helper.py"], "full")


def payload_method(data):
    return data["token_method"]


class TestL001Oversize(LintCase):
    def test_default_threshold_fires_on_huge_full_file(self):
        line = "The quick brown fox jumps over the lazy dog and runs through the forest.\n"
        write(self.root, "big.md", line * 4000)
        payload = lint(self.root)
        hits = by_rule(payload, "L001")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"], "big.md")
        entry = {f.path: f for f in scan(self.root).files}["big.md"]
        self.assertGreater(entry.tokens, 20000)
        self.assertEqual(hits[0]["tokens"], entry.tokens)

    def test_threshold_override_and_default_silence(self):
        write(self.root, "notes.txt", "word " * 400 + "\n" * 5)
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L001"), [])  # under 20k default
        write_profile(self.root, {"lint": {"L001": {"threshold_tokens": 100}}})
        payload = lint(self.root)
        self.assertEqual(len(by_rule(payload, "L001")), 1)

    def test_big_code_file_at_signatures_is_silent(self):
        body = "".join(f"def f{i}(x):\n    return x + {i}\n" for i in range(2200))
        write(self.root, "module.py", body)
        entry = {f.path: f for f in scan(self.root).files}["module.py"]
        self.assertGreater(entry.tokens, 20000)
        payload = lint(self.root)
        self.assertEqual([f for f in by_rule(payload, "L001")
                          if f["path"] == "module.py"], [])


class TestL002FullModeSlicable(LintCase):
    def test_fires_when_profile_forces_full(self):
        write(self.root, "fat.py", fat_python())
        write_profile(self.root, {"modes": {"fat.py": "full"}})
        payload = lint(self.root)
        hits = by_rule(payload, "L002")
        self.assertEqual(len(hits), 1)
        self.assertGreaterEqual(hits[0]["savings"], 2000)
        self.assertGreaterEqual(hits[0]["savings"], 0.6 * hits[0]["tokens"])

    def test_silent_at_default_signatures(self):
        write(self.root, "fat.py", fat_python())
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L002"), [])

    def test_silent_when_saving_too_small(self):
        write(self.root, "tiny.py", "def add(a, b):\n    return a + b\n")
        write_profile(self.root, {"modes": {"tiny.py": "full"}})
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L002"), [])


class TestL003DeadWeight(LintCase):
    def test_orphan_fires(self):
        write(self.root, "main.py", "def main():\n    print('hi')\n")
        write(self.root, "orphan.py", "def unused():\n    return 42\n")
        payload = lint(self.root)
        hits = [f for f in by_rule(payload, "L003") if f["path"] == "orphan.py"]
        self.assertEqual(len(hits), 1)
        # Audit G1: the message itself carries the token cost; the
        # CLI no longer appends a duplicate "(est. ...)" suffix.
        self.assertIn("estimated tokens", hits[0]["message"])

    def test_excluded_orphan_is_silent(self):
        write(self.root, "main.py", "def main():\n    print('hi')\n")
        write(self.root, "orphan.py", "def unused():\n    return 42\n")
        write_profile(self.root, {"modes": {"orphan.py": "exclude"}})
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L003"), [])


DUP_BODY = "\n".join(
    [f"def fn_{i}(x):\n    y = x * {i} + len('abcdefghij')\n    return y" for i in range(10)]) + "\n"


class TestL004Duplicates(LintCase):
    def test_exact_duplicate_fires_on_second_copy(self):
        write(self.root, "a.py", DUP_BODY)
        write(self.root, "b.py", DUP_BODY)
        payload = lint(self.root)
        hits = by_rule(payload, "L004")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"], "b.py")
        self.assertIn("exact duplicate of a.py", hits[0]["message"])

    def test_near_duplicate_fires(self):
        write(self.root, "a.py", DUP_BODY)
        write(self.root, "c.py", DUP_BODY.replace("x * 3", "x * 33", 1))
        payload = lint(self.root)
        hits = by_rule(payload, "L004")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"], "c.py")
        self.assertIn("near-duplicate", hits[0]["message"])

    def test_excluded_copy_is_silent(self):
        write(self.root, "a.py", DUP_BODY)
        write(self.root, "b.py", DUP_BODY)
        write_profile(self.root, {"modes": {"b.py": "exclude"}})
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L004"), [])

    def test_keep_reference_is_first_included_copy(self):
        # Audit F1: with the group's first file excluded, the finding
        # must name the first INCLUDED copy as the reference, not the
        # excluded original.
        write(self.root, "a.py", DUP_BODY)
        write(self.root, "b.py", DUP_BODY)
        write(self.root, "c.py", DUP_BODY)
        write_profile(self.root, {"modes": {"a.py": "exclude"}})
        payload = lint(self.root)
        hits = by_rule(payload, "L004")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"], "c.py")
        self.assertIn("exact duplicate of b.py", hits[0]["message"])


class TestL005Secrets(LintCase):
    def _secret_project(self):
        write(self.root, "keys.py", f'AWS_ACCESS_KEY_ID = "{AKIA}"\n')

    def test_secret_in_context_is_error(self):
        self._secret_project()
        payload = lint(self.root)
        hits = by_rule(payload, "L005")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["severity"], "error")
        self.assertEqual(lint_exit_code(payload), 1)
        self.assertEqual(lint_exit_code(payload, strict=True), 1)

    def test_secret_value_never_in_payload(self):
        self._secret_project()
        payload = lint(self.root)
        self.assertNotIn(AKIA, json.dumps(payload))
        code, out, _ = run_cli(["lint", str(self.root), "--json"])
        self.assertEqual(code, 1)
        self.assertNotIn(AKIA, out)

    def test_excluded_secret_file_is_silent(self):
        self._secret_project()
        write_profile(self.root, {"modes": {"keys.py": "exclude"}})
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L005"), [])
        self.assertEqual(lint_exit_code(payload), 0)


class TestL006GiantLine(LintCase):
    def test_minified_shape_fires(self):
        line = "var data = '" + "abcd" * 220 + "';"
        write(self.root, "min.js", "\n".join([line, line, line]) + "\n")
        payload = lint(self.root)
        hits = by_rule(payload, "L006")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"], "min.js")
        self.assertEqual(hits[0]["savings"], 0)  # detection only in v0.11

    def test_normal_lines_silent(self):
        write(self.root, "ok.js", "function go() {\n  return 1;\n}\n" * 10)
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L006"), [])


class TestL007Generated(LintCase):
    def test_header_marker_fires_at_full(self):
        write(self.root, "gen.txt",
              "// Code generated by protoc-gen. DO NOT EDIT.\n" + "payload line\n" * 30)
        payload = lint(self.root)
        hits = by_rule(payload, "L007")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"], "gen.txt")

    def test_marker_beyond_header_is_silent(self):
        body = "filler line\n" * 20 + "this file was generated by hand, do not edit\n"
        write(self.root, "late.txt", body)
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L007"), [])


class TestL008TestsAndL009Lockfile(LintCase):
    def test_test_file_at_full_fires(self):
        write(self.root, "test_stuff.py",
              "def test_one():\n    assert compute() == 1\n\n\ndef compute():\n    return 1\n")
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L008"), [])  # default strip-tests
        write_profile(self.root, {"modes": {"test_stuff.py": "full"}})
        payload = lint(self.root)
        self.assertEqual(len(by_rule(payload, "L008")), 1)

    def test_lockfile_included_fires(self):
        write(self.root, "package-lock.json",
              json.dumps({"name": "x", "lockfileVersion": 3,
                          "packages": {"": {"name": "x"}}}, indent=2))
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L009"), [])  # default exclude
        write_profile(self.root, {"modes": {"package-lock.json": "full"}})
        payload = lint(self.root)
        hits = by_rule(payload, "L009")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["savings"], hits[0]["tokens"])


class TestL010TinyNoise(LintCase):
    def test_many_tiny_files_fire_once_as_info(self):
        for i in range(25):
            write(self.root, f"tiny_{i}.txt", "hi")
        payload = lint(self.root)
        hits = by_rule(payload, "L010")
        self.assertEqual(len(hits), 1)
        self.assertIsNone(hits[0]["path"])
        self.assertEqual(hits[0]["severity"], "info")
        self.assertEqual(lint_exit_code(payload), 0)
        self.assertEqual(lint_exit_code(payload, strict=True), 0)

    def test_few_tiny_files_silent(self):
        for i in range(5):
            write(self.root, f"tiny_{i}.txt", "hi")
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L010"), [])


class TestProfileConfig(LintCase):
    def _warn_project(self):
        write(self.root, "notes.txt", "word " * 400)
        write_profile(self.root, {"lint": {"L001": {"threshold_tokens": 100}}})

    def test_rule_off(self):
        self._warn_project()
        write_profile(self.root, {"lint": {"L001": "off"}})
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L001"), [])

    def test_severity_override_changes_exit_code(self):
        self._warn_project()
        payload = lint(self.root)
        self.assertEqual(lint_exit_code(payload), 0)  # warn only
        self.assertEqual(lint_exit_code(payload, strict=True), 1)
        write_profile(self.root, {"lint": {"L001": {"severity": "error",
                                                    "threshold_tokens": 100}}})
        payload = lint(self.root)
        self.assertEqual(by_rule(payload, "L001")[0]["severity"], "error")
        self.assertEqual(lint_exit_code(payload), 1)

    def test_cli_strict_flag(self):
        self._warn_project()
        code, _, _ = run_cli(["lint", str(self.root)])
        self.assertEqual(code, 0)
        code, _, _ = run_cli(["lint", str(self.root), "--strict"])
        self.assertEqual(code, 1)

    def test_unknown_rule_id_is_loud(self):
        write_profile(self.root, {"lint": {"L099": "off"}})
        with self.assertRaises(ValueError):
            load_profile(self.root)
        code, _, err = run_cli(["lint", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("L099", err)

    def test_unknown_severity_is_loud(self):
        write_profile(self.root, {"lint": {"L001": "shout"}})
        with self.assertRaises(ValueError):
            load_profile(self.root)

    def test_typo_option_name_is_loud(self):
        write_profile(self.root, {"lint": {"L001": {"threshold_token": 5}}})
        with self.assertRaises(ValueError):
            load_profile(self.root)

    def test_nonpositive_option_is_loud(self):
        write_profile(self.root, {"lint": {"L001": {"threshold_tokens": 0}}})
        with self.assertRaises(ValueError):
            load_profile(self.root)

    def test_fraction_out_of_range_is_loud(self):
        write(self.root, "fat.py", fat_python())
        write_profile(self.root, {"lint": {"L002": {"min_savings_fraction": 1.5}}})
        with self.assertRaises(ValueError):
            lint(self.root)
        code, _, _ = run_cli(["lint", str(self.root)])
        self.assertEqual(code, 2)

    def test_missing_project_cli_exit_2(self):
        code, _, _ = run_cli(["lint", str(self.root / "nope")])
        self.assertEqual(code, 2)

    def test_bogus_profile_mode_cli_exit_2(self):
        # Audit G3: an unknown mode from the profile is the exporter's
        # own ValueError, surfaced by lint as a config error (2),
        # exactly as an export would fail.
        write(self.root, "x.py", "def f():\n    return 1\n")
        write_profile(self.root, {"modes": {"x.py": "bogus"}})
        code, _, err = run_cli(["lint", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("bogus", err)

    def test_every_rule_registered(self):
        self.assertEqual(sorted(RULES), [f"L{i:03d}" for i in range(1, 11)])


class TestNoDoubleCounting(LintCase):
    def test_overlapping_rules_count_file_once(self):
        write(self.root, "fat.py", fat_python())
        write_profile(self.root, {
            "modes": {"fat.py": "full"},
            "lint": {"L001": {"threshold_tokens": 100}},
        })
        payload = lint(self.root)
        rules_hit = {f["rule"] for f in payload["findings"] if f["path"] == "fat.py"}
        self.assertTrue({"L001", "L002"} <= rules_hit)
        entry = {f.path: f for f in scan(self.root).files}["fat.py"]
        # fat.py is the only file: flagged tokens count it exactly once
        # and savings never exceed the file's own tokens.
        self.assertEqual(payload["flagged_tokens"], entry.tokens)
        self.assertLessEqual(payload["potential_savings"], entry.tokens)


class TestSurfaces(LintCase):
    def setUp(self):
        super().setUp()
        write(self.root, "keys.py", f'AWS_ACCESS_KEY_ID = "{AKIA}"\n')
        write(self.root, "app.py", "def run():\n    return 1\n")

    def test_dashboard_api_lint_matches_engine(self):
        server, _ = make_server(str(self.root), port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/lint",
                                        timeout=10) as r:
                self.assertEqual(r.status, 200)
                data = json.loads(r.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
        payload = lint(self.root)
        self.assertEqual(data["counts"], payload["counts"])
        self.assertEqual([f["rule"] for f in data["findings"]],
                         [f["rule"] for f in payload["findings"]])

    def test_mcp_lint_project(self):
        resp = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertIn("lint_project", names)
        resp = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": "lint_project",
                                          "arguments": {"path": str(self.root)}}})
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(payload["counts"]["error"], 1)
        self.assertEqual(payload["exit_code"], 1)
        self.assertNotIn(AKIA, json.dumps(payload))

    def test_cli_json_matches_engine(self):
        code, out, _ = run_cli(["lint", str(self.root), "--json"])
        self.assertEqual(code, 1)
        data = json.loads(out)
        payload = lint(self.root)
        self.assertEqual(data["findings"], payload["findings"])
        self.assertEqual(data["counts"], payload["counts"])


if __name__ == "__main__":
    unittest.main()
