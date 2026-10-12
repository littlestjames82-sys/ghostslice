import tempfile
import unittest
from pathlib import Path

from ghostslice.scanner import is_lockfile, is_test_file, scan


def make_tree(root: Path):
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def main():\n    return 1\n" * 10)
    (root / "src" / "util.ts").write_text("export function util() { return 2; }\n")
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("module.exports = {};\n")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n")
    (root / "ignored.py").write_text("SECRET = 1\n")
    (root / ".gitignore").write_text("ignored.py\nbuild/\n")
    (root / "build").mkdir()
    (root / "build" / "out.py").write_text("x = 1\n")
    (root / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("def test_main():\n    assert True\n")
    (root / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    (root / "img.png").write_bytes(b"\x89PNG\r\n\x00")
    (root / "README.md").write_text("# hi\n")


class TestScanner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_tree(self.root)
        self.result = scan(self.root)
        self.paths = {f.path for f in self.result.files}

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_code_files(self):
        self.assertIn("src/app.py", self.paths)
        self.assertIn("src/util.ts", self.paths)
        self.assertIn("README.md", self.paths)

    def test_default_ignores(self):
        self.assertNotIn("node_modules/pkg/index.js", self.paths)
        self.assertFalse(any(p == ".git" or p.startswith(".git/") for p in self.paths))
        self.assertNotIn(".git/config", self.paths)
        self.assertNotIn("build/out.py", self.paths)
        self.assertNotIn("img.png", self.paths)
        self.assertNotIn("blob.bin", self.paths)

    def test_gitignore_respected(self):
        self.assertNotIn("ignored.py", self.paths)

    def test_lockfile_flagged(self):
        entry = next(f for f in self.result.files if f.path == "package-lock.json")
        self.assertTrue(entry.is_lockfile)
        self.assertTrue(is_lockfile("yarn.lock"))
        self.assertFalse(is_lockfile("app.py"))

    def test_test_file_flagged(self):
        entry = next(f for f in self.result.files if f.path == "tests/test_app.py")
        self.assertTrue(entry.is_test)
        self.assertTrue(is_test_file("src/foo.test.ts"))
        self.assertTrue(is_test_file("src/foo.spec.js"))
        self.assertFalse(is_test_file("src/app.py"))

    def test_tokens_and_totals(self):
        self.assertGreater(self.result.total_tokens, 0)
        app = next(f for f in self.result.files if f.path == "src/app.py")
        self.assertGreater(app.tokens, 10)
        # sorted by tokens, descending
        tokens = [f.tokens for f in self.result.files]
        self.assertEqual(tokens, sorted(tokens, reverse=True))


if __name__ == "__main__":
    unittest.main()
