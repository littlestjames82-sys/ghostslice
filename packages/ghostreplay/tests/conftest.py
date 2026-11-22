"""Shared helpers for the GhostReplay contract test suite (Agent B).

These tests encode the PLAN.md verification bar as a CLI contract.
Assumed core interface (Agent A; assumptions recorded in REPORT_B.md):

    ghostreplay ingest  <project> <transcript>
    ghostreplay analyse <project> <transcript> --bundle <bundle-dir> --out <dir>
                        -> writes <dir>/REPLAY.md and <dir>/replay-report.json,
                           and appends <project>/.ghostreplay-history.jsonl
    ghostreplay propose <project> <session...> --bundle <bundle-dir> --out <dir>
                        -> writes <dir>/ghostreplay-proposal.json + PROPOSAL.md
                           ({"changes": [ {kind, target, current, proposed,
                                            evidence, sessions_present,
                                            sessions_referenced} ]})
    ghostreplay apply   <project> --proposal <ghostreplay-proposal.json>
                        (interactive explicit yes; .ghostslice.json.bak backup)
    ghostreplay trend   <project>

(Interface verified against the landed core, Oct 14 2026. Tests always
run against a COPY of the fixture project, because analyse/ingest write
a ledger / canonical session into the project dir.)

CLI discovery order: $GHOSTREPLAY_BIN, `ghostreplay` on PATH, then
`python -m ghostreplay` with PYTHONPATH=<repo>/src. If no core is found,
the CLI-dependent tests FAIL (not skip): a green suite must mean a core
actually satisfied the contract. Fixture-integrity tests in
test_fixtures.py are pure and pass without a core.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROJECT = FIXTURES / "project"
BUNDLE = FIXTURES / "bundle"
SESSIONS = FIXTURES / "sessions"

# The planted secret-shaped string (AWS documentation example key shape).
# It appears ONLY in the secret_* fixture inputs. It must appear in zero
# files any GhostReplay command produces.
PLANTED_SECRET = "AKIAIOSFODNN7EXAMPLE"

HOT = "src/hot.py"          # re-read exactly 5x in every planted-waste session
NEVER = "src/legacy.py"     # in the bundle, never referenced in planted waste


def manifest():
    return json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))


def manifest_entry(path):
    for entry in manifest()["files"]:
        if entry["path"] == path:
            return entry
    raise AssertionError(f"{path} missing from fixture manifest")


def cli_available():
    if os.environ.get("GHOSTREPLAY_BIN"):
        return True
    if shutil.which("ghostreplay"):
        return True
    return (REPO / "src" / "ghostreplay").is_dir()


def run_cli(args, cwd=None, stdin_text=None, timeout=120):
    """Run the GhostReplay CLI; return CompletedProcess (text mode)."""
    env = dict(os.environ)
    if os.environ.get("GHOSTREPLAY_BIN"):
        cmd = [os.environ["GHOSTREPLAY_BIN"]]
    elif shutil.which("ghostreplay"):
        cmd = ["ghostreplay"]
    else:
        cmd = [sys.executable, "-m", "ghostreplay"]
        env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        cmd + [str(a) for a in args],
        cwd=str(cwd) if cwd else None,
        env=env,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture()
def require_core():
    if not cli_available():
        pytest.fail(
            "GhostReplay core not found (no $GHOSTREPLAY_BIN, no ghostreplay "
            "on PATH, no src/ghostreplay package). Contract tests cannot "
            "pass without a core; this is a failure, not a skip."
        )


def make_project_copy(tmp_path):
    """Copy the fixture project into tmp (core writes ledger files into
    the project dir; the shared fixture must stay pristine)."""
    import shutil as _shutil
    dest = Path(tmp_path) / "project"
    _shutil.copytree(PROJECT, dest)
    return dest


@pytest.fixture()
def project_copy(tmp_path):
    return make_project_copy(tmp_path)


@pytest.fixture()
def analyse_planted(tmp_path, require_core, project_copy):
    """Run analyse on planted_waste_1 into a fresh out dir; return out dir."""
    out = tmp_path / "out"
    res = run_cli(
        ["analyse", project_copy, SESSIONS / "planted_waste_1.jsonl",
         "--bundle", BUNDLE, "--out", out],
        cwd=tmp_path,
    )
    assert res.returncode == 0, f"analyse failed: {res.stdout}\n{res.stderr}"
    return out


def load_report(out_dir):
    report = Path(out_dir) / "replay-report.json"
    assert report.is_file(), f"replay-report.json not written to {out_dir}"
    return json.loads(report.read_text(encoding="utf-8"))


def find_entries(report, *key_names):
    """Return the first list value in the report whose key matches, else []."""
    for key in key_names:
        val = report.get(key)
        if isinstance(val, list):
            return val
    return []


def entry_mentions(entry, needle):
    return needle in json.dumps(entry)
