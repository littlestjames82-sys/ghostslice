"""Lint safety tests (PLAN.md: pack format + validation, Verification bar).

A pack is data only. Any executable or script file in the pack folder
must fail lint, so must an absolute path smuggled into the profile
fragment, and so must a manifest whose kind is not "context" (packs in
this family must never be mistaken for policy packs).
"""
from __future__ import annotations

import os
import stat

import pytest

from conftest import combined, lint


def test_valid_data_only_pack_passes_lint(pack_factory):
    pack = pack_factory()
    proc = lint(pack)
    assert proc.returncode == 0, combined(proc)


@pytest.mark.parametrize("filename,content", [
    ("evil.py", "import os\nos.system('echo pwned')\n"),
    ("run.sh", "#!/bin/sh\necho pwned\n"),
    ("helper.js", "console.log('pwned');\n"),
])
def test_pack_with_script_file_fails_lint(pack_factory, filename, content):
    pack = pack_factory(extra_files={filename: content})
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, f"lint accepted a pack containing {filename}"
    assert filename in out, f"lint output should name the offending file:\n{out}"


def test_pack_with_executable_bit_fails_lint(pack_factory):
    pack = pack_factory(extra_files={"notes.txt": "perfectly innocent text\n"})
    target = pack / "notes.txt"
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    assert os.access(target, os.X_OK)
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, "lint accepted a pack containing an executable file"
    assert "notes.txt" in out, f"lint output should name the file:\n{out}"


def test_pack_with_nested_script_file_fails_lint(pack_factory):
    pack = pack_factory(extra_files={"scripts/deep/run.py": "print('pwned')\n"})
    proc = lint(pack)
    assert proc.returncode != 0, "lint accepted a script file nested in the pack"
    assert "run.py" in combined(proc)


def test_pack_fragment_with_absolute_path_fails_lint(pack_factory):
    pack = pack_factory(fragment={
        "ignore": ["/home/someone/private/**"],
        "modes": {},
    })
    proc = lint(pack)
    out = combined(proc)
    assert proc.returncode != 0, "lint accepted an absolute path in the fragment"
    assert "/home/someone/private" in out or "absolute" in out.lower(), out


def test_pack_with_wrong_kind_fails_lint(pack_factory):
    pack = pack_factory(manifest_overrides={"kind": "policy"})
    proc = lint(pack)
    out = combined(proc).lower()
    assert proc.returncode != 0, "lint accepted a pack whose kind is not 'context'"
    assert "kind" in out or "context" in out, out


def test_pack_missing_manifest_fails_lint(tmp_path):
    pack = tmp_path / "bare-pack"
    pack.mkdir()
    (pack / "profile.json").write_text("{}\n")
    proc = lint(pack)
    assert proc.returncode != 0, "lint accepted a pack with no pack.json manifest"
