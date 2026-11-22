"""Core CLI contract tests, written against PLAN.md / cli.py:

  ghostlift inspect <artifact> [--json]
  ghostlift lift <artifact-or-folder> -o <out>
      writes <out>/files/... plus <out>/manifest.json, every file
      entry marked lifted with its tier, source artifact, sha256.

These run the real core as a subprocess. If the core CLI is not
available yet they skip with that reason (the parent re-runs the
suite on the combined tree). Minified JS is a core Tier 2 lift:
inspect reports it liftable with its function boundaries, and the
JS lift itself is covered in depth in test_js_lift.py and
test_js_core_lift.py.
"""

import json
import os
import pathlib
import py_compile
import subprocess
import sys
import tempfile
import unittest

from tests.helpers import EXAMPLES, FIXTURES, ROOT

SRC = ROOT / "src"


def run_cli(*args, timeout=60):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "ghostlift", *[str(a) for a in args]],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def cli_available() -> bool:
    if not (SRC / "ghostlift" / "cli.py").is_file():
        return False
    try:
        return run_cli("--help", timeout=30).returncode == 0
    except Exception:
        return False


@unittest.skipUnless(cli_available(), "ghostlift core CLI not available yet (Agent A surface)")
class CliInspectTest(unittest.TestCase):
    def test_inspect_sourcemap_json(self):
        result = run_cli("inspect", FIXTURES / "sourcemap" / "bundle.js.map", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)
        self.assertEqual(info["kind"], "sourcemap")
        self.assertEqual(info["tier"], 1)
        self.assertTrue(info["liftable"])
        self.assertEqual(info["sources_recoverable"], 2)
        self.assertEqual(info["sources_not_recovered"], [])

    def test_inspect_js_reports_tier2_liftable_by_core(self):
        result = run_cli("inspect", FIXTURES / "minified" / "app.min.js", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)
        self.assertEqual(info["kind"], "javascript")
        self.assertEqual(info["tier"], 2)
        self.assertTrue(info["liftable"])
        self.assertEqual(
            info["function_boundaries"], ["clamp", "describeScore", "doubleIt"]
        )


@unittest.skipUnless(cli_available(), "ghostlift core CLI not available yet (Agent A surface)")
class CliLiftTest(unittest.TestCase):
    def test_lift_sourcemap_recovers_originals_and_watermarks_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out"
            result = run_cli("lift", FIXTURES / "sourcemap" / "bundle.js.map", "-o", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["totals"]["files"], 2)
            for entry in manifest["files"]:
                self.assertTrue(entry["lifted"])
                self.assertEqual(entry["tier"], 1)
                self.assertIn("source_sha256", entry)
                recovered = (out / "files" / entry["path"]).read_bytes()
                original = (
                    FIXTURES / "sourcemap" / "originals" / entry["source_path_in_map"]
                ).read_bytes()
                self.assertEqual(recovered, original)

    def test_lift_pyc_recovers_signature_names_and_tier2_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            pyc = tmp_path / "sample_module.pyc"
            py_compile.compile(
                str(EXAMPLES / "pyc_demo" / "sample_module.py"),
                cfile=str(pyc),
                doraise=True,
            )
            out = tmp_path / "out"
            result = run_cli("lift", pyc, "-o", out)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["totals"]["files"], 1)
            entry = manifest["files"][0]
            self.assertTrue(entry["lifted"])
            self.assertEqual(entry["tier"], 2)
            lifted_text = (out / "files" / entry["path"]).read_text()
            for name in ("greet", "add", "Pair", "__init__", "swap"):
                self.assertIn(name, lifted_text)
            # The lifted .py names it a reconstruction, not an original.
            self.assertIn("lift", lifted_text.lower())


if __name__ == "__main__":
    unittest.main()
