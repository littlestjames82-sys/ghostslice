"""v0.16 (G11): anthropic-xml + json bundle presets.

The fixture code deliberately contains the characters that break
naive XML building: `]]>`, `<tag>`, `&amp;`, bare `&` / `<` / `>`,
and a DEL control character (legal in XML 1.0). Round-trip tests
compare artifact content against the bundle's own files/ bytes —
the canonical slices — never against re-sliced output.
"""
import io
import json
import sys
import tempfile
import unittest
import xml.dom.minidom
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.cli import main as cli_main
from ghostslice.exporter import (_xml_safe_text, build_bundle,
                                 validate_bundle)
from ghostslice.mcp_server import handle_message
from ghostslice.profile import PRESETS, load_profile

NASTY = (
    "MARKER = ']]>'\n"
    "TAG = '<tag attr=\"a&b\">'\n"
    "AMP = '&amp; & <> '\n"
    "DEL = 'bad\x7fchar'\n"
    "def keep():\n    return MARKER\n"
)


def make_project(root: Path):
    (root / "nasty.py").write_text(NASTY, encoding="utf-8")
    (root / "main.py").write_text(
        "def main():\n    x = compute()\n    return x\n\n\ndef compute():\n    return 42\n",
        encoding="utf-8")
    (root / "test_main.py").write_text(
        "def test_main():\n    assert True\n", encoding="utf-8")
    (root / "package-lock.json").write_text('{"lockfileVersion": 3}\n',
                                            encoding="utf-8")
    (root / "notes.txt").write_text("plain notes & <stuff>\n", encoding="utf-8")


def included_paths(manifest, bundle: Path):
    return [f["path"] for f in manifest["files"]
            if (bundle / "files" / f["path"]).is_file()]


def xml_documents(bundle: Path):
    """Parse context.xml with minidom; return ({source: content},
    [sources in order], {excluded path: (mode, reason)})."""
    dom = xml.dom.minidom.parse(str(bundle / "context.xml"))
    contents, order = {}, []
    for doc in dom.getElementsByTagName("document"):
        source = doc.getElementsByTagName("source")[0].firstChild.data
        node = doc.getElementsByTagName("document_content")[0].firstChild
        contents[source] = node.data if node is not None else ""
        order.append(source)
    excluded = {}
    for f in dom.getElementsByTagName("file"):
        excluded[f.getAttribute("path")] = (f.getAttribute("mode"),
                                            f.getAttribute("reason"))
    return contents, order, excluded


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.root.mkdir(parents=True)
        make_project(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, preset, name="bundle", **kw):
        out = Path(self.tmp.name) / name
        kw.setdefault("record_history", False)
        kw.setdefault("selections", {"nasty.py": "full"})
        manifest = build_bundle(self.root, out, preset=preset, **kw)
        return manifest, out


class TestXmlPreset(Fixture):
    def test_well_formed_and_round_trip(self):
        manifest, out = self.build("anthropic-xml")
        self.assertTrue((out / "context.xml").is_file())
        contents, order, _ = xml_documents(out)  # minidom parse = well-formed
        inc = included_paths(manifest, out)
        self.assertEqual(order, inc)  # manifest order, deterministic
        for path in inc:
            disk = (out / "files" / path).read_text(encoding="utf-8")
            self.assertEqual(contents[path], disk, path)
        # The nasty payload survived escaping intact.
        self.assertIn("]]>", contents["nasty.py"])
        self.assertIn("<tag attr=\"a&b\">", contents["nasty.py"])
        self.assertIn("&amp; & <>", contents["nasty.py"])
        self.assertIn("\x7f", contents["nasty.py"])

    def test_document_attributes_match_manifest(self):
        manifest, out = self.build("anthropic-xml")
        dom = xml.dom.minidom.parse(str(out / "context.xml"))
        by_path = {f["path"]: f for f in manifest["files"]}
        docs = dom.getElementsByTagName("document")
        self.assertEqual([d.getAttribute("index") for d in docs],
                         [str(i) for i in range(1, len(docs) + 1)])
        for doc in docs:
            source = doc.getElementsByTagName("source")[0].firstChild.data
            entry = by_path[source]
            self.assertEqual(doc.getAttribute("mode"), entry["mode"])
            self.assertEqual(doc.getAttribute("sha256"), entry["sha256"])
            self.assertEqual(int(doc.getAttribute("sliced_tokens")),
                             entry["sliced_tokens"])

    def test_excluded_section(self):
        manifest, out = self.build("anthropic-xml")
        _, _, excluded = xml_documents(out)
        self.assertEqual(excluded["package-lock.json"][0], "exclude")
        # The test file strips to an empty slice: listed, with reason.
        self.assertIn("test_main.py", excluded)
        self.assertIn("empty slice", excluded["test_main.py"][1])
        # Every manifest file is either a document or excluded.
        contents, _, _ = xml_documents(out)
        self.assertEqual(set(contents) | set(excluded),
                         {f["path"] for f in manifest["files"]})
        self.assertFalse(set(contents) & set(excluded))

    def test_no_cdata_anywhere(self):
        _, out = self.build("anthropic-xml")
        self.assertNotIn("<![CDATA[", (out / "context.xml").read_text(encoding="utf-8"))

    def test_wrapper_overhead_in_manifest(self):
        manifest, out = self.build("anthropic-xml")
        info = manifest["wrapper_artifacts"]["context.xml"]
        raw = (out / "context.xml").read_bytes()
        self.assertEqual(info["bytes"], len(raw))
        self.assertGreater(info["estimated_tokens"], 0)
        # The artifact CONTAINS the slices: overhead is only the
        # markup beyond them, never the whole artifact size.
        self.assertEqual(
            info["overhead_estimated_tokens"],
            max(0, info["estimated_tokens"] - manifest["total_sliced_tokens"]))
        self.assertLess(info["overhead_estimated_tokens"],
                        info["estimated_tokens"])
        # Totals semantics unchanged: wrapper cost is NOT folded in.
        self.assertEqual(manifest["total_sliced_tokens"],
                         sum(f["sliced_tokens"] for f in manifest["files"]))

    def test_illegal_xml_chars_replaced_not_fatal(self):
        (self.root / "ctrl.txt").write_bytes(b"bell\x01 and \x0bvertical\n")
        manifest, out = self.build("anthropic-xml", "ctrl-bundle")
        contents, _, _ = xml_documents(out)  # still parses
        self.assertIn("\uFFFD", contents["ctrl.txt"])
        self.assertNotIn("\x01", contents["ctrl.txt"])
        # Canonical bytes stay in files/ and validation still passes.
        self.assertIn("\x01", (out / "files" / "ctrl.txt").read_bytes().decode(
            encoding="utf-8", errors="replace"))
        self.assertTrue(validate_bundle(out)["ok"], validate_bundle(out))

    def test_validate_ok_and_artifacts_listed(self):
        _, out = self.build("anthropic-xml")
        check = validate_bundle(out)
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["artifacts_checked"], ["context.xml"])

    def test_validate_fails_on_truncated_xml(self):
        _, out = self.build("anthropic-xml")
        raw = (out / "context.xml").read_text(encoding="utf-8")
        (out / "context.xml").write_text(raw[: len(raw) // 2], encoding="utf-8")
        check = validate_bundle(out)
        self.assertFalse(check["ok"])
        self.assertTrue(any("context.xml" in e and "well-formed" in e
                            for e in check["errors"]), check["errors"])

    def test_validate_fails_on_tampered_xml_content(self):
        _, out = self.build("anthropic-xml")
        raw = (out / "context.xml").read_text(encoding="utf-8")
        (out / "context.xml").write_text(raw.replace("compute", "computeX", 1),
                                         encoding="utf-8")
        check = validate_bundle(out)
        self.assertFalse(check["ok"])
        self.assertTrue(any("context.xml" in e and "content mismatch" in e
                            for e in check["errors"]), check["errors"])


class TestJsonPreset(Fixture):
    def test_schema_and_round_trip(self):
        manifest, out = self.build("json", model="claude-sonnet")
        payload = json.loads((out / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["project"], "proj")
        self.assertEqual(payload["model"], "claude-sonnet")
        self.assertIn("ghostslice", payload["generated_by"])
        self.assertEqual(payload["version"], manifest["version"])
        self.assertEqual(payload["totals"], {
            "original_tokens": manifest["total_original_tokens"],
            "sliced_tokens": manifest["total_sliced_tokens"],
            "saved_tokens": manifest["total_saved_tokens"],
        })
        inc = included_paths(manifest, out)
        self.assertEqual([f["path"] for f in payload["files"]], inc)
        by_path = {f["path"]: f for f in manifest["files"]}
        for rec in payload["files"]:
            disk = (out / "files" / rec["path"]).read_text(encoding="utf-8")
            self.assertEqual(rec["content"], disk, rec["path"])
            self.assertEqual(rec["sha256"], by_path[rec["path"]]["sha256"])
            self.assertEqual(rec["mode"], by_path[rec["path"]]["mode"])
            self.assertIn("package", rec)
        excluded = {e["path"] for e in payload["excluded"]}
        self.assertEqual(excluded | set(inc),
                         {f["path"] for f in manifest["files"]})

    def test_invalid_utf8_source_file(self):
        # Invalid UTF-8 bytes in a source file must not explode the
        # JSON writer: read errors="replace" turns them into U+FFFD
        # long before json.dumps sees the text.
        (self.root / "bad.txt").write_bytes(b"caf\xe9 \xff\xfe bytes\n")
        manifest, out = self.build("json", "bad-bundle")
        payload = json.loads((out / "context.json").read_text(encoding="utf-8"))
        rec = {f["path"]: f for f in payload["files"]}["bad.txt"]
        disk = (out / "files" / "bad.txt").read_text(encoding="utf-8")
        self.assertEqual(rec["content"], disk)
        self.assertIn("\uFFFD", rec["content"])
        self.assertTrue(validate_bundle(out)["ok"], validate_bundle(out))

    def test_validate_ok(self):
        _, out = self.build("json")
        check = validate_bundle(out)
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["artifacts_checked"], ["context.json"])

    def test_validate_fails_on_tampered_totals(self):
        _, out = self.build("json")
        payload = json.loads((out / "context.json").read_text(encoding="utf-8"))
        payload["totals"]["sliced_tokens"] += 1
        (out / "context.json").write_text(json.dumps(payload), encoding="utf-8")
        check = validate_bundle(out)
        self.assertFalse(check["ok"])
        self.assertTrue(any("context.json" in e and "totals" in e
                            for e in check["errors"]), check["errors"])

    def test_validate_fails_on_tampered_content(self):
        _, out = self.build("json")
        payload = json.loads((out / "context.json").read_text(encoding="utf-8"))
        payload["files"][0]["content"] += "tampered"
        (out / "context.json").write_text(json.dumps(payload), encoding="utf-8")
        check = validate_bundle(out)
        self.assertFalse(check["ok"])
        self.assertTrue(any("context.json" in e and "content mismatch" in e
                            for e in check["errors"]), check["errors"])

    def test_validate_fails_on_invalid_json(self):
        _, out = self.build("json")
        (out / "context.json").write_text("{not json", encoding="utf-8")
        check = validate_bundle(out)
        self.assertFalse(check["ok"])
        self.assertTrue(any("context.json" in e for e in check["errors"]))

    def _tamper_json(self, out, mutate):
        payload = json.loads((out / "context.json").read_text(encoding="utf-8"))
        mutate(payload)
        (out / "context.json").write_text(json.dumps(payload), encoding="utf-8")
        return validate_bundle(out)  # must report, never raise

    def test_validate_never_crashes_on_nonobject_file_entry(self):
        _, out = self.build("json")
        check = self._tamper_json(out, lambda p: p.update(files=[42]))
        self.assertFalse(check["ok"])
        self.assertTrue(any("context.json" in e for e in check["errors"]),
                        check["errors"])

    def test_validate_never_crashes_on_nonobject_excluded_entry(self):
        _, out = self.build("json")
        check = self._tamper_json(out, lambda p: p.update(excluded=["oops"]))
        self.assertFalse(check["ok"])
        self.assertTrue(any("context.json" in e for e in check["errors"]),
                        check["errors"])

    def test_validate_never_crashes_on_files_as_object(self):
        _, out = self.build("json")
        check = self._tamper_json(out, lambda p: p.update(files={"a.py": 1}))
        self.assertFalse(check["ok"])
        self.assertTrue(any("context.json" in e and "list" in e
                            for e in check["errors"]), check["errors"])


class TestCompositionAndSurfaces(Fixture):
    def test_old_bundle_shape_unchanged(self):
        # Bundles without the new artifacts validate exactly as
        # before and report no artifacts checked.
        out = Path(self.tmp.name) / "plain"
        build_bundle(self.root, out, record_history=False,
                     selections={"nasty.py": "full"})
        check = validate_bundle(out)
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["artifacts_checked"], [])
        self.assertNotIn("wrapper_artifacts",
                         json.loads((out / "manifest.json").read_text()))

    def test_fit_composes_with_json_preset(self):
        manifest, out = self.build("json", "fit-bundle", fit=10)
        self.assertIn("fit", manifest)
        self.assertTrue((out / "context.json").is_file())
        self.assertTrue(validate_bundle(out)["ok"], validate_bundle(out))

    def test_cli_export_xml_prints_wrapper_line(self):
        out = Path(self.tmp.name) / "cli-xml"
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            code = cli_main(["export", str(self.root), "-o", str(out),
                             "--preset", "anthropic-xml"])
        self.assertEqual(code, 0)
        self.assertIn("Wrapper: context.xml is ~", buf.getvalue())
        self.assertIn("format overhead beyond", buf.getvalue())
        self.assertTrue((out / "context.xml").is_file())

    def test_cli_task_with_xml_preset(self):
        out = Path(self.tmp.name) / "task-xml"
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            code = cli_main(["task", str(self.root), "--task", "compute main",
                             "-o", str(out), "--preset", "anthropic-xml"])
        self.assertEqual(code, 0)
        self.assertTrue((out / "context.xml").is_file())
        self.assertIn("context.xml", buf.getvalue())
        self.assertTrue(validate_bundle(out)["ok"], validate_bundle(out))

    def test_mcp_enum_and_export(self):
        resp = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        enum = tools["export_bundle"]["inputSchema"]["properties"]["preset"]["enum"]
        self.assertIn("anthropic-xml", enum)
        self.assertIn("json", enum)
        out = Path(self.tmp.name) / "mcp-json"
        resp = handle_message({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "export_bundle",
                       "arguments": {"path": str(self.root), "out": str(out),
                                     "preset": "json"}}})
        self.assertNotIn("error", resp)
        self.assertTrue((out / "context.json").is_file())

    def test_preset_consistency(self):
        # PRESETS, the profile loader, the CLI choices, and the
        # README list must all name the same preset set.
        for preset in PRESETS:
            (self.root / ".ghostslice.json").write_text(
                json.dumps({"preset": preset}))
            self.assertEqual(load_profile(self.root).preset, preset)
        (self.root / ".ghostslice.json").unlink()
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                cli_main(["export", "--help"])
        help_text = buf.getvalue()
        for preset in PRESETS:
            self.assertIn(preset, help_text)
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
            encoding="utf-8")
        for preset in PRESETS:
            self.assertIn(f"`{preset}`", readme)


class TestXmlSafeText(unittest.TestCase):
    def test_legal_chars_pass_through(self):
        text = "a\tb\nc\rd\x7fe\u0080f\U0001F600g"
        self.assertEqual(_xml_safe_text(text), text)

    def test_illegal_chars_replaced(self):
        self.assertEqual(_xml_safe_text("a\x00b\x0bc\x1fd"),
                         "a\uFFFDb\uFFFDc\uFFFDd")
        self.assertEqual(_xml_safe_text("\uFFFE\uFFFF"), "\uFFFD\uFFFD")
        self.assertEqual(_xml_safe_text("x\ud800y"), "x\uFFFDy")


if __name__ == "__main__":
    unittest.main()
