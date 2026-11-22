"""History-trend tests: Slice/Verify/Bench rows carry context from
their .jsonl histories (2+ entries), built only from recognized
fields. A trend is context, never a verdict: the latest entry alone
places the project, so a recovered tool is Verified even when older
history needed attention, and an old clean history never softens a
failing latest report.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import fixture_iso, combined, run_cli, write_json, write_jsonl

T1 = fixture_iso(0, days=-2)
T2 = fixture_iso(0, days=-1)
T3 = fixture_iso(0)


def _board(cli, project: Path) -> dict:
    proc = run_cli(cli, ["summary", project, "--json"])
    assert proc.returncode == 0, combined(proc)
    return json.loads(proc.stdout)["projects"][0]


def _section(board: dict, tool: str) -> dict:
    for section in board["sections"]:
        if section["tool"] == tool:
            return section
    raise AssertionError(f"no {tool} section in {board['sections']}")


def _slice_row(at, before, after):
    return {"at": at, "kind": "export", "before_tokens": before,
            "after_tokens": after, "saved_tokens": before - after}


def _verify_row(at, verdict):
    return {"at": at, "tool": "ghostverify", "verdict": verdict,
            "hard_gaps": 0, "patch_result": None}


def _bench_row(at, run_id, tasks_failed):
    return {"at": at, "tool": "ghostbench", "run_id": run_id,
            "tasks_total": 5, "tasks_failed": tasks_failed}


# ---------------------------------------------------------------- Slice

def test_slice_trend_compares_latest_saved_with_previous(cli, tmp_path):
    project = tmp_path / "p"
    write_jsonl(project / ".ghostslice-history.jsonl", [
        _slice_row(T1, 100000, 40000),
        _slice_row(T2, 100000, 30000),
        _slice_row(T3, 123456, 45678),
    ])
    section = _section(_board(cli, project), "GhostSlice")
    assert section["state"] == "ok"
    assert "3 entries recorded in history" in section["trend"]
    assert "tokens saved 70,000 -> 77,778 (up 7,778)" in section["trend"]


def test_slice_trend_derives_saved_from_before_and_after(cli, tmp_path):
    project = tmp_path / "p"
    rows = [_slice_row(T1, 1000, 900), _slice_row(T2, 1000, 900)]
    for row in rows:
        del row["saved_tokens"]
    write_jsonl(project / ".ghostslice-history.jsonl", rows)
    section = _section(_board(cli, project), "GhostSlice")
    assert "tokens saved 100 -> 100 (unchanged)" in section["trend"]


def test_single_history_entry_has_no_trend(cli, tmp_path):
    project = tmp_path / "p"
    write_jsonl(project / ".ghostslice-history.jsonl",
                [_slice_row(T3, 123456, 45678)])
    section = _section(_board(cli, project), "GhostSlice")
    assert section["trend"] == ""


# ---------------------------------------------------------------- Verify

def test_verify_trend_names_verdict_change_and_attention_count(
        cli, tmp_path):
    project = tmp_path / "p"
    write_jsonl(project / ".ghostverify-history.jsonl", [
        _verify_row(T1, "gaps_found"),
        _verify_row(T2, "sufficient"),
        _verify_row(T3, "sufficient"),
    ])
    board = _board(cli, project)
    section = _section(board, "GhostVerify")
    assert "3 verdicts recorded in history" in section["trend"]
    assert "1 needed attention" in section["trend"]
    assert "verdict unchanged from previous (sufficient)" in \
        section["trend"]
    # Older attention history does not demote a recovered latest.
    assert board["column"] == "verified"


def test_verify_trend_attached_when_report_is_the_evidence(cli, tmp_path):
    project = tmp_path / "p"
    write_json(project / "bundle" / "verify-report.json", {
        "tool": "ghostverify", "verdict": "gaps_found", "gaps": []})
    write_jsonl(project / ".ghostverify-history.jsonl", [
        _verify_row(T1, "sufficient"),
        _verify_row(T3, "gaps_found"),
    ])
    board = _board(cli, project)
    section = _section(board, "GhostVerify")
    assert section["state"] == "attention"
    assert "verdict changed: sufficient -> gaps_found" in section["trend"]
    assert board["column"] == "attention"


# ---------------------------------------------------------------- Bench

def test_bench_history_only_tasks_failed_is_attention(cli, tmp_path):
    # Bench's history writer records "tasks_failed"; a history-only
    # project with failing runs must not read as ok.
    project = tmp_path / "p"
    write_jsonl(project / ".ghostbench-history.jsonl", [
        _bench_row(T1, "run-1", 0),
        _bench_row(T3, "run-2", 2),
    ])
    board = _board(cli, project)
    section = _section(board, "GhostBench")
    assert section["state"] == "attention"
    assert "2 failed" in section["summary"]
    assert "2 runs recorded in history" in section["trend"]
    assert "failing tasks 0 -> 2" in section["trend"]
    assert board["column"] == "attention"


def test_bench_trend_shows_recovery_and_latest_still_rules(cli, tmp_path):
    project = tmp_path / "p"
    write_jsonl(project / ".ghostbench-history.jsonl", [
        _bench_row(T1, "run-1", 3),
        _bench_row(T3, "run-2", 0),
    ])
    board = _board(cli, project)
    section = _section(board, "GhostBench")
    assert section["state"] == "ok"
    assert "failing tasks 3 -> 0" in section["trend"]
    assert board["column"] == "verified"


def test_bench_trend_attached_when_report_is_the_evidence(cli, tmp_path):
    project = tmp_path / "p"
    write_json(project / "runs" / "bench-report.json", {
        "tool": "ghostbench", "run_id": "run-2",
        "tasks": [{"id": "t1", "status": "pass"}]})
    write_jsonl(project / ".ghostbench-history.jsonl", [
        _bench_row(T1, "run-1", 1),
        _bench_row(T3, "run-2", 0),
    ])
    section = _section(_board(cli, project), "GhostBench")
    assert "failing tasks 1 -> 0" in section["trend"]


# ------------------------------------------------------------- rendering

def test_trend_reaches_text_and_html_and_is_escaped(cli, tmp_path):
    project = tmp_path / "p"
    hostile = "<script>alert(1)</script>"
    write_jsonl(project / ".ghostverify-history.jsonl", [
        _verify_row(T1, hostile),
        _verify_row(T3, "sufficient"),
    ])
    proc = run_cli(cli, ["summary", project])
    assert proc.returncode == 0, combined(proc)
    assert "trend:" in proc.stdout
    assert hostile in proc.stdout  # text summary is plain text

    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", project, "-o", out])
    assert proc.returncode == 0, combined(proc)
    html_text = out.read_text(encoding="utf-8")
    assert "<script" not in html_text
    assert "&lt;script&gt;" in html_text
    assert "trend:" in html_text
