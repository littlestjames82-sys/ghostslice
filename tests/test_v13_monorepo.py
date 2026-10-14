"""v0.13 (G8): monorepo / workspace support — workspaces.py detection
(npm / pnpm / Cargo / go.work / uv declared sources + manifest
fallback), scanner `package` assignment, per-package subtotals on
scan (text + JSON), the export manifest, /api/scan and the HTML
report. Per-package budgets are explicitly out of scope.
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
from ghostslice.exporter import build_bundle, estimate_context_tokens, validate_bundle
from ghostslice.profile import load_profile
from ghostslice.report import build_report
from ghostslice.scanner import scan
from ghostslice.server import make_server
from ghostslice.workspaces import detect_workspaces, summarize_packages

CODE = "def main():\n    return 1\n\n\nmain()\n"


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def run_cli(argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main(argv)
    return code, out.getvalue(), err.getvalue()


def npm_fixture(root: Path) -> None:
    write(root, "package.json", json.dumps(
        {"name": "rootproj", "workspaces": ["packages/*"]}))
    write(root, "src/root.ts", "export const root = 1;\n")
    write(root, "packages/a/package.json", json.dumps({"name": "a"}))
    write(root, "packages/a/index.ts", "export const a = 1;\n")
    write(root, "packages/b/package.json", json.dumps({"name": "b"}))
    write(root, "packages/b/main.py", CODE)


class MonoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def packages_by_path(self):
        info = detect_workspaces(self.root)
        return info, {p.path: p for p in info.packages}


class TestNpmDetection(MonoCase):
    def test_array_form_glob_members(self):
        npm_fixture(self.root)
        info, by_path = self.packages_by_path()
        self.assertEqual(set(by_path), {"", "packages/a", "packages/b"})
        self.assertEqual(by_path["packages/a"].kind, "declared")
        self.assertIn("npm", by_path["packages/a"].source)
        self.assertEqual(by_path["packages/a"].manifest, "packages/a/package.json")
        self.assertEqual(by_path[""].kind, "root")
        self.assertTrue(info.is_monorepo)
        self.assertTrue(info.declared)
        self.assertEqual(info.missing, [])

    def test_scan_assigns_packages(self):
        npm_fixture(self.root)
        result = scan(self.root)
        got = {f.path: f.package for f in result.files}
        self.assertEqual(got["packages/a/index.ts"], "packages/a")
        self.assertEqual(got["packages/b/main.py"], "packages/b")
        self.assertEqual(got["src/root.ts"], "")
        self.assertEqual(got["package.json"], "")

    def test_object_form_and_negation(self):
        write(self.root, "package.json", json.dumps({
            "name": "rootproj",
            "workspaces": {"packages": ["packages/*", "!packages/skip"]}}))
        write(self.root, "packages/keep/package.json", json.dumps({"name": "keep"}))
        write(self.root, "packages/keep/index.ts", "export const k = 1;\n")
        write(self.root, "packages/skip/package.json", json.dumps({"name": "skip"}))
        write(self.root, "packages/skip/index.ts", "export const s = 1;\n")
        info, by_path = self.packages_by_path()
        self.assertIn("packages/keep", by_path)
        self.assertNotIn("packages/skip", by_path)
        result = scan(self.root)
        got = {f.path: f.package for f in result.files}
        self.assertEqual(got["packages/skip/index.ts"], "")

    def test_glob_match_without_manifest_is_not_a_member(self):
        write(self.root, "package.json", json.dumps(
            {"name": "r", "workspaces": ["packages/*"]}))
        write(self.root, "packages/empty/code.ts", "export const e = 1;\n")
        info, by_path = self.packages_by_path()
        self.assertNotIn("packages/empty", by_path)
        self.assertEqual(info.missing, [])  # matched, just not a member


class TestPnpmDetection(MonoCase):
    def test_yaml_list_quotes_and_termination(self):
        write(self.root, "pnpm-workspace.yaml",
              "packages:\n"
              "  - 'packages/*'\n"
              '  - "libs/*" # extra tree\n'
              "\n"
              "onlyBuiltDependencies:\n"
              "  - esbuild\n")
        write(self.root, "packages/app1/package.json", json.dumps({"name": "app1"}))
        write(self.root, "packages/app1/index.ts", "export const a = 1;\n")
        write(self.root, "libs/util/package.json", json.dumps({"name": "util"}))
        write(self.root, "libs/util/index.ts", "export const u = 1;\n")
        info, by_path = self.packages_by_path()
        self.assertIn("packages/app1", by_path)
        self.assertIn("libs/util", by_path)
        self.assertEqual(by_path["libs/util"].kind, "declared")
        self.assertIn("pnpm", by_path["libs/util"].source)


class TestCargoDetection(MonoCase):
    def test_members_comments_exclude_and_section_bleed(self):
        write(self.root, "Cargo.toml",
              "[workspace]\n"
              'resolver = "2"\n'
              "members = [\n"
              '    "crates/*",   # all the crates\n'
              "    'tools/cli',\n"
              "]\n"
              'exclude = ["crates/skip"]\n'
              "\n"
              "[package]\n"
              'name = "rootpkg"\n'
              'keywords = ["zzz-not-a-member"]\n')
        for name in ("one", "two", "skip"):
            write(self.root, f"crates/{name}/Cargo.toml", f'[package]\nname = "{name}"\n')
            write(self.root, f"crates/{name}/src/lib.rs", "pub fn f() {}\n")
        write(self.root, "tools/cli/Cargo.toml", '[package]\nname = "cli"\n')
        write(self.root, "tools/cli/src/main.rs", "fn main() {}\n")
        info, by_path = self.packages_by_path()
        self.assertIn("crates/one", by_path)
        self.assertIn("crates/two", by_path)
        self.assertIn("tools/cli", by_path)
        self.assertNotIn("crates/skip", by_path)
        self.assertIn("cargo", by_path["crates/one"].source)
        result = scan(self.root)
        got = {f.path: f.package for f in result.files}
        self.assertEqual(got["crates/one/src/lib.rs"], "crates/one")
        self.assertEqual(got["crates/skip/src/lib.rs"], "")

    def test_hash_inside_quoted_member_name(self):
        write(self.root, "Cargo.toml",
              '[workspace]\nmembers = ["crates/a#b"] # the hash crate\n')
        write(self.root, "crates/a#b/Cargo.toml", '[package]\nname = "ab"\n')
        write(self.root, "crates/a#b/src/lib.rs", "pub fn f() {}\n")
        info, by_path = self.packages_by_path()
        self.assertIn("crates/a#b", by_path)


class TestGoWorkDetection(MonoCase):
    def test_single_and_block_use_forms(self):
        write(self.root, "go.work",
              "go 1.21\n"
              "\n"
              "use ./core\n"
              "\n"
              "use (\n"
              "\t./libs/foo\n"
              "\t./libs/bar // the bar library\n"
              ")\n")
        write(self.root, "core/go.mod", "module example.com/core\n\ngo 1.21\n")
        write(self.root, "core/core.go", "package core\n")
        for name in ("foo", "bar"):
            write(self.root, f"libs/{name}/go.mod", f"module example.com/{name}\n")
            write(self.root, f"libs/{name}/{name}.go", f"package {name}\n")
        info, by_path = self.packages_by_path()
        self.assertEqual(
            {p for p in by_path if p}, {"core", "libs/foo", "libs/bar"})
        self.assertIn("go.work", by_path["core"].source)


class TestUvDetection(MonoCase):
    def test_uv_workspace_members(self):
        write(self.root, "pyproject.toml",
              "[build-system]\n"
              'requires = ["hatchling"]\n'
              "\n"
              "[project]\n"
              'name = "rootproj"\n'
              "\n"
              "[tool.uv.workspace]\n"
              'members = ["pkgs/*"]\n'
              "\n"
              "[tool.uv.sources]\n")
        for name in ("one", "two"):
            write(self.root, f"pkgs/{name}/pyproject.toml",
                  f'[project]\nname = "{name}"\n')
            write(self.root, f"pkgs/{name}/mod.py", CODE)
        info, by_path = self.packages_by_path()
        self.assertIn("pkgs/one", by_path)
        self.assertIn("pkgs/two", by_path)
        self.assertIn("uv", by_path["pkgs/one"].source)
        self.assertEqual(by_path["pkgs/one"].kind, "declared")


class TestFallbackDetection(MonoCase):
    def test_manifest_dirs_detected_not_declared(self):
        write(self.root, "top.py", CODE)
        write(self.root, "libs/x/pyproject.toml", '[project]\nname = "x"\n')
        write(self.root, "libs/x/mod.py", CODE)
        write(self.root, "apps/y/package.json", json.dumps({"name": "y"}))
        write(self.root, "apps/y/app.js", "console.log(1);\n")
        write(self.root, "random/notes.txt", "no manifest here\n")
        write(self.root, "node_modules/z/package.json", json.dumps({"name": "z"}))
        write(self.root, "node_modules/z/index.js", "console.log(2);\n")
        info, by_path = self.packages_by_path()
        self.assertEqual(by_path["libs/x"].kind, "detected")
        self.assertEqual(by_path["apps/y"].kind, "detected")
        self.assertNotIn("random", by_path)
        self.assertNotIn("node_modules/z", by_path)
        self.assertFalse(info.declared)
        result = scan(self.root)
        got = {f.path: f.package for f in result.files}
        self.assertEqual(got["libs/x/mod.py"], "libs/x")
        self.assertEqual(got["top.py"], "")


class TestMissingAndUnsafe(MonoCase):
    def test_declared_but_missing_members(self):
        write(self.root, "package.json", json.dumps(
            {"name": "r", "workspaces": ["packages/*", "libs/ghost", "vendor/*"]}))
        write(self.root, "packages/a/package.json", json.dumps({"name": "a"}))
        write(self.root, "packages/a/index.ts", "export const a = 1;\n")
        info, _ = self.packages_by_path()
        self.assertIn("libs/ghost", info.missing)
        self.assertIn("vendor/*", info.missing)
        result = scan(self.root)  # never a crash
        self.assertTrue(result.files)

    def test_escaping_member_is_clamped_with_warning(self):
        proj = self.root / "proj"
        outside = self.root / "outside"
        write(outside, "package.json", json.dumps({"name": "outside"}))
        write(outside, "evil.ts", "export const evil = 1;\n")
        write(proj, "package.json", json.dumps(
            {"name": "r", "workspaces": ["../outside", "packages/*"]}))
        write(proj, "packages/a/package.json", json.dumps({"name": "a"}))
        write(proj, "packages/a/index.ts", "export const a = 1;\n")
        info = detect_workspaces(proj)
        by_path = {p.path: p for p in info.packages}
        self.assertTrue(any("../outside" in w for w in info.warnings))
        self.assertFalse(any(".." in p for p in by_path))
        result = scan(proj)
        self.assertFalse(any("evil" in f.path for f in result.files))


class TestNestedWorkspaces(MonoCase):
    def test_outermost_wins(self):
        write(self.root, "package.json", json.dumps(
            {"name": "r", "workspaces": ["apps/*", "apps/web/modules/*"]}))
        write(self.root, "apps/web/package.json", json.dumps({"name": "web"}))
        write(self.root, "apps/web/modules/m1/package.json", json.dumps({"name": "m1"}))
        write(self.root, "apps/web/modules/m1/code.ts", "export const m = 1;\n")
        info, by_path = self.packages_by_path()
        self.assertIn("apps/web", by_path)
        self.assertNotIn("apps/web/modules/m1", by_path)
        result = scan(self.root)
        got = {f.path: f.package for f in result.files}
        self.assertEqual(got["apps/web/modules/m1/code.ts"], "apps/web")


class TestSinglePackageUnchanged(MonoCase):
    def test_plain_project_has_only_root_package(self):
        write(self.root, "package.json", json.dumps({"name": "solo"}))
        write(self.root, "src/main.ts", "export const x = 1;\n")
        info, _ = self.packages_by_path()
        self.assertFalse(info.is_monorepo)
        result = scan(self.root)
        summary = summarize_packages(result)
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["path"], "")
        self.assertEqual(summary[0]["label"], "(root)")
        self.assertEqual(summary[0]["share"], 100.0)
        code, out, _ = run_cli(["scan", str(self.root)])
        self.assertEqual(code, 0)
        self.assertNotIn("Packages (", out)


class TestSurfaces(MonoCase):
    def setUp(self):
        super().setUp()
        npm_fixture(self.root)

    def test_scan_text_and_json(self):
        code, out, _ = run_cli(["scan", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("Packages (3):", out)
        self.assertIn("packages/a", out)
        self.assertIn("declared", out)
        code, out, _ = run_cli(["scan", str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        pkgs = {p["path"]: p for p in payload["packages"]}
        self.assertEqual(set(pkgs), {"", "packages/a", "packages/b"})
        self.assertEqual(pkgs["packages/a"]["kind"], "declared")
        self.assertEqual(pkgs["packages/a"]["files"], 2)
        total_share = sum(p["share"] for p in pkgs.values())
        self.assertAlmostEqual(total_share, 100.0, delta=0.1)
        files = {f["path"]: f for f in payload["files"]}
        self.assertEqual(files["packages/a/index.ts"]["package"], "packages/a")
        self.assertEqual(files["src/root.ts"]["package"], "")

    def test_manifest_packages_and_old_bundle_still_validates(self):
        out_dir = self.root / "bundle"
        manifest = build_bundle(self.root, out_dir, record_history=False)
        entries = {f["path"]: f for f in manifest["files"]}
        self.assertEqual(entries["packages/a/index.ts"]["package"], "packages/a")
        pkgs = {p["path"]: p for p in manifest["packages"]}
        self.assertEqual(set(pkgs), {"", "packages/a", "packages/b"})
        self.assertIn("sliced_tokens", pkgs["packages/a"])
        self.assertIn("sliced_share", pkgs["packages/a"])
        check = validate_bundle(out_dir)
        self.assertTrue(check["ok"], check["errors"])
        # Pre-v0.13 shape: strip the additive keys; still validates.
        mpath = out_dir / "manifest.json"
        old = json.loads(mpath.read_text(encoding="utf-8"))
        old.pop("packages", None)
        for f in old["files"]:
            f.pop("package", None)
        mpath.write_text(json.dumps(old, indent=2) + "\n", encoding="utf-8")
        check = validate_bundle(out_dir)
        self.assertTrue(check["ok"], check["errors"])

    def test_api_scan_packages(self):
        server, _state = make_server(str(self.root), port=0)
        t = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
        t.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/api/scan"
            with urllib.request.urlopen(url, timeout=10) as resp:
                payload = json.loads(resp.read())
        finally:
            server.shutdown()
            server.server_close()
        pkgs = {p["path"]: p for p in payload["packages"]}
        self.assertEqual(set(pkgs), {"", "packages/a", "packages/b"})
        files = {f["path"]: f for f in payload["files"]}
        self.assertEqual(files["packages/b/main.py"]["package"], "packages/b")

    def test_report_packages_table(self):
        html = build_report(self.root)
        self.assertIn("<h2>Packages</h2>", html)
        self.assertIn("packages/a", html)
        self.assertIn("declared", html)


class TestReportSinglePackage(MonoCase):
    def test_no_packages_table_for_single_package(self):
        write(self.root, "package.json", json.dumps({"name": "solo"}))
        write(self.root, "src/main.ts", "export const x = 1;\n")
        html = build_report(self.root)
        self.assertNotIn("<h2>Packages</h2>", html)


class TestSymlinkedPackageDir(MonoCase):
    def test_symlink_does_not_double_count(self):
        npm_fixture(self.root)
        link = self.root / "packages" / "link"
        try:
            link.symlink_to(self.root / "packages" / "a", target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        result = scan(self.root)
        paths = [f.path for f in result.files]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertFalse(any(p.startswith("packages/link") for p in paths))
        a_files = [p for p in paths if p.startswith("packages/a/")]
        self.assertEqual(len(a_files), 2)


class TestAuditRound1Fixes(MonoCase):
    """Regression pins for audits/G08_audit.md Audit #1 findings."""

    def test_f1_missing_and_warnings_are_visible(self):
        write(self.root, "package.json", json.dumps(
            {"name": "r", "workspaces": ["packages/*", "libs/ghost", "../out"]}))
        write(self.root, "packages/a/package.json", json.dumps({"name": "a"}))
        write(self.root, "packages/a/index.ts", "export const a = 1;\n")
        code, out, _ = run_cli(["scan", str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIn("libs/ghost", payload["workspace"]["missing"])
        self.assertTrue(payload["workspace"]["declared"])
        self.assertTrue(any("../out" in w
                            for w in payload["workspace"]["warnings"]))
        code, out, _ = run_cli(["scan", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("declared but missing on disk", out)
        self.assertIn("libs/ghost", out)
        self.assertIn("Workspace warnings:", out)

    def test_f2_pnpm_column_zero_items(self):
        write(self.root, "pnpm-workspace.yaml",
              "packages:\n"
              "- 'libs/*'\n"
              "onlyBuiltDependencies:\n"
              "  - esbuild\n")
        write(self.root, "libs/util/package.json", json.dumps({"name": "util"}))
        write(self.root, "libs/util/index.ts", "export const u = 1;\n")
        info, by_path = self.packages_by_path()
        self.assertIn("libs/util", by_path)

    def test_f3_cargo_exclude_cannot_remove_literal_member(self):
        write(self.root, "Cargo.toml",
              "[workspace]\n"
              'members = ["crates/*", "crates/skip"]\n'
              'exclude = ["crates/skip"]\n')
        for name in ("one", "skip"):
            write(self.root, f"crates/{name}/Cargo.toml",
                  f'[package]\nname = "{name}"\n')
            write(self.root, f"crates/{name}/src/lib.rs", "pub fn f() {}\n")
        info, by_path = self.packages_by_path()
        # skip is glob-matched AND excluded, but also listed
        # literally — Cargo keeps explicitly listed members.
        self.assertIn("crates/skip", by_path)
        self.assertIn("crates/one", by_path)

    def test_f4_go_work_only_root_evidence(self):
        write(self.root, "go.work", "go 1.21\n\nuse ./core\n")
        write(self.root, "core/go.mod", "module example.com/core\n")
        write(self.root, "core/core.go", "package core\n")
        info, by_path = self.packages_by_path()
        self.assertEqual(by_path[""].manifest, "go.work")
        self.assertIn("go.work", by_path[""].source)

    def test_f5_double_star_is_one_segment(self):
        write(self.root, "package.json", json.dumps(
            {"name": "r", "workspaces": ["libs/**"]}))
        write(self.root, "libs/foo/package.json", json.dumps({"name": "foo"}))
        write(self.root, "libs/foo/bar/package.json", json.dumps({"name": "bar"}))
        write(self.root, "libs/foo/bar/code.ts", "export const b = 1;\n")
        info, by_path = self.packages_by_path()
        self.assertIn("libs/foo", by_path)
        self.assertNotIn("libs/foo/bar", by_path)
        result = scan(self.root)
        got = {f.path: f.package for f in result.files}
        self.assertEqual(got["libs/foo/bar/code.ts"], "libs/foo")


class TestAuditRound2Fixes(MonoCase):
    """Regression pins for audits/G08_audit.md Audit #2 findings."""

    def test_g1_comment_inside_pnpm_list_does_not_end_it(self):
        write(self.root, "pnpm-workspace.yaml",
              "packages:\n"
              "  - 'libs/*'\n"
              "# a top-level comment between items\n"
              "\n"
              "  - 'apps/*'\n"
              "onlyBuiltDependencies:\n"
              "  - esbuild\n")
        write(self.root, "libs/util/package.json", json.dumps({"name": "util"}))
        write(self.root, "libs/util/index.ts", "export const u = 1;\n")
        write(self.root, "apps/web/package.json", json.dumps({"name": "web"}))
        write(self.root, "apps/web/index.ts", "export const w = 1;\n")
        info, by_path = self.packages_by_path()
        self.assertIn("libs/util", by_path)
        self.assertIn("apps/web", by_path)

    def test_g2_pnpm_flow_style_packages(self):
        write(self.root, "pnpm-workspace.yaml",
              "packages: ['libs/*', \"apps/*\"] # both trees\n")
        write(self.root, "libs/util/package.json", json.dumps({"name": "util"}))
        write(self.root, "libs/util/index.ts", "export const u = 1;\n")
        write(self.root, "apps/web/package.json", json.dumps({"name": "web"}))
        write(self.root, "apps/web/index.ts", "export const w = 1;\n")
        info, by_path = self.packages_by_path()
        self.assertIn("libs/util", by_path)
        self.assertIn("apps/web", by_path)
        self.assertEqual(by_path["libs/util"].kind, "declared")


class TestGhostBusUnchanged(unittest.TestCase):
    def test_ghostbus_totals_and_single_package(self):
        ghostbus = Path.home() / "workspace" / "ghostbus"
        if not ghostbus.is_dir():
            self.skipTest("GhostBus checkout not present")
        profile = load_profile(ghostbus)
        before, after = estimate_context_tokens(ghostbus, profile=profile)
        self.assertEqual((before, after), (129555, 45770))
        result = scan(ghostbus)
        self.assertTrue(all(f.package == "" for f in result.files))
        summary = summarize_packages(result)
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["files"], len(result.files))


if __name__ == "__main__":
    unittest.main()
