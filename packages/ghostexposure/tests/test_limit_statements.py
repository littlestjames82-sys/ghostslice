"""Verification bar #4 (PLAN.md): EXPOSURE.md and verify output both
contain (a) the coverage-limits statement and (b) the cannot-prove-
other-channels statement. Missing either fails the build.

The plan's own example wordings are:
  coverage:  it does not detect sensitive logic in files with no
             matching signals
  verify:    it cannot prove a sender did not share other files by
             another channel

Tests check for those ideas with the fragment sets in helpers.py, so a
core that phrases them slightly differently still passes, and a core
that omits them does not.
"""
from __future__ import annotations

from pathlib import Path

from conftest import FIXTURES, ROOT, copy_fixture
from helpers import (
    CANNOT_PROVE_FRAGMENTS,
    COVERAGE_FRAGMENTS,
    contains_limit_statement,
)


def _export(cli, project, pack, out):
    result = cli(["export", project, "--surface", pack, "-o", out])
    assert result.returncode == 0, f"export failed:\n{result.stdout}\n{result.stderr}"
    return out


def test_exposure_md_has_coverage_limits(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    md = (bundle / "EXPOSURE.md").read_text()
    assert contains_limit_statement(md, COVERAGE_FRAGMENTS), (
        "EXPOSURE.md must state what the surface pack does not cover"
    )


def test_exposure_md_has_cannot_prove_statement(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    md = (bundle / "EXPOSURE.md").read_text()
    assert contains_limit_statement(md, CANNOT_PROVE_FRAGMENTS), (
        "EXPOSURE.md must state that it cannot prove nothing else was shared another way"
    )


def test_verify_output_states_its_limit(cli, surface_pack, tmp_path):
    project = copy_fixture("basic_project", tmp_path)
    bundle = _export(cli, project, surface_pack, tmp_path / "bundle")
    result = cli(["verify", bundle])
    assert result.returncode == 0
    assert contains_limit_statement(result.stdout + result.stderr, CANNOT_PROVE_FRAGMENTS), (
        "verify proves the bundle matches its manifest, and must say that is all it proves"
    )


def test_sample_documents_carry_the_statements():
    """Docs/examples tests: no core needed, these must pass today."""
    sample = (ROOT / "examples" / "sample_EXPOSURE.md").read_text()
    assert contains_limit_statement(sample, COVERAGE_FRAGMENTS)
    assert contains_limit_statement(sample, CANNOT_PROVE_FRAGMENTS)
    readme = (ROOT / "README.md").read_text()
    assert contains_limit_statement(readme, CANNOT_PROVE_FRAGMENTS)
