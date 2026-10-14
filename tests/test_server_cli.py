import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from ghostslice.cli import main
from ghostslice.server import make_server


def make_project(root: Path):
    (root / "app.py").write_text("def run(x: int) -> int:\n    secret = x * 3\n    return secret\n")
    (root / "api.ts").write_text("export function go(): void {\n  const hidden = 1;\n}\n")


class TestServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_project(self.root)
        self.server, _ = make_server(str(self.root), port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
            return r.status, r.read().decode("utf-8")

    def test_homepage(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("GhostSlice", body)
        self.assertIn("6716f3", body)

    def test_scan_api(self):
        status, body = self.get("/api/scan")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["file_count"], 2)
        f = next(x for x in data["files"] if x["path"] == "app.py")
        self.assertEqual(f["mode"], "signatures")
        self.assertIn("mode_tokens", f)
        self.assertLess(f["mode_tokens"]["signatures"], f["tokens"])

    def test_prices_api(self):
        status, body = self.get("/api/prices")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("as_of", data)
        self.assertTrue(data["models"])

    def test_preview_api(self):
        status, body = self.get("/api/preview?path=app.py&mode=signatures")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("def run", data["text"])
        self.assertNotIn("secret", data["text"])
        self.assertLess(data["sliced_tokens"], data["original_tokens"])

    def test_export_api(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/export",
            data=json.dumps({"selections": {"app.py": "signatures"}}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        self.assertTrue(data["ok"], data)
        self.assertTrue((self.root / ".claude_context" / "manifest.json").is_file())


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.root.mkdir(parents=True)
        make_project(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_cli(self):
        self.assertEqual(main(["scan", str(self.root)]), 0)

    def test_scan_json_cli(self):
        self.assertEqual(main(["scan", str(self.root), "--json"]), 0)

    def test_slice_and_export_cli(self):
        out = Path(self.tmp.name) / "sliced"
        self.assertEqual(main(["slice", str(self.root), "--mode", "signatures", "-o", str(out)]), 0)
        self.assertTrue((out / "app.py").is_file())
        bundle = Path(self.tmp.name) / "bundle"
        self.assertEqual(main(["export", str(self.root), "-o", str(bundle)]), 0)
        self.assertTrue((bundle / "manifest.json").is_file())
        self.assertEqual(main(["check", str(bundle)]), 0)

    def test_prices_cli(self):
        self.assertEqual(main(["prices"]), 0)


if __name__ == "__main__":
    unittest.main()
