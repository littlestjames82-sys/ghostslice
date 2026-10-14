"""v0.22 (G17) dashboard v2: /api/slice side-by-side preview,
/api/whatif panel totals, /api/export panel options.

Ground-truth rule for the what-if: its totals must equal a real
build_bundle manifest for the same options — the what-if is the
exporter's own machinery run in memory, not a second estimator.
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from ghostslice.exporter import build_bundle
from ghostslice.server import SLICE_PREVIEW_CAP, make_server
from ghostslice.slicer import slice_text

# Assembled from parts (the test_v17 pattern) so this file's own
# source does not trip `ghostslice secrets .` on the repo.
AKIA = "AKIA" + "1234567890ABCDEF"
XSS = "</script><script>alert(1)</" + "script>"

APP_PY = (
    f'API_KEY = "{AKIA}"\n\n\n'
    "def run(x: int) -> int:\n"
    "    secret = x * 3\n"
    "    return secret\n\n\n"
    "def helper() -> int:\n"
    "    return 7\n"
)
UTIL_PY = "def util_fn() -> int:\n    return 1\n"
EVIL_PY = f'PAYLOAD = "{XSS}"\n'
# One ~2,300-char line: detect.py flags it minified (line >= 300
# chars, >= 400 chars total, avg line >= 200).
MIN_JS = "var a=" + "1+".join(str(i) for i in range(400)) + ";\n"
BIG_PY = "# filler line\n" * 20000  # ~280k chars: over the preview cap
OUTSIDE_MARKER = "outside-the-project-marker"


def make_project(root: Path):
    (root / "app.py").write_text(APP_PY)
    (root / "util.py").write_text(UTIL_PY)
    (root / "evil.py").write_text(EVIL_PY)
    (root / "min.js").write_text(MIN_JS)
    (root / "big.py").write_text(BIG_PY)
    (root / "sub").mkdir()
    (root / "sub" / "inner.py").write_text(UTIL_PY)


class DashboardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "proj"
        self.root.mkdir()
        make_project(self.root)
        (self.base / "outside.txt").write_text(OUTSIDE_MARKER + "\n")
        self.server, self.state = make_server(str(self.root), port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02),
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}{path}",
                    timeout=30) as r:
                return r.status, r.headers, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read().decode("utf-8")

    def get_json(self, path):
        status, headers, body = self.get(path)
        return status, headers, json.loads(body)

    def post_json(self, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())


class SliceApiTests(DashboardCase):
    def test_slice_matches_ground_truth(self):
        status, headers, data = self.get_json(
            "/api/slice?path=app.py&mode=signatures")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "application/json")
        source = (self.root / "app.py").read_text()
        truth = slice_text("app.py", source, "signatures")
        self.assertEqual(data["original"], source)
        self.assertEqual(data["sliced"], truth.text)
        self.assertEqual(data["original_tokens"], truth.original_tokens)
        self.assertEqual(data["sliced_tokens"], truth.sliced_tokens)
        self.assertEqual(data["saved_tokens"], truth.saved_tokens)
        self.assertFalse(data["truncated"])

    def test_slice_mode_switch_changes_output(self):
        _, _, full = self.get_json("/api/slice?path=app.py&mode=full")
        _, _, sig = self.get_json("/api/slice?path=app.py&mode=signatures")
        _, _, exc = self.get_json("/api/slice?path=app.py&mode=exclude")
        source = (self.root / "app.py").read_text()
        self.assertEqual(full["sliced"], source)
        self.assertNotEqual(sig["sliced"], source)
        self.assertIn("def run", sig["sliced"])
        self.assertNotIn("secret = x * 3", sig["sliced"])
        self.assertEqual(exc["sliced"], "")
        self.assertEqual(exc["sliced_tokens"], 0)

    def test_slice_default_mode_is_files_default(self):
        _, _, data = self.get_json("/api/slice?path=app.py")
        self.assertEqual(data["mode"], "signatures")
        _, _, data = self.get_json("/api/slice?path=sub/inner.py&mode=full")
        self.assertEqual(data["sliced"], UTIL_PY)

    def test_slice_unknown_mode_and_missing_path(self):
        status, _, _ = self.get_json("/api/slice?path=app.py&mode=bogus")
        self.assertEqual(status, 400)
        status, _, _ = self.get_json("/api/slice?mode=full")
        self.assertEqual(status, 400)
        status, _, _ = self.get_json("/api/slice?path=nope.py&mode=full")
        self.assertEqual(status, 404)


class TraversalTests(DashboardCase):
    def setUp(self):
        super().setUp()
        # A scanned symlink whose target leaves the project, and one
        # that stays inside (resolve-based containment, not link fear).
        outside_py = self.base / "outside.py"
        outside_py.write_text("ESCAPED = '" + OUTSIDE_MARKER + "'\n")
        try:
            os.symlink(outside_py, self.root / "escape.py")
            os.symlink(self.root / "app.py", self.root / "alias.py")
        except OSError:
            self.skipTest("symlinks unavailable")
        # The server scanned before the links existed; rescan state
        # is a startup snapshot, so rebuild it to include them.
        self.server.shutdown()
        self.server.server_close()
        self.server, self.state = make_server(str(self.root), port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02),
                                       daemon=True)
        self.thread.start()

    def assert_blocked(self, path):
        status, _, body = self.get(path)
        self.assertIn(status, (400, 403, 404), f"{path} -> {status}")
        self.assertNotIn(OUTSIDE_MARKER, body)
        self.assertNotIn("ESCAPED", body)

    def test_traversal_variants_rejected(self):
        for p in ("/api/slice?path=../outside.txt&mode=full",
                  "/api/slice?path=%2e%2e%2foutside.txt&mode=full",
                  "/api/slice?path=%252e%252e%252foutside.txt&mode=full",
                  "/api/slice?path=/etc/passwd&mode=full",
                  "/api/slice?path=..%5coutside.txt&mode=full",
                  "/api/slice?path=sub/../../outside.txt&mode=full",
                  "/api/slice?path=sub/../app.py&mode=full",
                  "/api/preview?path=../outside.txt&mode=full"):
            self.assert_blocked(p)

    def test_symlink_out_of_root_rejected(self):
        # The scanner follows file symlinks, so escape.py IS in the
        # scan — the content endpoints must still refuse it.
        self.assertIn("escape.py", self.state.by_path)
        status, _, body = self.get("/api/slice?path=escape.py&mode=full")
        self.assertEqual(status, 403)
        self.assertNotIn(OUTSIDE_MARKER, body)

    def test_symlink_inside_root_served(self):
        status, _, data = self.get_json("/api/slice?path=alias.py&mode=full")
        self.assertEqual(status, 200)
        self.assertEqual(data["original"], APP_PY)


class TruncationTests(DashboardCase):
    def test_big_file_capped_but_tokens_full(self):
        status, _, data = self.get_json("/api/slice?path=big.py&mode=full")
        self.assertEqual(status, 200)
        source = (self.root / "big.py").read_text()
        truth = slice_text("big.py", source, "full")
        self.assertGreater(len(source), SLICE_PREVIEW_CAP)
        self.assertTrue(data["truncated"])
        self.assertEqual(set(data["truncated_sides"]),
                         {"original", "sliced"})
        self.assertLessEqual(len(data["original"]),
                             SLICE_PREVIEW_CAP + 200)
        self.assertIn("truncated", data["original"])
        # Token counts describe the full text, never the capped copy.
        self.assertEqual(data["original_tokens"], truth.original_tokens)
        self.assertEqual(data["sliced_tokens"], truth.sliced_tokens)

    def test_small_file_not_truncated(self):
        _, _, data = self.get_json("/api/slice?path=util.py&mode=full")
        self.assertFalse(data["truncated"])
        self.assertEqual(data["truncated_sides"], [])
        self.assertEqual(data["original"], UTIL_PY)


class ConcurrencyTests(DashboardCase):
    def test_concurrent_slice_requests_agree(self):
        results, errors = [], []

        def hit(i):
            try:
                status, _, data = self.get_json(
                    f"/api/slice?path=app.py&mode=signatures")
                results.append((status, data["sliced"]))
            except Exception as exc:  # collected, asserted below
                errors.append(exc)

        threads = [threading.Thread(target=hit, args=(i,))
                   for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 8)
        self.assertTrue(all(s == 200 for s, _ in results))
        self.assertEqual(len({text for _, text in results}), 1)


class WhatIfTests(DashboardCase):
    def ground_truth(self, options):
        """A real build_bundle with the same options, out of tree."""
        out = Path(tempfile.mkdtemp(dir=self.base)) / "bundle"
        manifest = build_bundle(
            self.root, out, profile=self.state.profile,
            selections=options.get("selections") or {},
            default_mode=options.get("mode"),
            fit=options.get("fit"),
            exclude_secrets=bool(options.get("exclude_secrets", False)),
            redact=options.get("redact"),
            auto_shrink=options.get("auto_shrink"),
            record_history=False, use_cache=False)
        return manifest["total_original_tokens"], \
            manifest["total_sliced_tokens"]

    def assert_whatif_matches(self, options):
        status, data = self.post_json("/api/whatif", options)
        self.assertEqual(status, 200, data)
        self.assertTrue(data["ok"], data)
        before, after = self.ground_truth(options)
        self.assertEqual(data["original_tokens"], before,
                         f"options={options}")
        self.assertEqual(data["sliced_tokens"], after,
                         f"options={options}")
        return data

    def test_whatif_defaults_equal_baseline(self):
        data = self.assert_whatif_matches({})
        self.assertEqual(data["delta_sliced_tokens"], 0)
        self.assertEqual(data["mode_changes"], 0)
        self.assertIsNone(data["fitted"])
        self.assertIsNone(data["fit"])

    def test_whatif_mode_override(self):
        data = self.assert_whatif_matches({"mode": "interfaces"})
        self.assertGreater(data["mode_changes"], 0)
        changed = {c["path"]: c for c in data["changed_files"]}
        self.assertEqual(changed["app.py"]["to"], "interfaces")

    def test_whatif_fit(self):
        base = self.assert_whatif_matches({})
        budget = max(1, base["baseline"]["sliced_tokens"] // 2)
        data = self.assert_whatif_matches({"fit": budget})
        self.assertIsNotNone(data["fit"])
        self.assertEqual(data["fit"]["fit_tokens"], budget)
        self.assertEqual(data["fitted"], data["fit"]["fitted"])
        self.assertLessEqual(data["sliced_tokens"],
                             base["baseline"]["sliced_tokens"])

    def test_whatif_exclude_secrets(self):
        data = self.assert_whatif_matches({"exclude_secrets": True})
        changed = {c["path"]: c for c in data["changed_files"]}
        self.assertEqual(changed["app.py"]["to"], "exclude")
        self.assertTrue(any("secret guard" in n for n in data["notes"]))

    def test_whatif_redact_full_mode(self):
        data = self.assert_whatif_matches({"mode": "full", "redact": True})
        self.assertTrue(any("post-redaction" in n for n in data["notes"]))

    def test_whatif_fit_plus_redact(self):
        base = self.assert_whatif_matches({})
        budget = max(1, base["baseline"]["sliced_tokens"] // 2)
        self.assert_whatif_matches(
            {"mode": "full", "fit": budget, "redact": True})

    def test_whatif_exclude_secrets_plus_redact(self):
        # Exclusion wins for flagged files; redaction covers the
        # rest — the CLI's documented precedence, on both sides.
        data = self.assert_whatif_matches(
            {"mode": "full", "exclude_secrets": True, "redact": True})
        changed = {c["path"]: c for c in data["changed_files"]}
        self.assertEqual(changed["app.py"]["to"], "exclude")

    def test_whatif_selections_protected_from_fit(self):
        base = self.assert_whatif_matches({})
        budget = max(1, base["baseline"]["sliced_tokens"] // 4)
        options = {"selections": {"app.py": "full"}, "fit": budget}
        self.assert_whatif_matches(options)
        # The protected selection is never downgraded, either side.
        out = Path(tempfile.mkdtemp(dir=self.base)) / "bundle"
        manifest = build_bundle(
            self.root, out, profile=self.state.profile,
            selections={"app.py": "full"}, fit=budget,
            record_history=False, use_cache=False)
        modes = {f["path"]: f["mode"] for f in manifest["files"]}
        self.assertEqual(modes["app.py"], "full")

    def test_whatif_mode_exclude(self):
        data = self.assert_whatif_matches({"mode": "exclude"})
        self.assertEqual(data["sliced_tokens"], 0)
        self.assertGreater(data["original_tokens"], 0)

    def test_whatif_auto_shrink_excludes_minified(self):
        data = self.assert_whatif_matches({"auto_shrink": True})
        changed = {c["path"]: c for c in data["changed_files"]}
        self.assertIn("min.js", changed)
        self.assertEqual(changed["min.js"]["to"], "exclude")

    def test_whatif_selections(self):
        data = self.assert_whatif_matches(
            {"selections": {"util.py": "exclude", "app.py": "full"}})
        changed = {c["path"]: c for c in data["changed_files"]}
        self.assertEqual(changed["util.py"]["to"], "exclude")
        self.assertEqual(changed["app.py"]["to"], "full")

    def test_whatif_bad_options(self):
        for payload in ({"mode": "bogus"}, {"fit": -5}, {"fit": "x"},
                        {"fit": True}, {"redact": "yes"},
                        {"selections": {"app.py": "bogus"}},
                        {"selections": ["app.py"]}):
            status, data = self.post_json("/api/whatif", payload)
            self.assertEqual(status, 400, f"{payload} -> {status} {data}")
            self.assertIn("error", data)

    def test_whatif_writes_nothing(self):
        def snapshot():
            snap = {}
            for p in sorted(self.root.rglob("*")):
                if p.is_file() and not p.is_symlink():
                    snap[str(p.relative_to(self.root))] = p.read_bytes()
            return snap

        before = snapshot()
        for payload in ({}, {"mode": "interfaces"}, {"fit": 50},
                        {"exclude_secrets": True},
                        {"mode": "full", "redact": True},
                        {"auto_shrink": True}):
            status, data = self.post_json("/api/whatif", payload)
            self.assertEqual(status, 200, data)
            self.assertTrue(data["ok"], data)
        self.assertEqual(snapshot(), before)
        self.assertFalse((self.root / ".ghostslice-cache").exists())
        self.assertFalse((self.root / ".claude_context").exists())
        self.assertFalse((self.root / ".ghostslice-history.jsonl").exists())


class ExportOptionsTests(DashboardCase):
    def manifest(self):
        return json.loads(
            (self.root / ".claude_context" / "manifest.json").read_text())

    def test_export_defaults_unchanged(self):
        status, data = self.post_json(
            "/api/export", {"selections": {"app.py": "signatures"}})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"], data)
        modes = {f["path"]: f["mode"] for f in self.manifest()["files"]}
        self.assertEqual(modes["app.py"], "signatures")

    def test_export_mode_override_honoured(self):
        status, data = self.post_json(
            "/api/export", {"selections": {}, "mode": "interfaces"})
        self.assertTrue(data["ok"], data)
        modes = {f["path"]: f["mode"] for f in self.manifest()["files"]}
        self.assertEqual(modes["app.py"], "interfaces")
        self.assertEqual(modes["util.py"], "interfaces")

    def test_export_redact_honoured(self):
        status, data = self.post_json(
            "/api/export", {"selections": {}, "mode": "full",
                            "redact": True})
        self.assertTrue(data["ok"], data)
        self.assertIn("redaction", data)
        shipped = (self.root / ".claude_context" / "files"
                   / "app.py").read_text()
        self.assertNotIn(AKIA, shipped)
        self.assertIn("[REDACTED:aws-access-key:", shipped)
        manifest = self.manifest()
        self.assertTrue(manifest["redaction"]["enabled"])
        self.assertGreaterEqual(manifest["redaction"]["values_redacted"], 1)

    def test_export_fit_honoured(self):
        base_status, base = self.post_json("/api/whatif", {})
        budget = max(1, base["baseline"]["sliced_tokens"] // 2)
        status, data = self.post_json(
            "/api/export", {"selections": {}, "fit": budget})
        self.assertTrue(data["ok"], data)
        self.assertIn("fit", data)
        self.assertEqual(data["fit"]["fit_tokens"], budget)
        self.assertEqual(self.manifest()["fit"]["fit_tokens"], budget)

    def test_export_bad_options(self):
        for payload in ({"mode": "bogus"}, {"fit": 0}, {"redact": 1}):
            status, data = self.post_json("/api/export", payload)
            self.assertEqual(status, 400, f"{payload} -> {status}")
            self.assertIn("error", data)

    def test_export_out_must_stay_inside_project(self):
        # Audit G17 F6: the bundle "always lands inside the served
        # project" is now enforced, not just intended.
        for out in ("../escaped", "../../escaped", "/tmp/escaped"):
            status, data = self.post_json(
                "/api/export", {"selections": {}, "out": out})
            self.assertEqual(status, 400, f"out={out} -> {status}")
            self.assertIn("error", data)
        self.assertFalse((self.root.parent / "escaped").exists())

    def test_export_out_nested_inside_project(self):
        status, data = self.post_json(
            "/api/export", {"selections": {}, "out": "bundles/one"})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"], data)
        self.assertTrue(
            (self.root / "bundles" / "one" / "manifest.json").is_file())


class PageTests(DashboardCase):
    def test_page_has_preview_and_whatif_markup(self):
        status, _, body = self.get("/")
        self.assertEqual(status, 200)
        for marker in ('id="origText"', 'id="sliceText"', 'id="sliceMode"',
                       'id="wiMode"', 'id="wiFitRange"', 'id="wiFitNum"',
                       'id="wiBtn"', 'id="wiResult"',
                       "/api/slice", "/api/whatif"):
            self.assertIn(marker, body)

    def test_xss_payload_travels_inert(self):
        status, _, body = self.get("/")
        self.assertEqual(status, 200)
        # The payload lives only in the file; the page must not carry
        # it, and file content must be assigned via textContent.
        self.assertNotIn(XSS, body)
        self.assertIn("$('origText').textContent = d.original", body)
        self.assertIn("$('sliceText').textContent = d.sliced", body)
        self.assertNotIn("innerHTML = d.original", body)
        self.assertNotIn("innerHTML = d.sliced", body)
        # The JSON payload round-trips the string verbatim (inert
        # data; the browser only ever textContent's it).
        status, _, data = self.get_json("/api/slice?path=evil.py&mode=full")
        self.assertEqual(status, 200)
        self.assertEqual(data["original"], EVIL_PY)
        self.assertIn(XSS, data["original"])


class ProfileWhatIfTests(unittest.TestCase):
    """F3: the what-if ground truth on a project WITH a profile —
    profile modes and entry points are fit-protected inside the
    shared machinery, and that protection must hold identically
    in the in-memory what-if and a real export."""

    MAIN_PY = ("def main() -> int:\n    return run(2)\n\n\n"
               "def run(x: int) -> int:\n    return x * 3\n")
    UTIL_PY = "def util_fn() -> int:\n    return 1\n\n\n" * 6

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "proj"
        self.root.mkdir()
        (self.root / "main.py").write_text(self.MAIN_PY)
        (self.root / "util.py").write_text(self.UTIL_PY)
        (self.root / ".ghostslice.json").write_text(json.dumps({
            "modes": {"util.py": "full"},
            "entry_points": ["main.py"],
        }))
        self.server, self.state = make_server(str(self.root), port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02),
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def post_whatif(self, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/whatif",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())

    def ground_truth(self, options):
        out = Path(tempfile.mkdtemp(dir=self.base)) / "bundle"
        return build_bundle(
            self.root, out, profile=self.state.profile,
            selections=options.get("selections") or {},
            default_mode=options.get("mode"),
            fit=options.get("fit"),
            exclude_secrets=bool(options.get("exclude_secrets", False)),
            redact=options.get("redact"),
            auto_shrink=options.get("auto_shrink"),
            record_history=False, use_cache=False)

    def test_profile_defaults_match(self):
        data = self.post_whatif({})
        manifest = self.ground_truth({})
        self.assertEqual(data["original_tokens"],
                         manifest["total_original_tokens"])
        self.assertEqual(data["sliced_tokens"],
                         manifest["total_sliced_tokens"])
        self.assertEqual(data["mode_changes"], 0)

    def test_profile_fit_protection_matches(self):
        base = self.post_whatif({})
        budget = max(1, base["baseline"]["sliced_tokens"] // 4)
        data = self.post_whatif({"fit": budget})
        manifest = self.ground_truth({"fit": budget})
        self.assertEqual(data["sliced_tokens"],
                         manifest["total_sliced_tokens"])
        modes = {f["path"]: f["mode"] for f in manifest["files"]}
        # Profile-moded files are never downgraded by the ladder,
        # and entry points are never excluded by it.
        self.assertEqual(modes["util.py"], "full")
        self.assertNotEqual(modes["main.py"], "exclude")


class ProfileDefaultsWhatIfTests(unittest.TestCase):
    """Audit #2 probe, pinned: when the PROFILE itself turns
    redact / auto_shrink on, the what-if defaults (panel silent)
    and explicit panel overrides both match build_bundle."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "proj"
        self.root.mkdir()
        (self.root / "app.py").write_text(
            f'KEY = "{AKIA}"\n\ndef run() -> int:\n    return 1\n')
        (self.root / "min.js").write_text(MIN_JS)
        (self.root / ".ghostslice.json").write_text(json.dumps(
            {"redact": True, "auto_shrink": True}))
        self.server, self.state = make_server(str(self.root), port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02),
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def check(self, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/whatif",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        out = Path(tempfile.mkdtemp(dir=self.base)) / "bundle"
        manifest = build_bundle(
            self.root, out, profile=self.state.profile,
            default_mode=payload.get("mode"),
            redact=payload.get("redact"),
            auto_shrink=payload.get("auto_shrink"),
            record_history=False, use_cache=False)
        self.assertEqual(data["original_tokens"],
                         manifest["total_original_tokens"], payload)
        self.assertEqual(data["sliced_tokens"],
                         manifest["total_sliced_tokens"], payload)

    def test_profile_defaults_and_overrides_match(self):
        for payload in ({}, {"mode": "full"},
                        {"mode": "full", "redact": False},
                        {"auto_shrink": False}):
            self.check(payload)


class EmptyProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.server, self.state = make_server(str(self.root), port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02),
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def test_whatif_empty_project(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/whatif",
            data=b"{}", headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        self.assertTrue(data["ok"])
        self.assertEqual(data["original_tokens"], 0)
        self.assertEqual(data["sliced_tokens"], 0)
        self.assertEqual(data["saved_pct"], 0.0)
        self.assertIsNone(data["fitted"])
        self.assertEqual(data["mode_changes"], 0)

    def test_slice_empty_project_404(self):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}"
                    "/api/slice?path=x.py&mode=full", timeout=30) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
