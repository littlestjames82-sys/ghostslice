"""v0.17 (G12): redact-in-place export.

The fixture carries one AWS key shared by two files (fingerprint
stability), a short password (fingerprint safety), a URL password, a
PEM block (block redaction), and secrets that survive slicing inside
a signature default and a docstring. The core promise under test:
with --redact on, the literal bytes appear in NO bundle artifact,
while the files themselves still ship.
"""
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice import secrets_scan
from ghostslice.cli import main as cli_main
from ghostslice.exporter import build_bundle, validate_bundle
from ghostslice.ledger import read_records
from ghostslice.mcp_server import handle_message
from ghostslice.profile import load_profile
from ghostslice.secrets_scan import (REDACTED_KINDS, RedactionError,
                                     fingerprint, redact_text,
                                     redaction_token, scan_text)
from ghostslice.tokens import estimate_tokens
from ghostslice.scanner import language_for
from ghostslice.watch import run_watch

# The literals are assembled from parts so this file's own SOURCE
# stays clean under `ghostslice secrets .` (the guard scans text,
# and a test file full of contiguous fake keys would flag itself);
# the runtime values are the real shapes.
AKIA = "AKIA" + "1234567890ABCDEF"
URL_PW = "sup3rsecretpw"
SHORT_PW = "abc12345"
PEM_CHUNK = "distinctivebody" + "chunk0123456789" + "abcdefXYZ="
AWS40 = "wJalrX" + "UtnFEMI/" + "K7MDENG/" + "bPxRfiCY" + "z9x8Qw3Er5"
LITERALS = (AKIA, URL_PW, SHORT_PW, PEM_CHUNK)
AKIA_TOKEN = re.compile(r"\[REDACTED:aws-access-key:[0-9a-f]{8}\]")

APP_PY = f'''API_KEY = "{AKIA}"
password = "{SHORT_PW}"


def connect(key="{AKIA}"):
    """Connect with the shared key {AKIA}."""
    return key
'''
SETTINGS_PY = (
    f'BACKUP_KEY = "{AKIA}"\n'
    f'DB = "postgres://admin:{URL_PW}@db.internal:5432/app"\n'
)
CERT_TXT = (
    "-----BEGIN " "PRIVATE KEY-----\n"
    "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC9w0BAQEFAA==\n"
    f"{PEM_CHUNK}\n"
    "-----END " "PRIVATE KEY-----\n"
)
NOTES = "plain notes, nothing sensitive\n"


def make_project(root: Path):
    (root / "app.py").write_text(APP_PY, encoding="utf-8")
    (root / "settings.py").write_text(SETTINGS_PY, encoding="utf-8")
    (root / "cert.txt").write_text(CERT_TXT, encoding="utf-8")
    (root / "notes.txt").write_text(NOTES, encoding="utf-8")


def bundle_bytes(bundle: Path) -> bytes:
    """Every byte of every artifact in the bundle, concatenated."""
    return b"".join(p.read_bytes() for p in sorted(bundle.rglob("*"))
                    if p.is_file())


class RedactExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.root.mkdir()
        make_project(self.root)
        self.out = Path(self.tmp.name) / "bundle"

    def tearDown(self):
        self.tmp.cleanup()

    def export(self, **kw):
        return build_bundle(self.root, self.out, **kw)

    # -- core promise -------------------------------------------------

    def test_same_literal_same_token_across_files(self):
        self.export(redact=True)
        app = (self.out / "files" / "app.py").read_text(encoding="utf-8")
        settings = (self.out / "files" / "settings.py").read_text(encoding="utf-8")
        tok_app = AKIA_TOKEN.search(app).group(0)
        tok_settings = AKIA_TOKEN.search(settings).group(0)
        self.assertEqual(tok_app, tok_settings)
        self.assertEqual(tok_app, redaction_token("aws-access-key", AKIA))
        self.assertNotIn(AKIA, app)
        self.assertNotIn(AKIA, settings)

    def test_literal_absent_from_every_artifact(self):
        for preset in ("json", "anthropic-xml"):
            out = Path(self.tmp.name) / f"bundle-{preset}"
            build_bundle(self.root, out, redact=True, preset=preset)
            blob = bundle_bytes(out)
            for literal in LITERALS:
                self.assertNotIn(literal.encode(), blob,
                                 f"{literal!r} leaked into {preset} bundle")
            # The token, by contrast, is everywhere the content is.
            files_app = (out / "files" / "app.py").read_text(encoding="utf-8")
            prompt = (out / "PROMPT.md").read_text(encoding="utf-8")
            wrapper = (out / ("context.json" if preset == "json"
                              else "context.xml")).read_text(encoding="utf-8")
            for text in (files_app, prompt, wrapper):
                self.assertRegex(text, AKIA_TOKEN)
            self.assertTrue(validate_bundle(out)["ok"], validate_bundle(out))

    def test_secrets_in_signature_default_and_docstring_redacted(self):
        # Default mode for Python is signatures: the default argument
        # and the docstring survive slicing, so redaction must catch
        # the key in both places (self-attack from the G12 brief).
        self.export(redact=True)
        app = (self.out / "files" / "app.py").read_text(encoding="utf-8")
        self.assertIn("def connect(", app)
        self.assertEqual(len(AKIA_TOKEN.findall(app)), 3)  # assign, default, docstring

    def test_private_key_block_fully_redacted(self):
        self.export(redact=True)
        cert = (self.out / "files" / "cert.txt").read_text(encoding="utf-8")
        lines = [l for l in cert.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^\[REDACTED:private-key:[0-9a-f]{8}\]$")
        self.assertNotIn(PEM_CHUNK, cert)
        self.assertNotIn("BEGIN PRIVATE KEY", cert)

    def test_redacted_output_rescans_clean_and_validates(self):
        manifest = self.export(redact=True)
        for entry in manifest["files"]:
            dest = self.out / "files" / entry["path"]
            if dest.is_file():
                self.assertEqual(
                    scan_text(entry["path"], dest.read_text(encoding="utf-8")), [],
                    f"{entry['path']} still trips the guard after redaction")
        check = validate_bundle(self.out)
        self.assertTrue(check["ok"], check)
        self.assertTrue(check["redaction_checked"])

    def test_placeholder_text_is_not_a_finding(self):
        text = f'API_KEY = "{redaction_token("aws-access-key", AKIA)}"\n'
        self.assertEqual(scan_text("x.py", text), [])
        text2 = f'DB = "postgres://u:{redaction_token("password-in-url", URL_PW)}@h/db"\n'
        self.assertEqual(scan_text("x.py", text2), [])

    # -- manifest / totals ---------------------------------------------

    def test_manifest_records_redactions(self):
        manifest = self.export(redact=True)
        by_path = {f["path"]: f for f in manifest["files"]}
        self.assertEqual(by_path["app.py"]["redactions"], 4)
        self.assertEqual(by_path["app.py"]["redaction_kinds"],
                         ["aws-access-key", "sensitive-assignment"])
        self.assertEqual(by_path["settings.py"]["redactions"], 3)
        self.assertEqual(by_path["cert.txt"]["redactions"], 1)
        self.assertNotIn("redactions", by_path["notes.txt"])
        block = manifest["redaction"]
        self.assertTrue(block["enabled"])
        self.assertEqual(block["values_redacted"], 8)
        self.assertEqual(block["files_affected"], 3)
        self.assertEqual(block["left_in_place"], 0)
        self.assertEqual(block["kinds"]["aws-access-key"], 4)

    def test_totals_are_post_redaction(self):
        plain = build_bundle(self.root, Path(self.tmp.name) / "plain")
        red = self.export(redact=True)
        self.assertEqual(plain["total_original_tokens"],
                         red["total_original_tokens"])
        # Manifest sliced tokens are recomputed from the shipped
        # (redacted) bytes: they match the validator exactly.
        self.assertEqual(red["total_sliced_tokens"],
                         sum(f["sliced_tokens"] for f in red["files"]))
        for entry in red["files"]:
            dest = self.out / "files" / entry["path"]
            if dest.is_file():
                self.assertEqual(
                    entry["sliced_tokens"],
                    estimate_tokens(dest.read_text(encoding="utf-8"),
                                    language_for(entry["path"])))
        self.assertNotEqual(plain["total_sliced_tokens"],
                            red["total_sliced_tokens"])

    def test_history_record_notes_redactions(self):
        self.export(redact=True)
        records = read_records(self.root)
        self.assertTrue(records)
        self.assertEqual(records[-1].get("redactions"), 8)

    # -- switches: default, profile, override, precedence --------------

    def test_default_off(self):
        manifest = self.export()
        self.assertNotIn("redaction", manifest)
        app = (self.out / "files" / "app.py").read_text(encoding="utf-8")
        self.assertIn(AKIA, app)
        self.assertFalse(validate_bundle(self.out)["redaction_checked"])

    def test_profile_redact_and_no_redact_override(self):
        (self.root / ".ghostslice.json").write_text(
            json.dumps({"redact": True}), encoding="utf-8")
        profile = load_profile(self.root)
        self.assertTrue(profile.redact)
        manifest = build_bundle(self.root, self.out, profile=profile)
        self.assertEqual(manifest["redaction"]["values_redacted"], 8)
        out2 = Path(self.tmp.name) / "bundle2"
        manifest2 = build_bundle(self.root, out2, profile=profile, redact=False)
        self.assertNotIn("redaction", manifest2)
        self.assertIn(AKIA, (out2 / "files" / "app.py").read_text(encoding="utf-8"))

    def test_profile_redact_must_be_bool(self):
        (self.root / ".ghostslice.json").write_text(
            json.dumps({"redact": "yes"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_profile(self.root)

    def test_exclude_secrets_wins_over_redact(self):
        manifest = self.export(exclude_secrets=True, redact=True)
        by_path = {f["path"]: f for f in manifest["files"]}
        for flagged in ("app.py", "settings.py", "cert.txt"):
            self.assertEqual(by_path[flagged]["mode"], "exclude")
            self.assertFalse((self.out / "files" / flagged).exists())
        # Excluded files are dropped whole; redaction had nothing to do.
        self.assertEqual(manifest["redaction"]["values_redacted"], 0)
        self.assertTrue(validate_bundle(self.out)["ok"])

    def test_cli_both_flags_prints_precedence_note(self):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            code = cli_main(["export", str(self.root), "-o", str(self.out),
                             "--exclude-secrets", "--redact"])
        self.assertEqual(code, 0)
        self.assertIn("exclusion wins", buf.getvalue())
        self.assertIn("Redacted 0 secret value(s)", buf.getvalue())

    def test_cli_redact_summary_line(self):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            code = cli_main(["export", str(self.root), "-o", str(self.out),
                             "--redact"])
        self.assertEqual(code, 0)
        self.assertIn("Redacted 8 secret value(s) across 3 file(s)",
                      buf.getvalue())

    def test_cli_no_redact_overrides_profile(self):
        (self.root / ".ghostslice.json").write_text(
            json.dumps({"redact": True}), encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = cli_main(["export", str(self.root), "-o", str(self.out),
                             "--no-redact"])
        self.assertEqual(code, 0)
        app = (self.out / "files" / "app.py").read_text(encoding="utf-8")
        self.assertIn(AKIA, app)

    # -- validator -------------------------------------------------------

    def test_validator_fails_on_planted_literal(self):
        manifest = self.export(redact=True)
        # Plant the literal back into one shipped file and fix up the
        # hash/token bookkeeping so ONLY the redaction check can fail.
        dest = self.out / "files" / "app.py"
        planted = dest.read_text(encoding="utf-8").replace(
            redaction_token("aws-access-key", AKIA), AKIA)
        dest.write_text(planted, encoding="utf-8")
        import hashlib
        man = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        old_total = man["total_sliced_tokens"]
        for entry in man["files"]:
            if entry["path"] == "app.py":
                entry["sha256"] = hashlib.sha256(
                    planted.encode("utf-8")).hexdigest()
                entry["sliced_tokens"] = estimate_tokens(
                    planted, language_for("app.py"))
        man["total_sliced_tokens"] = sum(
            f["sliced_tokens"] for f in man["files"])
        man["total_saved_tokens"] = man["total_original_tokens"] - man["total_sliced_tokens"]
        (self.out / "manifest.json").write_text(
            json.dumps(man, indent=2) + "\n", encoding="utf-8")
        self.assertNotEqual(old_total, man["total_sliced_tokens"])
        check = validate_bundle(self.out)
        self.assertFalse(check["ok"])
        self.assertTrue(any("redaction" in e for e in check["errors"]), check)

    def test_validator_ignores_unflagged_bundles_claim(self):
        # A bundle that never claimed redaction keeps literals legal
        # as far as the validator is concerned (pre-v0.17 semantics).
        self.export()
        check = validate_bundle(self.out)
        self.assertTrue(check["ok"], check)
        self.assertFalse(check["redaction_checked"])

    # -- inheritance: task / fit / watch / MCP ---------------------------

    def test_task_cli_redact(self):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            code = cli_main(["task", str(self.root), "--task", "connect key",
                             "-o", str(self.out), "--redact"])
        self.assertEqual(code, 0)
        self.assertNotIn(AKIA, bundle_bytes(self.out).decode("utf-8", "replace"))
        prompt = (self.out / "PROMPT.md").read_text(encoding="utf-8")
        self.assertRegex(prompt, AKIA_TOKEN)  # app.py selected AND redacted

    def test_fit_inherits_redact(self):
        manifest = self.export(redact=True, fit=100000)
        self.assertIn("fit", manifest)
        self.assertEqual(manifest["redaction"]["values_redacted"], 8)
        self.assertNotIn(AKIA.encode(), bundle_bytes(self.out))

    def test_watch_export_inherits_redact(self):
        summary = run_watch(self.root, out=self.out, export=True, once=True,
                            interval=0.01, debounce=0, redact=True)
        self.assertEqual(summary["exports"], 1)
        app = (self.out / "files" / "app.py").read_text(encoding="utf-8")
        self.assertNotIn(AKIA, app)
        self.assertRegex(app, AKIA_TOKEN)

    def test_mcp_export_redact(self):
        resp = handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "export_bundle",
                       "arguments": {"path": str(self.root),
                                     "out": str(self.out), "redact": True}}})
        self.assertNotIn("error", resp)
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(payload["redaction"]["values_redacted"], 8)
        self.assertNotIn(AKIA.encode(), bundle_bytes(self.out))

    # -- audit G12 F1: comment lines are content for a bundle ----------

    def test_comment_line_secret_redacted_guard_unchanged(self):
        (self.root / "legacy.py").write_text(
            f"# retired key, do not ship: {AKIA}\nVALUE = 1\n",
            encoding="utf-8")
        # The reporting guard still skips the comment (its documented
        # noise heuristic); the bundle must not ship the literal.
        self.assertEqual(scan_text("legacy.py", (self.root / "legacy.py")
                                   .read_text(encoding="utf-8")), [])
        manifest = build_bundle(self.root, self.out, redact=True,
                                default_mode="full")
        shipped = (self.out / "files" / "legacy.py").read_text(encoding="utf-8")
        self.assertNotIn(AKIA, shipped)
        self.assertRegex(shipped, AKIA_TOKEN)
        entry = {f["path"]: f for f in manifest["files"]}["legacy.py"]
        self.assertEqual(entry["redactions"], 1)
        self.assertTrue(validate_bundle(self.out)["ok"])

    def test_markdown_heading_secret_redacted(self):
        (self.root / "doc.md").write_text(
            f"# Release notes {AKIA}\n\nBody mentions {AKIA} too.\n",
            encoding="utf-8")
        build_bundle(self.root, self.out, redact=True,
                     selections={"doc.md": "headings"})
        shipped = (self.out / "files" / "doc.md").read_text(encoding="utf-8")
        self.assertNotIn(AKIA, shipped)
        self.assertTrue(validate_bundle(self.out)["ok"])

    def test_block_comment_body_redacted(self):
        (self.root / "notes2.txt").write_text(
            f"/*\n * embedded key: {AKIA}\n */\nplain\n", encoding="utf-8")
        build_bundle(self.root, self.out, redact=True)
        shipped = (self.out / "files" / "notes2.txt").read_text(encoding="utf-8")
        self.assertNotIn(AKIA, shipped)
        self.assertRegex(shipped, AKIA_TOKEN)

    def test_validator_catches_comment_line_plant(self):
        self.export(redact=True)
        import hashlib
        dest = self.out / "files" / "notes.txt"
        planted = dest.read_text(encoding="utf-8") + f"# key {AKIA}\n"
        dest.write_text(planted, encoding="utf-8")
        man = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        for entry in man["files"]:
            if entry["path"] == "notes.txt":
                entry["sha256"] = hashlib.sha256(
                    planted.encode("utf-8")).hexdigest()
                entry["sliced_tokens"] = estimate_tokens(
                    planted, language_for("notes.txt"))
        man["total_sliced_tokens"] = sum(
            f["sliced_tokens"] for f in man["files"])
        man["total_saved_tokens"] = (man["total_original_tokens"]
                                     - man["total_sliced_tokens"])
        (self.out / "manifest.json").write_text(
            json.dumps(man, indent=2) + "\n", encoding="utf-8")
        check = validate_bundle(self.out)
        self.assertFalse(check["ok"])
        self.assertTrue(any("redaction" in e for e in check["errors"]), check)

    # -- audit G12 F2: fit totals are pre-redaction, labelled -----------

    def test_fit_reports_redacted_after_tokens(self):
        manifest = self.export(redact=True, fit=100000)
        self.assertIn("redacted_after_tokens", manifest["fit"])
        self.assertEqual(manifest["fit"]["redacted_after_tokens"],
                         manifest["total_sliced_tokens"])
        self.assertNotEqual(manifest["fit"]["after_tokens"],
                            manifest["total_sliced_tokens"])

    def test_cli_fit_line_labels_redaction(self):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            code = cli_main(["export", str(self.root), "-o", str(self.out),
                             "--redact", "--fit", "100000"])
        self.assertEqual(code, 0)
        self.assertIn("after redaction:", buf.getvalue())

    # -- structure mode net ------------------------------------------------

    def test_config_full_and_structure_modes(self):
        (self.root / "config.yaml").write_text(
            f"service:\n  endpoint: https://example.com\n  api_key: {AKIA}\n",
            encoding="utf-8")
        manifest = self.export(redact=True)
        shipped = (self.out / "files" / "config.yaml").read_text(encoding="utf-8")
        self.assertNotIn(AKIA, shipped)
        self.assertTrue(validate_bundle(self.out)["ok"])
        # Structure mode placeholdering + the redaction net agree.
        (self.root / ".ghostslice.json").write_text(
            json.dumps({"modes": {"**/*.yaml": "structure"}}), encoding="utf-8")
        out2 = Path(self.tmp.name) / "bundle-struct"
        build_bundle(self.root, out2, redact=True,
                     profile=load_profile(self.root))
        shipped2 = (out2 / "files" / "config.yaml").read_text(encoding="utf-8")
        self.assertNotIn(AKIA, shipped2)
        self.assertTrue(validate_bundle(out2)["ok"])


class RedactTextUnitTests(unittest.TestCase):
    def test_fingerprint_rule(self):
        self.assertEqual(redaction_token("sensitive-assignment", SHORT_PW),
                         "[REDACTED:sensitive-assignment]")
        tok = redaction_token("aws-access-key", AKIA)
        self.assertEqual(tok, f"[REDACTED:aws-access-key:{fingerprint(AKIA)}]")
        self.assertEqual(len(fingerprint(AKIA)), 8)
        # Boundary: exactly MIN_FINGERPRINT_LEN gets a fingerprint.
        v = "x" * secrets_scan.MIN_FINGERPRINT_LEN
        tok = redaction_token("k", v)
        self.assertTrue(tok.startswith("[REDACTED:k:") and tok.endswith("]"))
        self.assertGreater(len(tok), len("[REDACTED:k:]"))

    def test_short_url_password_gets_no_fingerprint(self):
        out, applied, _ = redact_text(
            "x.py", 'DB = "postgres://u:abc' + '12@h/db"\n')
        by_type = {a["type"]: a["token"] for a in applied}
        self.assertEqual(by_type["password-in-url"],
                         "[REDACTED:password-in-url]")
        self.assertNotIn("abc12", out)

    def test_slice_relative_line_numbers(self):
        # The scan runs on the text as given: a secret on line 2 of a
        # slice is reported as line 2, whatever its source line was.
        _out, applied, _left = redact_text(
            "m.py", f'x = 1\nKEY = "{AKIA}"\n')
        self.assertEqual(applied[0]["line"], 2)

    def test_same_line_repeat_collapses(self):
        text = f'a = "{AKIA}"  # and again {AKIA}\n'
        out, applied, _ = redact_text("m.py", text)
        self.assertNotIn(AKIA, out)
        self.assertEqual(out.count(redaction_token("aws-access-key", AKIA)), 2)
        self.assertEqual(scan_text("m.py", out), [])

    def test_no_findings_returns_text_byte_identical(self):
        text = "nothing here\r\nsecond line\r\n"
        out, applied, leftovers = redact_text("m.py", text)
        self.assertEqual(out, text)
        self.assertEqual(applied, [])
        self.assertEqual(leftovers, [])

    def test_leftovers_reported_not_silently_shipped(self):
        kinds = REDACTED_KINDS - {"sensitive-assignment"}
        out, applied, leftovers = redact_text(
            "m.py", f'password = "{SHORT_PW}"\nKEY = "{AKIA}"\n', kinds=kinds)
        self.assertEqual(leftovers,
                         [{"line": 1, "type": "sensitive-assignment"}])
        self.assertIn(SHORT_PW, out)       # left in place, but reported
        self.assertNotIn(AKIA, out)
        self.assertEqual(len(applied), 1)

    def test_redact_kinds_cover_every_scanner_kind(self):
        # If the scanner ever grows a kind, this fails until the
        # redactor's set is updated — leftovers must be a decision,
        # not an accident.
        probe = "\n".join([
            "-----BEGIN " "PRIVATE KEY-----",
            AKIA,
            "ghp_" + "a1" * 16,
            "sk-ant-" + "a1" * 16,
            "xoxb-" + "1234567890ab",
            f'aws_secret = "{AWS40}"',
            f'DB = "postgres://u:{URL_PW}@h/db"',
            f'password = "{SHORT_PW}"',
            f'session = "{"Zx9Qw8Er7Ty6Ui5Op4As3Df2"}"',
            "-----END PRIVATE KEY-----",
        ]) + "\n"
        kinds_seen = {f["type"] for f in scan_text("probe.env", probe)}
        self.assertTrue(kinds_seen <= REDACTED_KINDS,
                        f"uncovered kinds: {kinds_seen - REDACTED_KINDS}")
        out, _applied, leftovers = redact_text("probe.env", probe)
        self.assertEqual(leftovers, [])
        self.assertEqual(scan_text("probe.env", out), [])

    def test_rescan_gate_raises_instead_of_shipping(self):
        # A scanner that keeps reporting a kind after replacement is
        # a redaction bug: redact_text must refuse, not return text.
        real = secrets_scan._scan_rich
        calls = {"n": 0}

        def stubborn(path, text, comments=False):
            calls["n"] += 1
            if calls["n"] == 1:
                return real(path, text)
            return [{"path": path, "line": 1, "type": "aws-access-key",
                     "redacted": "AKIA…", "value": AKIA,
                     "span": (0, len(AKIA)), "block": None}]

        with mock.patch.object(secrets_scan, "_scan_rich", stubborn):
            with self.assertRaises(RedactionError):
                redact_text("m.py", f'KEY = "{AKIA}"\n')


if __name__ == "__main__":
    unittest.main()
