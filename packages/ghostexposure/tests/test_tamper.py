"""Verification bar #2 (PLAN.md): adding one file to an exported bundle,
or removing one surface file, makes `verify` fail and NAME the
discrepancy."""
from __future__ import annotations

import shutil
from pathlib import Path

from conftest import copy_fixture
from helpers import bundle_payload_files


def _export(cli, project, pack, out):
    result = cli(["export", project, "--surface", pack, "-o", out])
    assert result.returncode == 0, f"export failed:\n{result.stdout}\n{result.stderr}"
    return out


def _verify(cli, bundle):
    return cli(["verify", bundle])


def test_clean_bundle_verifies(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    result = _verify(cli, bundle)
    assert result.returncode == 0, (
        f"an untampered bundle must verify:\n{result.stdout}\n{result.stderr}"
    )


def test_added_file_fails_verify_and_is_named(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    tampered = tmp_path / "tampered-add"
    shutil.copytree(bundle, tampered)

    files_dir = tampered / "files"
    base = files_dir if files_dir.is_dir() else tampered
    (base / "added_extra.py").write_text("# not in the manifest\n")

    result = _verify(cli, tampered)
    assert result.returncode != 0, "verify passed a bundle with an unlisted extra file"
    assert "added_extra.py" in (result.stdout + result.stderr), (
        "verify must name the discrepancy, not just fail"
    )


def test_removed_surface_file_fails_verify_and_is_named(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    tampered = tmp_path / "tampered-remove"
    shutil.copytree(bundle, tampered)

    victims = [p for p in tampered.rglob("login.py") if p.is_file()]
    assert victims, "fixture bundle should contain auth/login.py"
    victims[0].unlink()

    result = _verify(cli, tampered)
    assert result.returncode != 0, "verify passed a bundle missing a surface file"
    assert "login.py" in (result.stdout + result.stderr), (
        "verify must name the missing file"
    )
