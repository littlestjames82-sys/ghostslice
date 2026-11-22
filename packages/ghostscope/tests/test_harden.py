"""Hardening regression tests (improve-2026-10-18, lane: harden).

Each class pins one real bug found by audit:

  - diff lines that look like --- / +++ headers *inside* a hunk were
    parsed as file headers, corrupting paths and dropping the lines.
  - header-less unified diffs (`diff -u` output) parsed to nothing.
  - diff-supplied paths with `..` / absolute components were followed
    into filesystem reads and pack validation unchecked.
  - `git show` on a binary / non-UTF-8 blob crashed with
    UnicodeDecodeError.
  - pack validation let missing files pass, crashed on malformed
    manifests, and skipped the sha check for empty content.
  - the CLI let OSError (e.g. an unwritable pack path) escape as a
    traceback instead of exit code 2.
  - the MCP server crashed on a non-object JSON message and stayed
    silent on unparseable input.
  - the scanner read every file twice; the second read was
    unguarded and could disagree with the recorded size.
"""
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostscope.diffparse import parse_diff  # noqa: E402
from ghostscope.gitinput import ChangeInput, git_show  # noqa: E402
from ghostscope.validate import validate_pack  # noqa: E402
from tests.helpers import git  # noqa: E402

EMPTY_SHA = hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# diffparse
# ---------------------------------------------------------------------------

class TestHeaderLikeLinesInsideHunks(unittest.TestCase):
    DIFF = (
        "diff --git a/mod.py b/mod.py\n"
        "--- a/mod.py\n"
        "+++ b/mod.py\n"
        "@@ -1,3 +1,3 @@\n"
        " x = 1\n"
        "--- old comment\n"
        "+++ new comment\n"
        " y = 2\n"
    )

    def test_added_and_deleted_double_sign_lines_are_content(self):
        changes = parse_diff(self.DIFF)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].added, [(2, "++ new comment")])
        self.assertEqual(changes[0].deleted, [(2, "-- old comment")])

    def test_paths_are_not_corrupted_by_hunk_content(self):
        changes = parse_diff(self.DIFF)
        self.assertEqual(changes[0].old_path, "mod.py")
        self.assertEqual(changes[0].new_path, "mod.py")


class TestHeaderlessDiffs(unittest.TestCase):
    def test_plain_diff_u_single_file(self):
        changes = parse_diff(
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1 +1 @@\n"
            "-a = 1\n"
            "+a = 2\n"
        )
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].path, "x.py")
        self.assertEqual(changes[0].added, [(1, "a = 2")])
        self.assertEqual(changes[0].deleted, [(1, "a = 1")])

    def test_plain_diff_u_two_files_concatenated(self):
        changes = parse_diff(
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1 +1 @@\n"
            "-a = 1\n"
            "+a = 2\n"
            "--- a/y.py\n"
            "+++ b/y.py\n"
            "@@ -1 +1 @@\n"
            "-b = 1\n"
            "+b = 2\n"
        )
        self.assertEqual([c.path for c in changes], ["x.py", "y.py"])

    def test_plain_diff_u_new_file(self):
        changes = parse_diff(
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1 @@\n"
            "+new = True\n"
        )
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].path, "new.py")
        self.assertEqual(changes[0].status, "added")


class TestUnsafeDiffPaths(unittest.TestCase):
    def test_dotdot_path_is_refused(self):
        with self.assertRaises(ValueError):
            parse_diff(
                "diff --git a/../evil.py b/../evil.py\n"
                "--- a/../evil.py\n"
                "+++ b/../evil.py\n"
                "@@ -1 +1 @@\n"
                "-x = 1\n"
                "+x = 2\n"
            )

    def test_absolute_path_is_refused(self):
        with self.assertRaises(ValueError):
            parse_diff(
                "diff --git a//tmp/evil.py b//tmp/evil.py\n"
                "--- a//tmp/evil.py\n"
                "+++ b//tmp/evil.py\n"
                "@@ -1 +1 @@\n"
                "-x = 1\n"
                "+x = 2\n"
            )

    def test_dotdot_lookalike_filenames_are_fine(self):
        for name in ("..hidden.py", "a..b.py", "src/deep/mod.py"):
            changes = parse_diff(
                f"diff --git a/{name} b/{name}\n"
                f"--- a/{name}\n"
                f"+++ b/{name}\n"
                "@@ -1 +1 @@\n"
                "-x = 1\n"
                "+x = 2\n"
            )
            self.assertEqual([c.path for c in changes], [name])


# ---------------------------------------------------------------------------
# gitinput
# ---------------------------------------------------------------------------

class TestHeadContentTraversalGuard(unittest.TestCase):
    def test_dotdot_new_path_reads_nothing_outside_root(self):
        from ghostscope.diffparse import FileChange
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            root = tmp / "proj"
            root.mkdir()
            (tmp / "secret.txt").write_text("TOPSECRET\n")
            change = FileChange(old_path="../secret.txt",
                                new_path="../secret.txt")
            inp = ChangeInput("diff-file", "", [change])
            self.assertIsNone(inp.head_content(root, change))


class TestBinaryBlobDoesNotCrash(unittest.TestCase):
    def test_git_show_and_pack_on_binary_change(self):
        from ghostscope.pack import build_pack
        from ghostscope.profile import ScopeProfile
        from ghostscope.gitinput import load_change_input
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "proj"
            proj.mkdir()
            subprocess.run(["git", "init", "-q", str(proj)], check=True)
            git(proj, "config", "user.email", "test@example.com")
            git(proj, "config", "user.name", "GhostScope Tests")
            (proj / "data.bin").write_bytes(b"\x00\x01\xff\xfe v1 \x80\x81")
            git(proj, "add", "-A")
            git(proj, "commit", "-qm", "base")
            (proj / "data.bin").write_bytes(b"\x00\x02\xff\xfe v2 \x80\x81")
            git(proj, "add", "-A")
            git(proj, "commit", "-qm", "change")
            shown = git_show(proj, "HEAD:data.bin")
            self.assertIsInstance(shown, str)
            inp = load_change_input(proj, base="HEAD~1", head="HEAD")
            result = build_pack(proj, Path(td) / "pack", inp, ScopeProfile())
            changed = [c["path"] for c in result["scope"]["changed"]]
            self.assertIn("data.bin", changed)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def _bundle(tmp: Path, manifest, files: dict | None = None) -> Path:
    bundle = tmp / "pack"
    (bundle / "files").mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    for rel, text in (files or {}).items():
        dest = bundle / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    return bundle


def _entry(path, sliced=0, sha=EMPTY_SHA, mode="full"):
    return {"path": path, "mode": mode, "language": "python",
            "package": "", "original_tokens": 0,
            "sliced_tokens": sliced, "sha256": sha}


class TestValidateHardening(unittest.TestCase):
    def test_missing_file_with_claimed_tokens_is_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = _bundle(Path(td), {
                "files": [_entry("a.py", sliced=5, sha="0" * 64)],
                "total_sliced_tokens": 5, "total_original_tokens": 9})
            result = validate_pack(bundle)
            self.assertFalse(result["ok"])
            self.assertTrue(any("missing" in e for e in result["errors"]),
                            result["errors"])

    def test_non_object_manifest_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = _bundle(Path(td), [1, 2, 3])
            result = validate_pack(bundle)
            self.assertFalse(result["ok"])

    def test_empty_file_sha_is_checked(self):
        # Manifest claims the file's sliced text hashes to "\n"
        # (0 tokens, like the empty file on disk) but the bytes on
        # disk are empty: the old `if text` guard skipped this.
        with tempfile.TemporaryDirectory() as td:
            sha_nl = hashlib.sha256(b"\n").hexdigest()
            bundle = _bundle(Path(td), {
                "files": [_entry("a.py", sliced=0, sha=sha_nl)],
                "total_sliced_tokens": 0, "total_original_tokens": 0},
                files={"a.py": ""})
            result = validate_pack(bundle)
            self.assertFalse(result["ok"])
            self.assertTrue(any("sha256" in e for e in result["errors"]),
                            result["errors"])

    def test_zero_token_record_without_file_is_consistent(self):
        # build_pack writes no file for an empty slice; a manifest
        # declaring exactly that must still validate.
        with tempfile.TemporaryDirectory() as td:
            bundle = _bundle(Path(td), {
                "files": [_entry("a.py", sliced=0, sha=EMPTY_SHA,
                                 mode="signatures")],
                "total_sliced_tokens": 0, "total_original_tokens": 3})
            result = validate_pack(bundle)
            self.assertTrue(result["ok"], result["errors"])

    def test_unsafe_manifest_path_is_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            bundle = _bundle(Path(td), {
                "files": [_entry("../secret.txt")],
                "total_sliced_tokens": 0, "total_original_tokens": 0})
            result = validate_pack(bundle)
            self.assertFalse(result["ok"])
            self.assertTrue(any("unsafe" in e for e in result["errors"]),
                            result["errors"])


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------

class TestCliErrorHandling(unittest.TestCase):
    def test_unwritable_out_path_returns_2_not_traceback(self):
        from ghostscope.cli import main
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            proj = tmp / "proj"
            proj.mkdir()
            (proj / "app.py").write_text("x = 1\n")
            diff = tmp / "changes.diff"
            diff.write_text(
                "diff --git a/app.py b/app.py\n"
                "--- a/app.py\n"
                "+++ b/app.py\n"
                "@@ -0,0 +1 @@\n"
                "+x = 1\n"
            )
            out_file = tmp / "not-a-dir"
            out_file.write_text("occupied")
            rc = main(["pack", str(proj), "--diff", str(diff),
                       "-o", str(out_file)])
            self.assertEqual(rc, 2)


# ---------------------------------------------------------------------------
# mcp server
# ---------------------------------------------------------------------------

class TestMcpRobustness(unittest.TestCase):
    def test_non_object_message_gets_invalid_request(self):
        from ghostscope.mcp_server import handle_message
        for bad in (["not", "a", "dict"], "text", 42, None):
            resp = handle_message(bad)
            self.assertIsNotNone(resp)
            self.assertEqual(resp["error"]["code"], -32600)

    def test_ping_still_works(self):
        from ghostscope.mcp_server import handle_message
        resp = handle_message({"jsonrpc": "2.0", "id": 3, "method": "ping"})
        self.assertEqual(resp["id"], 3)
        self.assertEqual(resp["result"], {})

    def test_serve_answers_parse_errors_and_keeps_serving(self):
        from ghostscope.mcp_server import serve
        stdin = io.StringIO(
            "this is not json\n"
            '{"jsonrpc": "2.0", "id": 9, "method": "ping"}\n')
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdin", stdin), \
                mock.patch.object(sys, "stdout", stdout):
            self.assertEqual(serve(), 0)
        out = stdout.getvalue()
        self.assertIn("-32700", out)
        self.assertIn('"id": 9', out)


# ---------------------------------------------------------------------------
# scanner
# ---------------------------------------------------------------------------

class TestScannerSingleRead(unittest.TestCase):
    def test_scan_survives_read_text_failure(self):
        # scan() used to call read_text() for a second, unguarded
        # read of every file; it now decodes the bytes it already
        # read, so a failing read_text cannot crash or skew a scan.
        from ghostscope import scanner
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "proj"
            proj.mkdir()
            (proj / "a.py").write_text("x = 1\n")
            with mock.patch.object(
                    scanner, "read_text",
                    side_effect=OSError("removed mid-scan")):
                result = scanner.scan(proj)
            self.assertEqual([f.path for f in result.files], ["a.py"])

    def test_bom_file_still_decodes_in_scan(self):
        from ghostscope.scanner import scan
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "proj"
            proj.mkdir()
            (proj / "b.txt").write_bytes(
                b"\xef\xbb\xbf" + "plain text here\n".encode("utf-8"))
            result = scan(proj)
            by_path = result.by_path()
            self.assertEqual(by_path["b.txt"].lines, 1)
            self.assertGreater(by_path["b.txt"].tokens, 0)

    def test_shared_decoder_handles_utf16(self):
        # The decoder extracted from read_text must keep its BOM /
        # UTF-16 behaviour for the callers that read via read_text.
        from ghostscope.scanner import _decode, read_text
        self.assertEqual(_decode("héllo\n".encode("utf-16")), "héllo\n")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.txt"
            p.write_bytes("héllo\n".encode("utf-16"))
            self.assertEqual(read_text(p), "héllo\n")


if __name__ == "__main__":
    unittest.main()
