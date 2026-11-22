"""Go import closure (polish round, Oct 14, 2026).

v0.1 shipped closure for Python and JS/TS only; Go was labelled
"not computed". Go is resolvable exactly in module mode: the
``module`` directive in go.mod makes a module-local import path
name one package directory, so the closure is that directory's
non-test .go files. These black-box tests pin that behaviour:

- a bundled main.go pulls its imported packages in, transitively,
  with importers named;
- stdlib imports stay external references;
- a directory with its own go.mod is a nested module: imports of
  it by main-module path do NOT resolve into it;
- *_test.go files and unreferenced packages stay out;
- without go.mod there is no module context and no local
  resolution is attempted.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import helpers

pytestmark = pytest.mark.usefixtures("requires_cli")

GO_PROJECT = helpers.FIXTURES / "go_project"
SEED = [("cmd/server/main.go", "full")]


@pytest.fixture()
def go_project(tmp_path):
    dest = tmp_path / "go_project"
    shutil.copytree(GO_PROJECT, dest)
    return dest


@pytest.fixture()
def go_bundle(go_project, tmp_path):
    return helpers.build_bundle(go_project, tmp_path / "go_bundle", SEED)


def _included(manifest):
    return {e["path"]: e for e in manifest["included"]}


def test_go_closure_pulls_package_files_transitively(go_project, go_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(go_project, go_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    inc = _included(helpers.fixture_manifest(out))
    assert inc["cmd/server/main.go"]["reason"] == "bundle-referenced"
    util = inc["internal/util/util.go"]
    assert util["reason"] == "import-closure"
    assert util["via"] == "cmd/server/main.go"
    shared = inc["internal/shared/shared.go"]
    assert shared["reason"] == "import-closure"
    assert shared["via"] == "internal/util/util.go"
    assert (out / "internal/util/util.go").read_bytes() == \
        (go_project / "internal/util/util.go").read_bytes()
    assert (out / "internal/shared/shared.go").is_file()


def test_go_external_nested_and_test_file_rules(go_project, go_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(go_project, go_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    specs = {(e["from"], e["specifier"]) for e in manifest["external_references"]}
    # stdlib is external, and so is the nested module (it carries
    # its own go.mod, so the main module path must not resolve).
    assert ("cmd/server/main.go", "fmt") in specs
    assert ("cmd/server/main.go", "example.com/fixtureapp/internal/nested") in specs
    on_disk = {p.relative_to(out).as_posix() for p in helpers.output_files(out)}
    assert "internal/nested/nested.go" not in on_disk
    assert "internal/util/util_test.go" not in on_disk
    assert "stray/stray.go" not in on_disk
    assert "go.mod" not in on_disk


def test_go_closure_note_and_check_roundtrip(go_project, go_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(go_project, go_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    note = manifest["closure_by_language"]["go"]
    assert note.startswith("computed"), note
    proc = helpers.check_fixture(out)
    assert proc.returncode == 0, helpers.combined(proc)


def test_go_without_gomod_no_local_resolution(go_project, tmp_path):
    (go_project / "go.mod").unlink()
    bundle = helpers.build_bundle(go_project, tmp_path / "go_bundle", SEED)
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(go_project, bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    inc = _included(manifest)
    assert "internal/util/util.go" not in inc
    assert "internal/shared/shared.go" not in inc
    specs = {e["specifier"] for e in manifest["external_references"]}
    assert "example.com/fixtureapp/internal/util" in specs
