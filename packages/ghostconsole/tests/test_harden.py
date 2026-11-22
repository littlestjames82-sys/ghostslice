"""Harden-round tests (Oct 18, 2026): field shapes the sibling
writers actually ship, present-but-unreadable evidence never being
dropped or counted as ok, embedded timestamps winning over mtime,
booleans never acting as numbers, and CLI argument validation.

Fixture shapes mirror the shipped examples and conftest writers:
GhostBench history records "tasks_failed", its report carries
"created_utc", GhostWatch reports carry "checked_at" and a findings
dict of lists, and GhostLedger totals name the estimate
"estimated_cost".
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import (combined, fixture_iso, run_cli,
                      write_json, write_jsonl)

NOW = fixture_iso(5)
OLD = "2020-01-01T00:00:00+00:00"


def _board(cli, project: Path) -> dict:
    proc = run_cli(cli, ["summary", project, "--json"])
    assert proc.returncode == 0, combined(proc)
    return json.loads(proc.stdout)["projects"][0]


def _section(board: dict, tool: str) -> dict:
    for section in board["sections"]:
        if section["tool"] == tool:
            return section
    raise AssertionError(f"no {tool} section in {board['sections']}")


# ------------------------------------------------------------- Bench

def test_bench_history_tasks_failed_is_attention(cli, tmp_path):
    """GhostBench's history writer records "tasks_failed"; the
    adapter read a "failed" key that shape never writes, so a
    history-only failing run rendered as ok."""
    project = tmp_path / "p"
    project.mkdir()
    write_jsonl(project / ".ghostbench-history.jsonl", [{
        "at": NOW, "tool": "ghostbench", "run_id": "run-9",
        "tasks_total": 5, "tasks_failed": 2}])
    board = _board(cli, project)
    section = _section(board, "GhostBench")
    assert section["state"] == "attention"
    assert "2 failed" in section["summary"]
    assert board["column"] == "attention"


def test_bench_history_zero_tasks_failed_is_ok(cli, tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    write_jsonl(project / ".ghostbench-history.jsonl", [{
        "at": NOW, "tool": "ghostbench", "run_id": "run-9",
        "tasks_total": 5, "tasks_failed": 0}])
    board = _board(cli, project)
    assert _section(board, "GhostBench")["state"] == "ok"
    assert board["column"] == "verified"


def test_bench_report_created_utc_is_the_report_time(cli, tmp_path):
    """A bench report's embedded "created_utc" is its run time. It
    used to be ignored, so the board showed the file's mtime and a
    copied-but-ancient report looked fresh."""
    project = tmp_path / "p"
    write_json(project / "runs" / "bench-report.json", {
        "tool": "ghostbench", "run_id": "old-run",
        "created_utc": "2020-01-01T00:00:00Z",
        "tasks": [{"id": "t1", "status": "pass"}]})
    board = _board(cli, project)
    section = _section(board, "GhostBench")
    assert section["when"].startswith("2020-01-01")
    assert section["time_kind"] == "reported"
    assert board["column"] == "stale"


# ------------------------------------------------------------- Watch

def test_watch_checked_at_is_the_report_time(cli, tmp_path):
    """GhostWatch reports carry "checked_at". Ignoring it meant a
    2020 check with a fresh file mtime landed in Verified."""
    project = tmp_path / "p"
    write_json(project / "watch" / "watch-report.json", {
        "tool": "ghostwatch", "verdict": "fresh", "checked_at": OLD,
        "findings": {"missing_bundle_file": [], "stale_symbols": []}})
    board = _board(cli, project)
    section = _section(board, "GhostWatch")
    assert section["state"] == "ok"
    assert section["when"].startswith("2020-01-01")
    assert section["time_kind"] == "reported"
    assert board["column"] == "stale"
    assert "day(s) old" in board["column_reason"]


def test_watch_verdict_with_whitespace_is_recognized(cli, tmp_path):
    project = tmp_path / "p"
    write_json(project / "watch" / "watch-report.json", {
        "tool": "ghostwatch", "verdict": " fresh ", "checked_at": NOW})
    board = _board(cli, project)
    assert _section(board, "GhostWatch")["state"] == "ok"


def test_watch_findings_dict_of_lists_is_counted(cli, tmp_path):
    """Real Watch findings are a dict of lists, not a list; the
    entries used to be silently uncounted on the row."""
    project = tmp_path / "p"
    write_json(project / "watch" / "watch-report.json", {
        "tool": "ghostwatch", "verdict": "stale", "checked_at": NOW,
        "findings": {"missing_bundle_file": ["a.py"],
                     "stale_symbols": ["s1", "s2"]}})
    board = _board(cli, project)
    section = _section(board, "GhostWatch")
    assert section["state"] == "stale"
    assert "3 finding(s)" in section["summary"]


# ------------------------------------------- present but unreadable

def test_verify_history_with_no_readable_lines_is_unreadable(
        cli, tmp_path):
    """A corrupt history used to fall through to "no report found",
    dropping present evidence; Slice's history treats the identical
    case as unreadable."""
    project = tmp_path / "p"
    project.mkdir()
    (project / ".ghostverify-history.jsonl").write_text(
        "{bad\n{also bad\n", encoding="utf-8")
    board = _board(cli, project)
    assert _section(board, "GhostVerify")["state"] == "unreadable"
    assert board["column"] == "attention"


def test_bench_history_empty_file_is_unreadable(cli, tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    (project / ".ghostbench-history.jsonl").write_text(
        "", encoding="utf-8")
    board = _board(cli, project)
    assert _section(board, "GhostBench")["state"] == "unreadable"
    assert board["column"] == "attention"


def test_ledger_jsonl_empty_file_is_not_ok_evidence(cli, tmp_path):
    """An empty ledger file used to render as an ok row ("0
    entries"), enough on its own to put a project in Verified."""
    project = tmp_path / "p"
    project.mkdir()
    (project / ".ghostledger.jsonl").write_text("", encoding="utf-8")
    board = _board(cli, project)
    assert _section(board, "GhostLedger")["state"] == "unreadable"
    assert board["column"] == "attention"


def test_verify_report_json_array_is_unreadable_not_absent(
        cli, tmp_path):
    """Valid JSON that is not an object is a corrupt report for a
    Ghost-specific file name, not a missing one."""
    project = tmp_path / "p"
    bad = project / "bundle" / "verify-report.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("[1, 2, 3]\n", encoding="utf-8")
    board = _board(cli, project)
    assert _section(board, "GhostVerify")["state"] == "unreadable"
    assert board["column"] == "attention"


def test_logs_manifest_json_array_beside_companion_is_unreadable(
        cli, tmp_path):
    project = tmp_path / "p"
    pack = project / "incident-pack"
    pack.mkdir(parents=True)
    (pack / "INCIDENT.md").write_text("# Incident pack\n",
                                      encoding="utf-8")
    (pack / "manifest.json").write_text("[1, 2]\n", encoding="utf-8")
    board = _board(cli, project)
    assert _section(board, "GhostLogs")["state"] == "unreadable"
    assert board["column"] == "attention"


# ------------------------------------------------------------ Ledger

def test_ledger_report_estimated_cost_reaches_summary(cli, tmp_path):
    """GhostLedger totals name the estimate "estimated_cost"; the
    adapter only looked for "cost_estimate_usd", so the cost never
    reached the board for the real shape."""
    project = tmp_path / "p"
    write_json(project / "ledger-report.json", {
        "tool": "ghostledger", "generated_at": NOW, "entries": 9,
        "loop_warnings": [],
        "totals": {"estimated_cost": 1.25, "actual_cost": 1.31}})
    board = _board(cli, project)
    section = _section(board, "GhostLedger")
    assert section["state"] == "ok"
    assert "9 entries" in section["summary"]
    assert "$1.25" in section["summary"]


# --------------------------------------------- booleans are not ints

def test_deps_boolean_count_is_not_a_gap(cli, tmp_path):
    """JSON true is not a count of 1: a boolean imported_not_declared
    used to drive Attention as "1 imported not declared"."""
    project = tmp_path / "p"
    write_json(project / "deps" / "deps-manifest.json", {
        "tool": "ghostdeps", "generated_at": NOW,
        "counts": {"declared": 1, "imported_not_declared": True}})
    board = _board(cli, project)
    assert _section(board, "GhostDeps")["state"] == "ok"
    assert board["column"] != "attention"


def test_data_boolean_malformed_is_not_a_count(cli, tmp_path):
    project = tmp_path / "p"
    pack = project / "data-pack"
    pack.mkdir(parents=True)
    (pack / "PROMPT.md").write_text("# Data pack\n", encoding="utf-8")
    write_json(pack / "manifest.json", {
        "tool": "ghostdata", "generated_at": NOW,
        "source": {"file": "rows.csv", "format": "csv"},
        "counts": {"rows_parsed": 6, "rows_total": 6,
                   "rows_malformed": True},
        "columns": [], "redaction": {"enabled": True, "columns": []}})
    board = _board(cli, project)
    assert _section(board, "GhostData")["state"] == "ok"


# --------------------------------------------------------- CLI input

def test_negative_stale_days_is_a_usage_error(cli, tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    proc = run_cli(cli, ["summary", project, "--stale-days", "-1"])
    assert proc.returncode == 2
    assert "stale-days" in combined(proc)


# ---------------------------------------------------- verdict wording

def test_verify_history_unrecognized_verdict_is_noted(cli, tmp_path):
    """The report path notes unrecognized verdict wording; the
    history path used to show the same wording as a plain ok."""
    project = tmp_path / "p"
    project.mkdir()
    write_jsonl(project / ".ghostverify-history.jsonl", [{
        "at": NOW, "tool": "ghostverify", "verdict": "banana_split",
        "patch_result": None}])
    board = _board(cli, project)
    section = _section(board, "GhostVerify")
    assert section["state"] == "ok"
    assert "banana_split" in section["summary"]
    assert "not recognized" in section["summary"]
