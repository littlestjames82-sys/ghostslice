"""CLI contract tests from PLAN.md MVP items 1-4.

Assumptions recorded in REPORT_B.md: `ghostatlas build <project> -o
<atlas.html>` also produces ATLAS.md in the same run; the profile's
`atlas` section in `.ghostslice.json` fails loudly on unknown keys;
building never modifies the project's source files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from conftest import requires_core, run_atlas


@requires_core
def test_help_lists_build(tmp_path: Path):
    result = run_atlas(["--help"], cwd=tmp_path)
    assert result.returncode == 0
    assert "build" in result.stdout.lower()


@requires_core
def test_build_creates_html_and_brief(build, ground_truth: Path, truth: dict):
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    assert built.html_path.is_file()
    assert "<html" in built.html.lower()
    assert built.atlas_md, "ATLAS.md brief was not produced by the build run"
    # Brief-first honesty labels required by PLAN.md: estimates + static.
    brief = built.atlas_md.lower()
    assert "estimat" in brief
    assert truth["entry_point"] in built.atlas_md


@requires_core
def test_build_does_not_modify_project_sources(build, ground_truth: Path):
    def hashes() -> dict[str, str]:
        return {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ground_truth.glob("*.py"))
        }

    before = hashes()
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    assert hashes() == before


@requires_core
def test_unknown_atlas_profile_key_fails_loudly(build, ground_truth: Path):
    (ground_truth / ".ghostslice.json").write_text(
        json.dumps({"atlas": {"bogus_atlas_key_xyz": True}}), encoding="utf-8"
    )
    built = build(ground_truth)
    assert built.result.returncode != 0
    combined = (built.result.stdout + built.result.stderr).lower()
    assert "bogus_atlas_key_xyz" in combined or "unknown" in combined


@requires_core
def test_diligence_mode_states_limits(build, ground_truth: Path):
    built = build(ground_truth, extra_args=["--audience", "diligence"])
    assert built.result.returncode == 0, built.result.stderr
    brief = built.atlas_md.lower()
    assert "not checked" in brief or "not covered" in brief
    assert "not an audit" in brief or "not an opinion" in brief or "orientation" in brief
