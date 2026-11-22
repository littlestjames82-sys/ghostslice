"""CLI surface + safety contract tests.

- --help lists the five PLAN commands: ingest, analyse, propose, apply,
  trend;
- an unrecognised transcript shape fails LOUDLY (non-zero exit, error
  names the problem) instead of being analysed badly;
- ingest registers a local transcript (exit 0);
- apply is propose-only's other half: with no explicit terminal "yes"
  it must leave .ghostslice.json byte-identical.
"""
import hashlib
import json
import shutil
from pathlib import Path

from conftest import BUNDLE, SESSIONS, run_cli
from conftest import PROJECT as FIXTURE_PROJECT

COMMANDS = ["ingest", "analyse", "propose", "apply", "trend"]


def test_help_lists_all_plan_commands(require_core):
    res = run_cli(["--help"])
    assert res.returncode == 0, res.stderr
    text = (res.stdout + res.stderr).lower()
    for cmd in COMMANDS:
        assert cmd in text, f"--help does not list `{cmd}`"


def test_unrecognised_transcript_shape_fails_loudly(tmp_path, require_core, project_copy):
    res = run_cli(
        ["analyse", project_copy, SESSIONS / "not_a_transcript.jsonl",
         "--bundle", BUNDLE, "--out", tmp_path / "out"],
        cwd=tmp_path,
    )
    assert res.returncode != 0, (
        "a garbage transcript was accepted; output: " + res.stdout
    )
    blob = (res.stdout + res.stderr).lower()
    assert any(word in blob for word in
               ("unrecognis", "unrecogniz", "unsupported", "invalid",
                "not a", "format")), (
        f"failure did not name the format problem: {res.stdout} {res.stderr}"
    )


def test_ingest_registers_a_transcript(tmp_path, require_core, project_copy):
    res = run_cli(["ingest", project_copy, SESSIONS / "planted_waste_1.jsonl"],
                  cwd=tmp_path)
    assert res.returncode == 0, f"ingest failed: {res.stdout}\n{res.stderr}"


def test_apply_without_yes_changes_nothing(tmp_path, require_core):
    project = tmp_path / "proj"
    shutil.copytree(FIXTURE_PROJECT, project)
    profile = {"budget_tokens": 5000, "modes": {"src/**": "full"}}
    profile_path = project / ".ghostslice.json"
    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    before = hashlib.sha256(profile_path.read_bytes()).hexdigest()

    # A proposal file to apply, in the core's proposal format
    # (ghostreplay-proposal/1, status ready, kind/target/proposed changes).
    proposal = tmp_path / "ghostreplay-proposal.json"
    proposal.write_text(json.dumps({
        "format": "ghostreplay-proposal/1", "status": "ready",
        "sessions_analysed": 3,
        "changes": [
            {"kind": "mode", "target": "src/legacy.py",
             "current": "full", "proposed": "exclude",
             "evidence": "present in 3 bundle(s), referenced in 0/3 "
                         "of those sessions"},
        ]}), encoding="utf-8")

    res = run_cli(["apply", project, "--proposal", proposal],
                  cwd=tmp_path, stdin_text="no\n")
    after = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    assert after == before, (
        "apply modified .ghostslice.json without an explicit yes "
        f"(exit {res.returncode}): {res.stdout} {res.stderr}"
    )
