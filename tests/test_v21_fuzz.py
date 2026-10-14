"""G16 (v0.21): fuzz + encoding robustness.

The rule under test, for every case: NO unhandled traceback from
any command on ANY input bytes. Malformed input degrades to a
clear error (typed error -> CLI exit code) or a documented
fallback. The corpus is deterministic (tests/fuzz_harness.py):
same seed, same cases, every run.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fuzz_harness import (LEDGER_CASES, PROFILE_CASES, SEED_FILES,
                          manifest_mutations, mutated_corpus)

from ghostslice import textio
from ghostslice.cli import main as cli_main
from ghostslice.exporter import build_bundle, validate_bundle
from ghostslice.mcp_server import handle_message, run_stdio
from ghostslice.scanner import language_for, scan
from ghostslice.secrets_scan import redact_text, scan_text
from ghostslice.slicer import MODES, slice_text
from ghostslice.symslice import outline_source, slice_with_symbols
from ghostslice.tokens import estimate_tokens

CASE_BUDGET_S = 5.0  # per fuzz case, per the goal's wall-clock bound


def run_cli(argv: list[str]) -> int:
    """main() must return an int; ANY escaped exception is a
    failure with the argv and exception in the message."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(argv)
    except SystemExit as exc:  # argparse exits; a code is a code
        return int(exc.code or 0)
    except BaseException as exc:  # noqa: BLE001 - the point of the fuzz
        raise AssertionError(
            f"CLI {argv!r} raised {type(exc).__name__}: {exc}") from exc
    assert isinstance(code, int), f"CLI {argv!r} returned {code!r}"
    return code


class CorpusSanityTests(unittest.TestCase):
    def test_corpus_is_deterministic_and_bounded(self):
        a = mutated_corpus()
        b = mutated_corpus()
        self.assertEqual(a, b)
        # 10 seed files x (raw + 9 recipes)
        self.assertEqual(len(a), 10 * 10)
        names = [n for n, _ in a]
        self.assertEqual(len(names), len(set(names)))


class LibrarySurfaceTests(unittest.TestCase):
    """Every corpus case through every library entry point that
    consumes source text. No raises; each case inside the budget."""

    def test_slice_all_modes_all_cases(self):
        for name, data in mutated_corpus():
            text, _label = textio.decode_bytes(data)
            path = name.split("/")[0]
            t0 = time.perf_counter()
            for mode in MODES:
                try:
                    r = slice_text(path, text, mode)
                except BaseException as exc:  # noqa: BLE001
                    self.fail(f"{name} mode={mode}: "
                              f"{type(exc).__name__}: {exc}")
                self.assertIsInstance(r.text, str)
            dt = time.perf_counter() - t0
            self.assertLess(dt, CASE_BUDGET_S, f"{name} too slow: {dt:.1f}s")

    def test_outlines_symbols_secrets_all_cases(self):
        keep = {"total", "Store.total", "helper", "main", "Total"}
        for name, data in mutated_corpus():
            text, _label = textio.decode_bytes(data)
            path = name.split("/")[0]
            lang = language_for(path)
            t0 = time.perf_counter()
            try:
                outline_source(text, lang, path)
                slice_with_symbols(path, text, keep)
                scan_text(path, text)
                scan_text(path, text, comments=True)
                redact_text(path, text)
                estimate_tokens(text, lang)
            except BaseException as exc:  # noqa: BLE001
                self.fail(f"{name}: {type(exc).__name__}: {exc}")
            dt = time.perf_counter() - t0
            self.assertLess(dt, CASE_BUDGET_S, f"{name} too slow: {dt:.1f}s")


class _ProjectMixin:
    def make_project(self, files: dict[str, bytes]) -> Path:
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="gs-fuzz-"))
        for rel, data in files.items():
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        return root


class CliProjectSweepTests(_ProjectMixin, unittest.TestCase):
    """All corpus files in ONE project; every command must return
    an int code, and produced bundles must validate."""

    @classmethod
    def setUpClass(cls):
        mixin = _ProjectMixin()
        files = {}
        for name, data in mutated_corpus():
            fname, recipe = name.split("/")
            stem, dot, ext = fname.partition(".")
            files[f"{stem}_{recipe}.{ext}"] = data
        cls.root = mixin.make_project(files)

    def test_command_sweep(self):
        root = str(self.root)
        out = self.root.parent / (self.root.name + "-bundle")
        commands = [
            ["scan", root],
            ["scan", root, "--json"],
            ["scan", root, "--timing"],
            ["graph", root],
            ["graph", root, "--json"],
            ["lint", root],
            ["lint", root, "--json"],
            ["secrets", root],
            ["secrets", root, "--json"],
            ["calls", root],
            ["calls", root, "--dead"],
            ["calls", root, "--json"],
            ["symbols", root],
            ["symbols", root, "--json"],
            ["history", root],
            ["history", root, "--trend"],
            ["calibrate", root],
            ["calibrate", root, "--json"],
            ["check-budget", root, "--max-tokens", "100000000"],
            ["explain", root, "mod_raw.py"],
            ["init", root, "--dry-run"],
            ["task", root, "--task", "store total helper", "-o", str(out / "task")],
            ["export", root, "-o", str(out / "plain")],
            ["export", root, "-o", str(out / "json"), "--preset", "json"],
            ["export", root, "-o", str(out / "xml"), "--preset", "anthropic-xml"],
            ["export", root, "-o", str(out / "redact"), "--redact"],
            ["export", root, "-o", str(out / "fit"), "--fit", "2000"],
            ["export", root, "-o", str(out / "auto"), "--auto-shrink"],
            ["export", root, "-o", str(out / "sym"), "--symbols", "total"],
            ["slice", root, "--mode", "signatures", "-o", str(out / "slices")],
            ["report", root, "-o", str(out / "report.html")],
            ["cache", "stats", root],
            ["watch", root, "--once"],
        ]
        for argv in commands:
            t0 = time.perf_counter()
            code = run_cli(argv)
            dt = time.perf_counter() - t0
            self.assertLess(dt, 30.0, f"{argv[:2]} too slow: {dt:.1f}s")
            self.assertIn(code, (0, 1, 2), f"{argv[:2]} -> {code}")
        for name in ("plain", "json", "xml", "redact", "sym"):
            bundle = out / name
            if bundle.is_dir():
                check = validate_bundle(bundle)
                self.assertTrue(check["ok"], f"{name}: {check['errors'][:3]}")

    def test_per_case_single_file_projects(self):
        # The nastiest recipes on the most-parsed formats, isolated:
        # scan + export + calls + symbols per single-file project.
        nasty = {"bom", "badutf8", "nul", "unbalance", "truncate"}
        for name, data in mutated_corpus():
            fname, recipe = name.split("/")
            if recipe not in nasty or fname not in (
                    "mod.py", "api.js", "data.json", "nb.ipynb", "main.go"):
                continue
            root = self.make_project({fname: data})
            self.assertIn(run_cli(["scan", str(root)]), (0, 1, 2), name)
            self.assertIn(
                run_cli(["export", str(root), "-o", str(root / "out")]),
                (0, 1, 2), name)
            self.assertIn(run_cli(["symbols", str(root)]), (0, 1, 2), name)
            self.assertIn(run_cli(["lint", str(root)]), (0, 1, 2), name)


class EncodingTests(_ProjectMixin, unittest.TestCase):
    PY = "def café(x):\n    # über comment\n    return x + 1\n\n\ndef second():\n    return 'naïve'\n"

    def twin(self, blob: bytes, name: str = "a.py") -> Path:
        return self.make_project({name: blob})

    def test_decode_labels(self):
        py = self.PY
        cases = [
            (py.encode("utf-8"), "utf-8"),
            (b"\xef\xbb\xbf" + py.encode("utf-8"), "utf-8-sig"),
            (py.encode("utf-16"), "utf-16-le"),
            (b"\xfe\xff" + py.encode("utf-16-be"), "utf-16-be"),
            (py.encode("utf-32"), "utf-32-le"),
            (b"\x00\x00\xfe\xff" + py.encode("utf-32-be"), "utf-32-be"),
            (py.encode("latin-1"), "latin-1"),
        ]
        for blob, label in cases:
            text, got = textio.decode_bytes(blob)
            self.assertEqual(got, label)
            self.assertEqual(text, py, label)

    def test_encodings_scan_and_export_like_utf8(self):
        reference = None
        variants = {
            "utf-8": self.PY.encode("utf-8"),
            "utf-8-sig": b"\xef\xbb\xbf" + self.PY.encode("utf-8"),
            "utf-16-le": self.PY.encode("utf-16"),
            "utf-32-le": self.PY.encode("utf-32"),
            "latin-1": self.PY.encode("latin-1"),
        }
        for label, blob in variants.items():
            root = self.twin(blob)
            result = scan(root)
            self.assertEqual(len(result.files), 1, label)
            entry = result.files[0]
            self.assertEqual(entry.encoding, label)
            if reference is None:
                reference = entry.tokens
            self.assertEqual(entry.tokens, reference, label)
            self.assertEqual(entry.lines, 7, label)
            manifest = build_bundle(root, root / "bundle")
            rec = {f["path"]: f for f in manifest["files"]}["a.py"]
            if label == "utf-8":
                self.assertNotIn("source_encoding", rec)
            else:
                self.assertEqual(rec["source_encoding"], label)
            shipped = (root / "bundle" / "files" / "a.py").read_text(
                encoding="utf-8")
            self.assertIn("def café", shipped, label)
            self.assertTrue(validate_bundle(root / "bundle")["ok"], label)

    def test_wide_bom_unknown_extension_admitted(self):
        root = self.make_project(
            {"notes.zzz": "hello world\nsome text\n".encode("utf-16")})
        result = scan(root)
        self.assertEqual(len(result.files), 1)
        self.assertEqual(result.files[0].encoding, "utf-16-le")

    def test_cr_only_lines_and_slicing(self):
        blob = self.PY.replace("\n", "\r").encode()
        root = self.twin(blob)
        result = scan(root)
        self.assertEqual(result.files[0].lines, 7)
        sliced = slice_text("a.py", textio.decode_bytes(blob)[0],
                            "signatures")
        self.assertIn("def café", sliced.text)
        self.assertIn("def second", sliced.text)

    def test_crlf_matches_lf(self):
        lf = scan(self.twin(self.PY.encode()))
        crlf = scan(self.twin(self.PY.replace("\n", "\r\n").encode()))
        self.assertEqual(lf.files[0].tokens, crlf.files[0].tokens)
        self.assertEqual(lf.files[0].lines, crlf.files[0].lines)
        a = slice_text("a.py", self.PY, "signatures").text
        b = slice_text("a.py", self.PY.replace("\n", "\r\n"),
                       "signatures").text
        self.assertEqual(a, b)


class ProfileFamilyTests(_ProjectMixin, unittest.TestCase):
    EXPECTED = {  # case -> scan exit code on a project using it
        "valid": 0, "empty": 2, "truncated": 2, "not-json": 2,
        "top-list": 2, "top-string": 2, "top-null": 2, "ignore-int": 2,
        "ignore-str": 2, "ignore-mixed": 2, "modes-list": 2,
        "modes-int-value": 2, "budget-str": 2, "budget-bool": 2,
        "budget-list": 2, "model-int": 2, "entry-mixed": 2,
        "bad-utf8": 2, "preset-bad": 2, "lint-bad": 2,
    }

    def test_profile_family(self):
        self.assertEqual(set(self.EXPECTED), set(PROFILE_CASES))
        for name, blob in PROFILE_CASES.items():
            root = self.make_project(
                {"x.py": SEED_FILES["mod.py"], ".ghostslice.json": blob})
            code = run_cli(["scan", str(root)])
            self.assertEqual(code, self.EXPECTED[name], f"profile {name}")


class ManifestFamilyTests(_ProjectMixin, unittest.TestCase):
    def setUp(self):
        self.root = self.make_project({"x.py": SEED_FILES["mod.py"]})
        self.bundle = self.root / "bundle"
        build_bundle(self.root, self.bundle)
        self.valid = (self.bundle / "manifest.json").read_bytes()

    def test_manifest_mutations_fail_cleanly(self):
        valid_twin = self.root / "twin"
        build_bundle(self.root, valid_twin)
        for name, blob in manifest_mutations(self.valid).items():
            (self.bundle / "manifest.json").write_bytes(blob)
            check = validate_bundle(self.bundle)
            self.assertIsInstance(check, dict, name)
            self.assertFalse(check["ok"], f"{name} unexpectedly valid")
            self.assertEqual(run_cli(["check", str(self.bundle)]), 1, name)
            self.assertEqual(
                run_cli(["diff", str(self.bundle), str(valid_twin)]), 1, name)
            (self.bundle / "manifest.json").write_bytes(self.valid)

    def test_missing_manifest(self):
        ghost = self.root / "no-such-bundle"
        check = validate_bundle(ghost)
        self.assertFalse(check["ok"])
        self.assertEqual(run_cli(["check", str(ghost)]), 1)
        self.assertEqual(run_cli(["check", str(self.root / "x.py")]), 1)


class LedgerFamilyTests(_ProjectMixin, unittest.TestCase):
    def test_ledger_family(self):
        for name, blob in LEDGER_CASES.items():
            root = self.make_project(
                {"x.py": SEED_FILES["mod.py"],
                 ".ghostslice-history.jsonl": blob})
            self.assertEqual(run_cli(["history", str(root)]), 0, name)
            self.assertEqual(
                run_cli(["history", str(root), "--trend"]), 0, name)
            self.assertEqual(
                run_cli(["history", str(root), "--json"]), 0, name)


class PathRobustnessTests(_ProjectMixin, unittest.TestCase):
    def test_nonexistent_project_every_command(self):
        ghost = "/nonexistent-gs-fuzz/project"
        out = "/tmp/gs-fuzz-out"
        argvs = [
            ["scan", ghost], ["scan", ghost, "--json"], ["graph", ghost],
            ["export", ghost, "-o", out], ["lint", ghost],
            ["secrets", ghost], ["calls", ghost], ["symbols", ghost],
            ["history", ghost], ["calibrate", ghost],
            ["check-budget", ghost], ["explain", ghost, "a.py"],
            ["report", ghost, "-o", "/tmp/gs-fuzz-r.html"],
            ["task", ghost, "--task", "x", "-o", out],
            ["init", ghost, "--dry-run"], ["watch", ghost, "--once"],
            ["slice", ghost, "-o", out], ["cache", "stats", ghost],
            ["cache", "clear", ghost],
        ]
        for argv in argvs:
            self.assertIn(run_cli(argv), (0, 1, 2), argv[:2])

    def test_file_and_dir_confusion(self):
        root = self.make_project({"x.py": SEED_FILES["mod.py"]})
        a_file = str(root / "x.py")
        for argv in (["scan", a_file], ["export", a_file, "-o", "/tmp/gs-o"],
                     ["check", a_file], ["diff", a_file, a_file],
                     ["history", a_file], ["lint", a_file]):
            self.assertIn(run_cli(argv), (0, 1, 2), argv[:2])
        # empty dir is a valid, empty project
        empty = self.make_project({})
        self.assertEqual(run_cli(["scan", str(empty)]), 0)
        self.assertIn(
            run_cli(["export", str(empty), "-o", str(empty / "o")]), (0, 1, 2))

    def test_unreadable_paths_do_not_traceback(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root reads anything; permission paths moot")
        root = self.make_project({"x.py": SEED_FILES["mod.py"],
                                  "sub/y.py": SEED_FILES["mod.py"]})
        os.chmod(root / "sub", 0)
        try:
            self.assertIn(run_cli(["scan", str(root)]), (0, 1, 2))
            self.assertIn(
                run_cli(["export", str(root), "-o", str(root / "o")]),
                (0, 1, 2))
        finally:
            os.chmod(root / "sub", 0o755)
        os.chmod(root / "x.py", 0)
        try:
            self.assertIn(run_cli(["scan", str(root)]), (0, 1, 2))
        finally:
            os.chmod(root / "x.py", 0o644)
        locked = self.make_project({"x.py": SEED_FILES["mod.py"]})
        os.chmod(locked, 0)
        try:
            self.assertEqual(run_cli(["scan", str(locked)]), 2)
        finally:
            os.chmod(locked, 0o755)


class SizeGuardTests(unittest.TestCase):
    def test_giant_single_line(self):
        src = "var x = '" + "a" * (10 * 1024 * 1024) + "';\n"
        t0 = time.perf_counter()
        r = slice_text("x.js", src, "signatures")
        self.assertLess(time.perf_counter() - t0, CASE_BUDGET_S)
        self.assertGreater(r.original_tokens, 0)

    def test_deep_nesting_degrades(self):
        deep_py = "x = " + "(" * 3000 + "1" + ")" * 3000 + "\n"
        for mode in MODES:
            slice_text("x.py", deep_py, mode)  # must not raise
        deep_json = '{"a": ' * 300 + "1" + "}" * 300
        r = slice_text("x.json", deep_json, "structure")
        json.loads(r.text)  # shaped with the depth-cap placeholder
        self.assertNotEqual(r.text, deep_json)
        # Past the interpreter's own parse limit (<3.12) json.loads
        # fails and the slicer falls back to full; it must not raise.
        slice_text("x.json", '{"a": ' * 1200 + "1" + "}" * 1200, "structure")
        huge_json = '{"a": ' * 20000 + "1" + "}" * 20000
        r = slice_text("x.json", huge_json, "structure")
        self.assertEqual(r.text, huge_json)  # loads fails -> full fallback
        deep_if = "".join("    " * i + "if True:\n" for i in range(250))
        slice_text("x.py", deep_if + "    " * 250 + "pass\n", "signatures")

    def test_unbalanced_braces_scale_linearly(self):
        def timeit(n: int) -> float:
            src = "function f(){" * n + "\n"
            t0 = time.perf_counter()
            slice_text("x.js", src, "signatures")
            return time.perf_counter() - t0
        small, big = timeit(20_000), timeit(80_000)
        self.assertLess(big, 10.0)
        # 4x input must cost well under 16x (quadratic): allow 8x.
        self.assertLess(big, max(8 * small, small + 2.0))

    def test_hundred_k_line_file(self):
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="gs-fuzz-big-"))
        (root / "big.py").write_text(
            "".join(f"def f{i}():\n    return {i}\n\n" for i in range(34000)))
        result = scan(root)
        self.assertEqual(result.files[0].lines, 102000)
        t0 = time.perf_counter()
        self.assertEqual(run_cli(["export", str(root), "-o", str(root / "o")]), 0)
        self.assertLess(time.perf_counter() - t0, 20.0)


class CacheCorruptionTests(_ProjectMixin, unittest.TestCase):
    def test_random_bytes_in_cache_never_poison(self):
        root = self.make_project({"x.py": SEED_FILES["mod.py"],
                                  "a.js": SEED_FILES["api.js"]})
        # Bundles live OUTSIDE the project (a bundle inside the
        # root would itself be scanned by the next build).
        outside = root.parent / (root.name + "-bundles")
        truth = build_bundle(root, outside / "truth", use_cache=False)
        first = build_bundle(root, outside / "b1")
        cache_dir = root / ".ghostslice-cache"
        self.assertTrue(cache_dir.is_dir())
        rng = __import__("random").Random(7)
        for path in cache_dir.rglob("*"):
            if path.is_file():
                path.write_bytes(bytes(rng.randrange(256) for _ in range(64)))
        second = build_bundle(root, outside / "b2")
        self.assertEqual(first["total_sliced_tokens"],
                         truth["total_sliced_tokens"])
        self.assertEqual(second["total_sliced_tokens"],
                         truth["total_sliced_tokens"])
        self.assertTrue(validate_bundle(outside / "b2")["ok"])


class CampaignTwoRegressionTests(_ProjectMixin, unittest.TestCase):
    """Finds from the G16 audit's second campaign (new mutations /
    surfaces beyond the first harness): each pinned as it was fixed."""

    def test_fifo_in_tree_does_not_hang_scan(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("no mkfifo on this platform")
        root = self.make_project({"x.py": SEED_FILES["mod.py"]})
        os.mkfifo(root / "pipe.py")
        t0 = time.perf_counter()
        code = run_cli(["scan", str(root)])
        self.assertLess(time.perf_counter() - t0, CASE_BUDGET_S)
        self.assertEqual(code, 0)
        result = scan(root)
        self.assertEqual([f.path for f in result.files], ["x.py"])

    def test_unknown_model_id_is_exit_2_everywhere(self):
        root = self.make_project({"x.py": SEED_FILES["mod.py"]})
        for argv in (["scan", str(root), "--model", "nope"],
                     ["export", str(root), "-o", str(root / "o"),
                      "--model", "nope"],
                     ["task", str(root), "--task", "x", "-o", str(root / "t"),
                      "--model", "nope"],
                     ["report", str(root), "-o", str(root / "r.html"),
                      "--model", "nope"],
                     ["history", str(root), "--model", "nope"]):
            self.assertEqual(run_cli(argv), 2, argv[:2])
        bad = self.make_project(
            {"x.py": SEED_FILES["mod.py"],
             ".ghostslice.json": b'{"model": "nope"}'})
        self.assertEqual(run_cli(["scan", str(bad)]), 2)

    def test_bom_profile_loads(self):
        root = self.make_project(
            {"x.py": SEED_FILES["mod.py"],
             ".ghostslice.json": b'\xef\xbb\xbf{"budget_tokens": 1000}'})
        self.assertEqual(run_cli(["scan", str(root)]), 0)

    def test_symlink_loop_is_skipped(self):
        root = self.make_project({"x.py": SEED_FILES["mod.py"]})
        try:
            os.symlink("loop.py", root / "loop.py")
            os.symlink("x.py", root / "alias.py")
        except OSError:
            self.skipTest("symlinks not permitted")
        self.assertEqual(run_cli(["scan", str(root)]), 0)
        paths = [f.path for f in scan(root).files]
        self.assertNotIn("loop.py", paths)  # ELOOP read error -> skip
        self.assertIn("alias.py", paths)    # regular target: followed

    def test_profile_as_directory_is_ignored(self):
        root = self.make_project({"x.py": SEED_FILES["mod.py"]})
        (root / ".ghostslice.json").mkdir()
        self.assertEqual(run_cli(["scan", str(root)]), 0)


class McpRobustnessTests(unittest.TestCase):
    def test_handle_message_wrong_shapes(self):
        for msg in ([], {"method": 5}, {"method": None},
                    {"method": "tools/call", "params": [1, 2]},
                    {"method": "tools/call",
                     "params": {"name": ["x"], "arguments": {}}},
                    {"method": "tools/call",
                     "params": {"name": "scan_project",
                                "arguments": {"path": "/nonexistent-gs"}}}):
            resp = handle_message(msg)  # must not raise
            self.assertTrue(resp is None or isinstance(resp, dict), msg)

    def test_run_stdio_garbage_lines(self):
        instream = io.StringIO(
            'not json\n[1,2]\n"str"\n{"method": "ping", "id": 1}\n')
        outstream = io.StringIO()
        run_stdio(instream, outstream)  # must return, not raise
        lines = [ln for ln in outstream.getvalue().splitlines() if ln]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["id"], 1)


if __name__ == "__main__":
    unittest.main()
