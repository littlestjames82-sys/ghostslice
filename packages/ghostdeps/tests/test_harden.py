"""Hardening regression tests (improvement wave, harden lane).

Each test pins a bug found by probing malformed or unusual local
input: wrong-typed manifest fields crashed discovery with a
traceback or were iterated into bogus one-character declarations,
BOM-marked files silently lost their contents, a bare VCS line in
requirements.txt became a package named "git", Rust block comments
manufactured imports, wildcard specs were recorded as exact pins,
malformed JS scoped specifiers became packages, and a dependency
whose name contains a banned-wording substring made rendering raise.
The hard rules are unchanged: evidence only, no network, versions as
recorded.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from conftest import combined, needs_cli, run_ghostdeps, run_pack  # noqa: E402
from helpers import banned_hits  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _manifest(found) -> dict:
    assert found is not None, "pack produced no DEPS.md + deps-manifest.json"
    return json.loads(found[1].read_text())


def _names(entries) -> set[str]:
    return {entry["name"] for entry in entries}


# ------------------------------------------------------- manifest shapes

@needs_cli
def test_package_json_wrong_top_level_shape_is_error_not_crash(tmp_path):
    project = tmp_path / "badjson"
    _write(project / "package.json", "[]")
    _write(project / "index.js", "const x = 1;\n")

    doc = run_ghostdeps(["doctor", str(project)])
    assert "traceback" not in combined(doc).lower()
    # No manifest parsed -> the documented exit 2, not a crash.
    assert doc.returncode == 2, combined(doc)

    proc, _found = run_pack(project, tmp_path / "out")
    assert "traceback" not in combined(proc).lower()
    assert proc.returncode == 2, combined(proc)


@needs_cli
def test_one_bad_manifest_does_not_hide_the_rest(tmp_path):
    project = tmp_path / "mixed"
    _write(project / "package.json", '"just a string"')
    _write(project / "pyproject.toml",
           '[project]\nname = "mixed"\ndependencies = ["requests>=2"]\n')
    _write(project / "main.py", "import requests\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)
    statuses = {s["file"]: s["status"] for s in data["sources"]}
    assert statuses["package.json"] == "error"
    assert statuses["pyproject.toml"] == "parsed"
    assert _names(data["sections"]["declared_and_used"]) == {"requests"}


@needs_cli
def test_pyproject_wrong_typed_fields_spawn_no_character_declarations(
        tmp_path):
    project = tmp_path / "badtypes"
    _write(project / "pyproject.toml", """\
[build-system]
requires = "setuptools"

[project]
name = "badtypes"
dependencies = ["requests>=2", 123, true]

[project.optional-dependencies]
test = "pytest"

[dependency-groups]
dev = "pytest"
""")
    _write(project / "main.py", "import requests\nimport pytest\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert "traceback" not in combined(proc).lower()
    assert proc.returncode == 1, combined(proc)  # pytest is undeclared
    data = _manifest(found)
    # Only the genuine string entry survives. The string fields are
    # not lists, the numeric/bool entries are not requirements, and
    # nothing was iterated character by character.
    assert _names(data["sections"]["declared_and_used"]) == {"requests"}
    assert data["sections"]["declared_not_imported"] == []
    assert _names(data["sections"]["imported_not_declared"]) == {"pytest"}
    assert data["build_requirements"] == []
    assert data["counts"]["declared"] == 1


@needs_cli
def test_cargo_wrong_typed_tables_do_not_crash(tmp_path):
    project = tmp_path / "badcargo"
    _write(project / "Cargo.toml", """\
package = "oops"
target = "oops"

[dependencies]
serde = "1"
""")
    _write(project / "main.rs", "use serde;\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert "traceback" not in combined(proc).lower()
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)
    assert _names(data["sections"]["declared_and_used"]) == {"serde"}


@needs_cli
def test_lockfile_root_string_section_does_not_fabricate_direct_pins(
        tmp_path):
    project = tmp_path / "badlock"
    _write(project / "package.json", json.dumps(
        {"name": "badlock", "dependencies": {"express": "1.0.0"}}))
    _write(project / "package-lock.json", json.dumps({
        "name": "badlock", "lockfileVersion": 3,
        "packages": {
            # Malformed: a bare string where a name->spec map belongs.
            # Iterating it used to yield the character "e" as a direct
            # name, promoting the one-letter package below to direct.
            "": {"dependencies": "e"},
            "node_modules/e": {"version": "1.0.0"},
            "node_modules/express": {"version": "1.0.0"},
        },
    }))
    _write(project / "index.js", "const e = require('express');\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)
    # The only direct pin is express's bare spec in package.json
    # itself; no lockfile pin is direct, because the root entry's
    # dependency section is a malformed string, not a name map.
    lock_direct = [p for p in data["sections"]["pins"]
                   if p["source"] == "package-lock.json"]
    assert lock_direct == []
    transitive = data["sections"]["transitive_pins"]
    assert len(transitive) == 1
    assert "e=1.0.0" in transitive[0]["pins"]
    assert "express=1.0.0" in transitive[0]["pins"]


@needs_cli
def test_js_null_spec_is_not_recorded_as_python_none(tmp_path):
    project = tmp_path / "nullspec"
    _write(project / "package.json", json.dumps(
        {"dependencies": {"express": None}}))
    _write(project / "index.js", "const e = require('express');\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)
    used = data["sections"]["declared_and_used"]
    assert _names(used) == {"express"}
    # No spec was recorded in the file, so no spec may be reported;
    # in particular the Python repr "None" is not local evidence.
    assert used[0]["specs"] == []
    assert "None" not in found[0].read_text()


# ------------------------------------------------------------------ BOM

@needs_cli
def test_bom_marked_python_files_still_parse(tmp_path):
    project = tmp_path / "bompy"
    (project).mkdir(parents=True, exist_ok=True)
    (project / "pyproject.toml").write_bytes(
        b'\xef\xbb\xbf[project]\nname = "bompy"\n'
        b'dependencies = ["requests"]\n')
    (project / "requirements.txt").write_bytes(
        b"\xef\xbb\xbfrequests==2.31.0\n")
    (project / "main.py").write_bytes(b"\xef\xbb\xbfimport requests\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)
    assert _names(data["sections"]["declared_and_used"]) == {"requests"}
    assert data["python_parse_failures"] == []
    assert "2.31.0" in found[0].read_text()


@needs_cli
def test_bom_marked_package_json_still_parses(tmp_path):
    project = tmp_path / "bomnode"
    (project).mkdir(parents=True, exist_ok=True)
    (project / "package.json").write_bytes(
        b'\xef\xbb\xbf{"dependencies": {"express": "4.18.2"}}')
    _write(project / "index.js", "const e = require('express');\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)
    assert _names(data["sections"]["declared_and_used"]) == {"express"}


# ----------------------------------------------------------- requirements

@needs_cli
def test_requirements_vcs_lines_and_equals_includes(tmp_path):
    project = tmp_path / "reqedge"
    _write(project / "requirements.txt", """\
-r=base.txt
--requirement=other.txt
git+https://example.com/repo.git
requests==2.0
""")
    _write(project / "main.py", "import requests\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)
    declared = _names(data["sections"]["declared_and_used"]) | \
        _names(data["sections"]["declared_not_imported"])
    # The bare VCS line is not a declaration of a package named "git".
    assert declared == {"requests"}
    note = next(s["note"] for s in data["sources"]
                if s["file"] == "requirements.txt")
    assert "base.txt" in note and "other.txt" in note
    assert "not in requirement shape" in note


def test_parse_pep508_rejects_vcs_shaped_text():
    from ghostdeps.manifests import parse_pep508

    assert parse_pep508("git+https://example.com/r.git") is None
    assert parse_pep508("https://example.com/pkg.tar.gz") is None
    assert parse_pep508("requests>=2") == ("requests", ">=2")
    assert parse_pep508("Pillow[all]>=10") == ("Pillow", ">=10")
    name, _spec = parse_pep508("name @ https://example.com/p.tar.gz")
    assert name == "name"


# ------------------------------------------------------------------ Rust

@needs_cli
def test_rust_block_commented_crates_are_not_imports(tmp_path):
    project = tmp_path / "rustcomments"
    _write(project / "Cargo.toml",
           '[package]\nname = "rustcomments"\n\n'
           '[dependencies]\nserde = "1"\n')
    _write(project / "main.rs", """\
/*
use phantomcrate;
*/
/* outer /* inner */ use alsophantom; */
use serde;
// use linephantom;
""")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)
    assert _names(data["sections"]["declared_and_used"]) == {"serde"}
    assert data["sections"]["imported_not_declared"] == []


# -------------------------------------------------------------------- JS

@needs_cli
def test_malformed_scoped_specifiers_are_not_packages(tmp_path):
    project = tmp_path / "scopes"
    _write(project / "package.json", json.dumps({"dependencies": {}}))
    _write(project / "index.js", """\
import x from '@/pkg';
import y from '@scope';
import z from '@scope/';
import w from '@scope/real';
import fsA from 'node:fs';
import fsB from 'fs';
""")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)
    data = _manifest(found)
    assert _names(data["sections"]["imported_not_declared"]) == \
        {"@scope/real"}
    # node:fs and fs are the same builtin, recorded once.
    fs_entries = [e for e in data["stdlib_imports"]
                  if e["module"] == "fs"]
    assert len(fs_entries) == 1
    assert fs_entries[0]["files"] == ["index.js"]


def test_js_package_name_rejects_malformed_scopes():
    from ghostdeps.names import js_package_name

    assert js_package_name("@scope") is None
    assert js_package_name("@scope/") is None
    assert js_package_name("@/pkg") is None
    assert js_package_name("@scope/pkg/sub") == "@scope/pkg"
    assert js_package_name("node:fs") == "fs"
    assert js_package_name("lodash/fp") == "lodash"


# ------------------------------------------------------------------- pins

@needs_cli
def test_wildcard_specs_are_not_recorded_as_exact_pins(tmp_path):
    project = tmp_path / "wildcards"
    _write(project / "requirements.txt",
           "widget==1.2.*\ngadget==1.2.3\nthing==1.2.x\n")
    _write(project / "main.py",
           "import widget\nimport gadget\nimport thing\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)
    pins = {p["name"]: p["version"] for p in data["sections"]["pins"]}
    assert pins == {"gadget": "1.2.3"}
    # The wildcard packages are still declared and used; only the
    # claim that they are exact pins is gone.
    assert _names(data["sections"]["declared_and_used"]) == \
        {"widget", "gadget", "thing"}


# ------------------------------------------------------- wording guard

@needs_cli
def test_dependency_name_with_banned_substring_still_packs(tmp_path):
    project = tmp_path / "namesake"
    _write(project / "pyproject.toml",
           '[project]\nname = "namesake"\n'
           'dependencies = ["outdated-thing==1.0.0"]\n')
    _write(project / "main.py", "import os\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    assert "outdated-thing" in found[0].read_text()

    # Same for a project checked out under a directory whose path
    # itself contains the substring: the path is evidence (the
    # pack's Project line), not tool wording.
    nested = tmp_path / "vulnerable-app"
    _write(nested / "pyproject.toml",
           '[project]\nname = "nested"\ndependencies = ["requests"]\n')
    _write(nested / "main.py", "import requests\n")
    proc2, found2 = run_pack(nested, tmp_path / "out2")
    assert proc2.returncode == 0, combined(proc2)
    assert found2 is not None


@needs_cli
def test_banned_guard_still_fires_on_tool_prose(tmp_path):
    project = tmp_path / "guard"
    _write(project / "pyproject.toml",
           '[project]\nname = "guard"\ndependencies = ["requests"]\n')
    _write(project / "main.py", "import requests\n")
    _proc, found = run_pack(project, tmp_path / "out")
    pack = _manifest(found)

    from ghostdeps.xref import render_deps_md

    pack["notes"] = ["This dependency is outdated and safe to remove."]
    try:
        render_deps_md(pack)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "banned wording in the tool's own notes did not raise")


# ------------------------------------------------------------- robustness

@needs_cli
def test_pack_output_path_that_is_a_file_returns_2_not_traceback(
        tmp_path):
    project = tmp_path / "proj"
    _write(project / "pyproject.toml",
           '[project]\nname = "proj"\ndependencies = ["requests"]\n')
    _write(project / "main.py", "import requests\n")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")

    proc = run_ghostdeps(["pack", str(project), "-o", str(blocker)])
    assert proc.returncode == 2, combined(proc)
    assert "traceback" not in combined(proc).lower()


@needs_cli
def test_ghostslice_profile_wrong_shape_warns_and_scan_continues(
        tmp_path):
    project = tmp_path / "badprofile2"
    _write(project / "package.json", json.dumps({"dependencies": {}}))
    _write(project / ".ghostslice.json", '["ignore-me"]')
    _write(project / "index.js", "const a = require('axios');\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)
    data = _manifest(found)
    assert data["import_scan"]["warnings"]
    assert ".ghostslice.json" in data["import_scan"]["warnings"][0]
    assert _names(data["sections"]["imported_not_declared"]) == {"axios"}
    assert banned_hits(found[0].read_text(), found[1].read_text()) == []


def test_python_scan_missing_file_is_parse_failure_not_crash(tmp_path):
    from ghostdeps.imports_scan import ImportIndex, _scan_python

    idx = ImportIndex()
    _scan_python(idx, tmp_path / "gone.py", "gone.py", set(), set())
    assert idx.parse_failures == ["gone.py"]
