"""C/C++ preprocessor include closure (DEEPEN improvement round).

Before this round, C and C++ files were labelled "not computed
in v0.1": a bundled .c file arrived with none of the headers it
includes. The quoted #include form is local by the language's
own rule, so it is now resolved statically: first against the
including file's directory, then against the project root
(modelling the project root as one include path). These
black-box tests pin the behaviour:

- a bundled main.c pulls its included headers in, transitively,
  with importers named, including a header found only through
  the project-root fallback;
- angle-bracket includes (system / include-path headers),
  unresolved quoted includes, and macro includes are recorded
  as external references, never resolved or copied;
- includes named only inside comments or a string literal pull
  nothing in and record nothing;
- an include path that climbs out of the project root never
  reaches the file outside it;
- the hard rules still govern the new candidates: a flagged
  header reached only through closure is excluded by default
  (path + pattern type only, no value anywhere in the output),
  and --include-flagged includes it with the flag on record.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import helpers

pytestmark = pytest.mark.usefixtures("requires_cli")

C_PROJECT = helpers.FIXTURES / "c_project"
SEED = [("src/main.c", "full")]


@pytest.fixture()
def c_project(tmp_path):
    dest = tmp_path / "c_project"
    shutil.copytree(C_PROJECT, dest)
    return dest


@pytest.fixture()
def c_bundle(c_project, tmp_path):
    return helpers.build_bundle(c_project, tmp_path / "c_bundle", SEED)


def _included(manifest):
    return {e["path"]: e for e in manifest["included"]}


def test_c_closure_pulls_headers_transitively(c_project, c_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(c_project, c_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    inc = _included(helpers.fixture_manifest(out))
    assert inc["src/main.c"]["reason"] == "bundle-referenced"
    app = inc["src/app.h"]
    assert app["reason"] == "import-closure"
    assert app["via"] == "src/main.c"
    util = inc["src/util/util.h"]
    assert util["reason"] == "import-closure"
    assert util["via"] == "src/app.h"
    # src/defs.h is not beside util.h: it is found only through
    # the project-root fallback for #include "src/defs.h".
    defs = inc["src/defs.h"]
    assert defs["reason"] == "import-closure"
    assert defs["via"] == "src/util/util.h"
    assert (out / "src/util/util.h").read_bytes() == \
        (c_project / "src/util/util.h").read_bytes()
    assert (out / "src/defs.h").is_file()


def test_c_external_comment_and_unreferenced_rules(c_project, c_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(c_project, c_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    specs = {(e["from"], e["specifier"]) for e in manifest["external_references"]}
    # Angle-bracket headers stay external, even stdint.h named
    # from a closure header.
    assert ("src/main.c", "stdio.h") in specs
    assert ("src/util/util.h", "stdint.h") in specs
    # An unresolved quoted include and a macro include are
    # recorded as external references, not errors and not copies.
    assert ("src/main.c", "no_such.h") in specs
    assert ("src/main.c", "PLUGIN_HEADER") in specs
    # ghost.h is named only in a // comment, a /* */ comment, and
    # a string literal: it is neither copied nor recorded.
    assert "ghost.h" not in {spec for _, spec in specs}
    on_disk = {p.relative_to(out).as_posix() for p in helpers.output_files(out)}
    assert "src/ghost.h" not in on_disk
    assert "src/impl.c" not in on_disk
    assert "stray.h" not in on_disk


def test_c_closure_note_and_check_roundtrip(c_project, c_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(c_project, c_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    note = manifest["closure_by_language"]["c/c++"]
    assert note.startswith("computed"), note
    proc = helpers.check_fixture(out)
    assert proc.returncode == 0, helpers.combined(proc)


def test_c_flagged_header_excluded_by_default(c_project, c_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(c_project, c_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    flagged = {e["path"]: e for e in manifest["excluded_flagged"]}
    entry = flagged["src/api_keys.h"]
    assert "stripe-key" in entry["types"]
    assert not entry.get("included_by_override")
    assert "src/api_keys.h" not in _included(manifest)
    assert not (out / "src/api_keys.h").exists()
    # The flag record names path and pattern types only: the
    # planted value appears nowhere in the output tree.
    assert helpers.CANARY.encode() not in helpers.all_output_bytes(out)


def test_c_flagged_header_include_flagged_override(c_project, c_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(c_project, c_bundle, out,
                                 extra=("--include-flagged",))
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    assert "src/api_keys.h" in _included(manifest)
    flagged = {e["path"]: e for e in manifest["excluded_flagged"]}
    assert flagged["src/api_keys.h"].get("included_by_override") is True
    assert (out / "src/api_keys.h").is_file()


def test_c_include_escaping_root_never_reaches_outside(c_project, tmp_path):
    outside = tmp_path / "outside.h"
    outside.write_text("#pragma once\n#define OUTSIDE 1\n", encoding="utf-8")
    esc = c_project / "src" / "esc.c"
    esc.write_text('#include "../outside.h"\nint esc(void);\n',
                   encoding="utf-8")
    bundle = helpers.build_bundle(c_project, tmp_path / "c_bundle",
                                  [("src/esc.c", "full")])
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(c_project, bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)
    manifest = helpers.fixture_manifest(out)
    assert "outside.h" not in _included(manifest)
    on_disk = {p.relative_to(out).as_posix() for p in helpers.output_files(out)}
    assert "outside.h" not in on_disk
    specs = {e["specifier"] for e in manifest["external_references"]}
    assert "../outside.h" in specs
