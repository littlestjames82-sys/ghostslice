"""Polish-round tests (Oct 14, 2026): verdict vocabularies matched
exactly per sibling format, and GhostApprove stores found beyond the
project root.

The verdict words below are the ones the shipped siblings actually
write (GhostVerify core.py / reports.py, GhostBench runner.py), not
inventions: substring matching used to put Verify's
"could_not_verify" and the patch verdict "flagged" on ok rows, which
could land a project in the Verified column when its own tool had
said the opposite of ok.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import (combined, fixture_iso, run_cli,
                      write_json, write_jsonl)

NOW = fixture_iso(5)


def _board(cli, project: Path) -> dict:
    proc = run_cli(cli, ["summary", project, "--json"])
    assert proc.returncode == 0, combined(proc)
    return json.loads(proc.stdout)["projects"][0]


def _section(board: dict, tool: str) -> dict:
    for section in board["sections"]:
        if section["tool"] == tool:
            return section
    raise AssertionError(f"no {tool} section in {board['sections']}")


def _verify_report(project: Path, verdict: str, post_verdict=None):
    report = {"tool": "ghostverify", "version": "0.1.0",
              "verdict": verdict, "exit_code": 0, "gaps": []}
    if post_verdict is not None:
        report["post"] = {"verdict": post_verdict}
    return write_json(project / "bundle" / "verify-report.json", report)


# ---------------------------------------------------------------- Verify

def test_verify_could_not_verify_report_is_attention(cli, tmp_path):
    project = tmp_path / "p"
    _verify_report(project, "could_not_verify")
    board = _board(cli, project)
    section = _section(board, "GhostVerify")
    assert section["state"] == "attention"
    assert "could_not_verify" in section["summary"]
    assert board["column"] == "attention"


def test_verify_could_not_verify_history_is_attention(cli, tmp_path):
    project = tmp_path / "p"
    write_jsonl(project / ".ghostverify-history.jsonl", [{
        "at": NOW, "tool": "ghostverify", "verdict": "could_not_verify",
        "hard_gaps": 0, "patch_result": None}])
    board = _board(cli, project)
    assert _section(board, "GhostVerify")["state"] == "attention"
    assert board["column"] == "attention"


def test_verify_post_flagged_is_attention(cli, tmp_path):
    project = tmp_path / "p"
    _verify_report(project, "sufficient", post_verdict="flagged")
    board = _board(cli, project)
    section = _section(board, "GhostVerify")
    assert section["state"] == "attention"
    assert "flagged" in section["summary"]
    assert board["column"] == "attention"


def test_verify_sufficient_after_expand_is_ok(cli, tmp_path):
    project = tmp_path / "p"
    _verify_report(project, "sufficient_after_expand")
    board = _board(cli, project)
    assert _section(board, "GhostVerify")["state"] == "ok"
    assert board["column"] == "verified"


def test_verify_gaps_remain_is_attention(cli, tmp_path):
    project = tmp_path / "p"
    _verify_report(project, "gaps_remain")
    board = _board(cli, project)
    assert _section(board, "GhostVerify")["state"] == "attention"
    assert board["column"] == "attention"


def test_verify_unrecognized_verdict_shown_verbatim_not_guessed(
        cli, tmp_path):
    project = tmp_path / "p"
    _verify_report(project, "banana_split")
    board = _board(cli, project)
    section = _section(board, "GhostVerify")
    assert section["state"] == "ok"
    assert "banana_split" in section["summary"]
    assert "not recognized" in section["summary"]
    assert board["column"] == "verified"


# ---------------------------------------------------------------- Bench

def _bench_report(project: Path, statuses):
    tasks = [{"id": f"t{i + 1}", "status": s}
             for i, s in enumerate(statuses)]
    return write_json(project / "runs" / "bench-report.json", {
        "tool": "ghostbench", "run_id": "fixture-run",
        "tasks": tasks})


def test_bench_real_status_vocabulary_counts_only_fail(cli, tmp_path):
    project = tmp_path / "p"
    _bench_report(project, ["pass", "fail", "unknown"])
    board = _board(cli, project)
    section = _section(board, "GhostBench")
    assert section["state"] == "attention"
    assert "1 failed" in section["summary"]
    assert board["column"] == "attention"


def test_bench_unknown_statuses_are_not_failures(cli, tmp_path):
    # GhostBench counts "unknown" separately from "fail" in its own
    # tallies; a run Bench could not judge is not a failing run.
    project = tmp_path / "p"
    _bench_report(project, ["unknown", "unknown"])
    board = _board(cli, project)
    section = _section(board, "GhostBench")
    assert section["state"] == "ok"
    assert "failed" not in section["summary"]
    assert board["column"] == "verified"


# ---------------------------------------------------------------- Approve

def _real_store(store: Path, requests, decided_ids=()):
    """A GhostApprove store in the sibling's real shapes: request
    records nest risk inside "content", ledger rows are events."""
    for rid, risk in requests:
        write_json(store / "requests" / f"{rid}.json", {
            "id": rid, "hash": f"hash-{rid}", "ingested_at": NOW,
            "content": {"source": "agent", "action": "shell",
                        "summary": f"request {rid}", "risk": risk}})
    rows = [{"event": "ingested", "id": rid, "at": NOW}
            for rid, _risk in requests]
    rows += [{"event": "approved", "id": rid, "at": NOW}
             for rid in decided_ids]
    write_jsonl(store / "ledger.jsonl", rows)
    return store


def test_approve_nested_store_is_found(cli, tmp_path):
    project = tmp_path / "p"
    _real_store(project / "sub" / ".ghostapprove", [("req-1", "high")])
    board = _board(cli, project)
    section = _section(board, "GhostApprove")
    assert section["state"] == "attention"
    assert "1 pending of 1" in section["summary"]
    assert "(risk: high)" in section["summary"]
    assert section["source"].endswith(
        str(Path("sub") / ".ghostapprove"))
    assert board["column"] == "attention"


def test_approve_multiple_nested_stores_aggregate(cli, tmp_path):
    project = tmp_path / "p"
    _real_store(project / "svc-a" / ".ghostapprove",
                [("req-1", "low"), ("req-2", "medium")],
                decided_ids=("req-1",))
    _real_store(project / "svc-b" / ".ghostapprove",
                [("req-3", "high")])
    board = _board(cli, project)
    section = _section(board, "GhostApprove")
    assert section["state"] == "attention"
    assert "2 pending of 3" in section["summary"]
    assert "2 nested store(s)" in section["summary"]
    assert "high" in section["summary"]


def test_approve_nested_store_in_skipped_dir_is_ignored(cli, tmp_path):
    project = tmp_path / "p"
    _real_store(project / "node_modules" / ".ghostapprove",
                [("req-1", "high")])
    board = _board(cli, project)
    assert _section(board, "GhostApprove")["state"] == "absent"


def test_approve_nested_store_beyond_search_depth_is_ignored(
        cli, tmp_path):
    project = tmp_path / "p"
    _real_store(project / "a" / "b" / "c" / "d" / ".ghostapprove",
                [("req-1", "high")])
    board = _board(cli, project)
    assert _section(board, "GhostApprove")["state"] == "absent"


def test_approve_root_store_takes_precedence_over_nested(cli, tmp_path):
    project = tmp_path / "p"
    _real_store(project / ".ghostapprove", [("req-1", "low")],
                decided_ids=("req-1",))
    _real_store(project / "sub" / ".ghostapprove", [("req-9", "high")])
    board = _board(cli, project)
    section = _section(board, "GhostApprove")
    assert section["state"] == "ok"
    assert "queue clear" in section["summary"]
    assert "nested" not in section["summary"]


def test_approve_risk_named_from_real_record_shape(cli, tmp_path):
    project = tmp_path / "p"
    _real_store(project / ".ghostapprove", [("req-1", "critical")])
    board = _board(cli, project)
    section = _section(board, "GhostApprove")
    assert section["state"] == "attention"
    assert "(risk: critical)" in section["summary"]
