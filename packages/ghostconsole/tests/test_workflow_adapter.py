"""GhostWorkflow adapter tests: .ghostworkflow/<run-id> discovery.

Shapes mirror ghostworkflow's writer (report.py / evidence.py and
schemas/workflow-report.schema.json): top-level verdict from
("ok", "attention", "failed"), verification_level from the evidence
contract enum, tool_version, timestamp, tree_hash (or null), and a
per-step list with name/status. The run directory also holds the
board.html the run rendered, which is the row's artifact.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from conftest import fixture_iso, combined, run_cli, verify_report, write_json

AT = fixture_iso(10).replace("+00:00", "Z")
TREE = "sha256:" + "ab" * 32
RUN = "wf-20261014T081000Z-abc123"


def _board(cli, project: Path) -> dict:
    proc = run_cli(cli, ["summary", project, "--json"])
    assert proc.returncode == 0, combined(proc)
    return json.loads(proc.stdout)["projects"][0]


def _section(board: dict, tool: str = "GhostWorkflow") -> dict:
    for section in board["sections"]:
        if section["tool"] == tool:
            return section
    raise AssertionError(f"no {tool} section in {board['sections']}")


def _workflow_report(project: Path, run_id: str = RUN, verdict="ok",
                     level="tests-executed", tree_hash=TREE,
                     timestamp=AT, board: bool = True, **fields) -> Path:
    """One contract-shaped workflow run under .ghostworkflow/."""
    report = {
        "project": {"name": project.name, "path": str(project)},
        "task": "fixture task",
        "commit": None,
        "tree_hash": tree_hash,
        "tree_hash_source": "fixture",
        "tool": "ghostworkflow",
        "tool_version": "0.1.0",
        "engines": {
            "ghostslice": {"found": True, "version": "1.0.6",
                           "how": "checkout", "home": "/x"},
            "ghostverify": {"found": True, "version": "0.1.0",
                            "how": "checkout", "home": "/x"},
            "ghostbench": {"found": True, "version": "0.1.0",
                           "how": "checkout", "home": "/x"},
            "ghostconsole": {"found": True, "version": "0.1.0",
                             "how": "checkout", "home": "/x"},
        },
        "timestamp": timestamp,
        "run_id": run_id,
        "verdict": verdict,
        "verification_level": level,
        "provenance": "live",
        "steps": [
            {"name": "slice", "status": "ok", "argv": [],
             "exit_code": 0, "started_utc": timestamp,
             "finished_utc": timestamp, "duration_s": 0.1,
             "reports": [], "verdict": "exported",
             "verification_level": "static-analysis", "detail": ""},
            {"name": "verify", "status": "attention", "argv": [],
             "exit_code": 1, "started_utc": timestamp,
             "finished_utc": timestamp, "duration_s": 0.1,
             "reports": [], "verdict": "gaps_found",
             "verification_level": "static-analysis", "detail": ""},
            {"name": "bench", "status": "ok", "argv": [],
             "exit_code": 0, "started_utc": timestamp,
             "finished_utc": timestamp, "duration_s": 0.1,
             "reports": [], "verdict": "tasks_passed",
             "verification_level": "tests-executed", "detail": ""},
            {"name": "console", "status": "ok", "argv": [],
             "exit_code": 0, "started_utc": timestamp,
             "finished_utc": timestamp, "duration_s": 0.1,
             "reports": [], "verdict": "rendered",
             "verification_level": "none", "detail": ""},
        ],
    }
    report.update(fields)
    path = write_json(project / ".ghostworkflow" / run_id /
                      "workflow-report.json", report)
    if board:
        (path.parent / "board.html").write_text(
            "<!DOCTYPE html><title>run board</title>\n",
            encoding="utf-8")
    return path


# ------------------------------------------------------------- discovery

def test_no_workflow_runs_is_an_absent_row(cli, tmp_path):
    p = tmp_path / "plain"
    p.mkdir()
    section = _section(_board(cli, p))
    assert section["state"] == "absent"
    assert section["summary"] == "no report found"


def test_newest_run_wins_when_several(cli, tmp_path):
    p = tmp_path / "multi"
    p.mkdir()
    old = _workflow_report(p, run_id="wf-old", verdict="attention",
                           timestamp=fixture_iso(-60).replace("+00:00", "Z"))
    new = _workflow_report(p, run_id="wf-new", verdict="ok",
                           timestamp=fixture_iso(60).replace("+00:00", "Z"))
    # Discovery order is newest file first, as with every adapter;
    # pin the mtimes so the newer run is unambiguously newer.
    base = 1_760_000_000
    os.utime(old, (base, base))
    os.utime(new, (base + 3600, base + 3600))
    board = _board(cli, p)
    section = _section(board)
    assert "wf-new" in section["summary"]
    assert "wf-old" not in section["summary"]
    assert section["state"] == "ok"
    assert board["column"] == "verified"


def test_report_outside_the_run_layout_is_not_discovered(cli, tmp_path):
    """A workflow-report.json NOT under .ghostworkflow/<run-id>/ was
    not written by a workflow run and is not picked up."""
    p = tmp_path / "stray"
    p.mkdir()
    _workflow_report(p, run_id="wf-x")
    stray = json.loads((p / ".ghostworkflow" / "wf-x" /
                        "workflow-report.json").read_text(encoding="utf-8"))
    write_json(p / "workflow-report.json", stray)
    (p / ".ghostworkflow").rename(p / ".ghostworkflow-gone")
    section = _section(_board(cli, p))
    assert section["state"] == "absent"


def test_malformed_newest_falls_back_to_older_valid_run(cli, tmp_path):
    p = tmp_path / "fallback"
    p.mkdir()
    good = _workflow_report(p, run_id="wf-good", verdict="ok")
    bad_dir = p / ".ghostworkflow" / "wf-bad"
    bad_dir.mkdir(parents=True)
    bad = bad_dir / "workflow-report.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    base = 1_760_000_000
    os.utime(good, (base, base))
    os.utime(bad, (base + 3600, base + 3600))
    section = _section(_board(cli, p))
    assert section["state"] == "ok"
    assert "wf-good" in section["summary"]


# --------------------------------------------------------- verdict mapping

def test_ok_at_tests_executed_supports_verified_with_level_named(
        cli, tmp_path):
    p = tmp_path / "wfonly"
    p.mkdir()
    _workflow_report(p, verdict="ok", level="tests-executed")
    board = _board(cli, p)
    section = _section(board)
    assert section["state"] == "ok"
    assert section["verification_level"] == "tests-executed"
    assert section["tool_version"] == "0.1.0"
    assert board["column"] == "verified"
    reason = board["column_reason"]
    assert "strongest verification level: tests-executed" in reason
    # Only Workflow of the board's 12 tool rows has a live report.
    assert "11 of 12 checks missing" in reason


def test_attention_verdict_places_project_in_attention(cli, tmp_path):
    p = tmp_path / "wfattn"
    p.mkdir()
    _workflow_report(p, verdict="attention")
    board = _board(cli, p)
    section = _section(board)
    assert section["state"] == "attention"
    assert board["column"] == "attention"
    assert board["column_reason"] == "Workflow verdict: attention"


def test_failed_verdict_is_attention_not_a_crash(cli, tmp_path):
    p = tmp_path / "wffailed"
    p.mkdir()
    _workflow_report(p, verdict="failed", level="static-analysis")
    board = _board(cli, p)
    section = _section(board)
    assert section["state"] == "attention"
    assert board["column"] == "attention"
    assert "failed" in board["column_reason"]


# ------------------------------------------------------------------ level

def test_unknown_level_is_unstated_never_accepted(cli, tmp_path):
    p = tmp_path / "wflevel"
    p.mkdir()
    _workflow_report(p, verdict="ok", level="certified-gold")
    board = _board(cli, p)
    section = _section(board)
    assert section["verification_level"] is None
    assert board["column"] == "verified"
    assert "verification level not stated" in board["column_reason"]
    assert "certified-gold" not in board["column_reason"]


# -------------------------------------------------------------- malformed

def test_malformed_report_is_unreadable_and_other_evidence_intact(
        cli, tmp_path):
    p = tmp_path / "wfbad"
    p.mkdir()
    run_dir = p / ".ghostworkflow" / "wf-broken"
    run_dir.mkdir(parents=True)
    (run_dir / "workflow-report.json").write_text(
        "{ this is not json", encoding="utf-8")
    verify_report(p, verdict="sufficient")
    proc = run_cli(cli, ["summary", p, "--json"])
    assert proc.returncode == 0, combined(proc)
    board = json.loads(proc.stdout)["projects"][0]
    workflow = _section(board)
    assert workflow["state"] == "unreadable"
    assert "unreadable" in workflow["summary"]
    verify = _section(board, "GhostVerify")
    assert verify["state"] == "ok"
    assert board["column"] == "attention"  # unreadable counts, per plan


# ------------------------------------------------------------- row content

def test_steps_version_and_tree_hash_are_on_the_row(cli, tmp_path):
    p = tmp_path / "wfdetail"
    p.mkdir()
    _workflow_report(p)
    section = _section(_board(cli, p))
    assert "slice ok" in section["summary"]
    assert "verify attention" in section["summary"]
    assert "bench ok" in section["summary"]
    assert "(ghostworkflow 0.1.0)" in section["summary"]
    assert TREE in section["summary"]
    assert section["when"][:13] == AT[:13]
    assert section["time_kind"] == "reported"


def test_absent_tree_hash_is_never_invented(cli, tmp_path):
    p = tmp_path / "wfnohash"
    p.mkdir()
    _workflow_report(p, tree_hash=None)
    section = _section(_board(cli, p))
    assert "tree_hash" not in section["summary"]
    assert "sha256:" not in section["summary"]


def test_row_source_is_the_run_board_and_resolves(cli, tmp_path):
    p = tmp_path / "wflink"
    p.mkdir()
    _workflow_report(p)
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", p, "-o", out])
    assert proc.returncode == 0, combined(proc)
    board = _board(cli, p)
    section = _section(board)
    assert section["source"] == f".ghostworkflow/{RUN}/board.html"
    # Resolve the row's artifact the way a reader does: the card
    # prints the project path, the row prints a project-relative
    # source; joined, they must land on the real board file.
    resolved = Path(board["path"]) / section["source"]
    assert resolved.is_file()
    assert "board.html" in out.read_text(encoding="utf-8")


def test_row_source_falls_back_to_report_when_no_board(cli, tmp_path):
    p = tmp_path / "wfnoboard"
    p.mkdir()
    _workflow_report(p, board=False)
    section = _section(_board(cli, p))
    assert section["source"] == \
        f".ghostworkflow/{RUN}/workflow-report.json"
