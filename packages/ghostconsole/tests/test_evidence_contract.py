"""Evidence-contract tests (Oct 18, 2026), from
~/workspace/ghostslice-companions/EVIDENCE_CONTRACT_DRAFT.md, Console
half. The known-answer sanity cases, stated before the change:

1. A project whose only live evidence is a Bench report at
   verification_level "static-analysis" lands in Verified ONLY with
   a reason saying static evidence only (no tests executed, no live
   run) and counting the missing checks. (Pre-change: Verified with
   the generic "latest reports ok" reason, level nowhere.)
2. The same project at "tests-executed" names that level in the
   reason. (Pre-change: identical generic reason.)
3. A Bench report whose own JSON says provenance "sample", sitting
   at a LIVE path (not under examples/), is labelled sample and does
   NOT place the project. (Pre-change: it placed the project in
   Verified as live evidence.)
4. A report with NO verification_level (every pre-contract report)
   renders the level as not stated, never an invented one.
   (Pre-change: no level field existed at all; the reason claimed an
   unqualified Verified.)

Shapes mirror GhostBench's post-contract writer: top-level
verification_level, provenance, tool_version on bench-report.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import conftest
from conftest import fixture_iso, combined, run_cli, write_json, write_jsonl

AT = fixture_iso(10).replace("+00:00", "Z")


def _board(cli, project: Path) -> dict:
    proc = run_cli(cli, ["summary", project, "--json"])
    assert proc.returncode == 0, combined(proc)
    return json.loads(proc.stdout)["projects"][0]


def _section(board: dict, tool: str) -> dict:
    for section in board["sections"]:
        if section["tool"] == tool:
            return section
    raise AssertionError(f"no {tool} section in {board['sections']}")


def _bench_report(project: Path, failed=0, **fields) -> Path:
    """Contract-shaped bench report at a LIVE path (runs/)."""
    tasks = [{"id": "task-1", "status": "failed" if failed else "passed"},
             {"id": "task-2", "status": "passed"}]
    report = {"tool": "ghostbench", "run_id": "contract-run-1",
              "created_utc": AT, "tier": "A", "tasks": tasks}
    report.update(fields)
    return write_json(project / "runs" / "bench-report.json", report)


# ------------------------------------------------------------ case 1

def test_static_only_verified_reason_says_static_and_counts_missing(
        cli, tmp_path):
    p = tmp_path / "staticonly"
    p.mkdir()
    _bench_report(p, verification_level="static-analysis",
                  provenance="live", tool_version="0.1.0")
    board = _board(cli, p)
    assert board["column"] == "verified"
    reason = board["column_reason"]
    assert "static-analysis" in reason
    assert "static only" in reason
    assert "no tests executed, no live run" in reason
    # Only Bench of the board's 12 tool rows has a live report.
    assert "11 of 12 checks missing" in reason
    bench = _section(board, "GhostBench")
    assert bench["provenance"] == "live"
    assert bench["verification_level"] == "static-analysis"
    assert bench["tool_version"] == "0.1.0"
    assert "0.1.0" in bench["summary"]


# ------------------------------------------------------------ case 2

def test_tests_executed_level_named_in_verified_reason(cli, tmp_path):
    p = tmp_path / "tested"
    p.mkdir()
    _bench_report(p, verification_level="tests-executed",
                  provenance="live", tool_version="0.1.0")
    board = _board(cli, p)
    assert board["column"] == "verified"
    reason = board["column_reason"]
    assert "tests-executed" in reason
    assert "static only" not in reason
    assert "11 of 12 checks missing" in reason
    assert _section(board, "GhostBench")["verification_level"] == \
        "tests-executed"


# ------------------------------------------------------------ case 3

def test_sample_provenance_at_live_path_never_places(cli, tmp_path):
    p = tmp_path / "samplelive"
    p.mkdir()
    _bench_report(p, verification_level="static-analysis",
                  provenance="sample", sample=True,
                  tool_version="0.1.0")
    board = _board(cli, p)
    bench = _section(board, "GhostBench")
    assert bench["provenance"] == "sample"
    assert "(sample report)" in bench["summary"]
    assert bench["state"] == "ok"  # evidence kept, not hidden
    assert board["column"] == "stale"
    assert board["column"] != "verified"
    assert "no live reports found" in board["column_reason"]
    assert "sample report" in board["column_reason"]


def test_sample_report_with_failures_is_not_attention(cli, tmp_path):
    p = tmp_path / "samplefail"
    p.mkdir()
    _bench_report(p, failed=1, verification_level="static-analysis",
                  provenance="sample", sample=True)
    board = _board(cli, p)
    bench = _section(board, "GhostBench")
    assert bench["state"] == "attention"  # the failure is still shown
    assert bench["provenance"] == "sample"
    assert board["column"] == "stale"
    assert board["column"] != "attention"


# ------------------------------------------------------------ case 4

def test_pre_contract_report_level_is_not_stated_never_invented(
        cli, tmp_path):
    p = tmp_path / "precontract"
    p.mkdir()
    _bench_report(p)  # no verification_level, provenance, tool_version
    board = _board(cli, p)
    bench = _section(board, "GhostBench")
    assert bench["verification_level"] is None
    assert bench["tool_version"] is None
    assert bench["provenance"] == "live"
    assert board["column"] == "verified"
    reason = board["column_reason"]
    assert "verification level not stated" in reason
    assert "strongest verification level" not in reason


def test_unrecognized_level_value_is_not_a_level(cli, tmp_path):
    p = tmp_path / "badlevel"
    p.mkdir()
    _bench_report(p, verification_level="certified-gold",
                  provenance="live")
    board = _board(cli, p)
    bench = _section(board, "GhostBench")
    assert bench["verification_level"] is None
    assert "certified-gold" not in board["column_reason"]
    assert "verification level not stated" in board["column_reason"]


# ------------------------------------------------------- strongest level

def test_strongest_level_wins_across_live_sections(cli, tmp_path):
    p = tmp_path / "strongest"
    p.mkdir()
    _bench_report(p, verification_level="static-analysis",
                  provenance="live")
    report = conftest.verify_report(p, verdict="sufficient")
    obj = json.loads(report.read_text(encoding="utf-8"))
    obj["verification_level"] = "live-agent"
    report.write_text(json.dumps(obj) + "\n", encoding="utf-8")
    board = _board(cli, p)
    assert board["column"] == "verified"
    assert "live-agent" in board["column_reason"]
    assert "static only" not in board["column_reason"]
    assert "10 of 12 checks missing" in board["column_reason"]


def test_fixture_level_never_feeds_strongest(cli, tmp_path):
    p = tmp_path / "fixlevel"
    p.mkdir()
    _bench_report(p, provenance="live")  # live, no level stated
    write_json(p / "examples" / "watch-report.json", {
        "tool": "ghostwatch", "verdict": "fresh",
        "checked_at": fixture_iso(20),
        "verification_level": "live-agent", "findings": {}})
    board = _board(cli, p)
    watch = _section(board, "GhostWatch")
    assert watch["provenance"] == "fixture"
    assert watch["verification_level"] == "live-agent"
    assert board["column"] == "verified"
    assert "live-agent" not in board["column_reason"]
    assert "verification level not stated" in board["column_reason"]


def test_bench_history_line_level_is_carried(cli, tmp_path):
    p = tmp_path / "benchhist"
    p.mkdir()
    write_jsonl(p / ".ghostbench-history.jsonl", [{
        "at": fixture_iso(10), "tool": "ghostbench",
        "run_id": "hist-run", "tasks_total": 2, "tasks_failed": 0,
        "verification_level": "tests-executed"}])
    board = _board(cli, p)
    bench = _section(board, "GhostBench")
    assert bench["verification_level"] == "tests-executed"
    assert board["column"] == "verified"
    assert "tests-executed" in board["column_reason"]


# ------------------------------------------------------------- rendering

def test_level_and_legend_render_in_html_and_text(cli, tmp_path):
    p = tmp_path / "rendered"
    p.mkdir()
    _bench_report(p, verification_level="tests-executed",
                  provenance="live", tool_version="0.1.0")
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", p, "-o", out])
    assert proc.returncode == 0, combined(proc)
    html = out.read_text(encoding="utf-8")
    assert "level: tests-executed" in html
    assert "Verification levels:" in html
    assert "static-analysis" in html
    assert "a real agent attempted the real task" in html
    assert "strongest verification level: tests-executed" in html

    proc = run_cli(cli, ["summary", p])
    assert proc.returncode == 0, combined(proc)
    text = proc.stdout
    assert "level: tests-executed" in text
    assert "Verification levels:" in text


def test_unstated_level_renders_no_level_on_row(cli, tmp_path):
    p = tmp_path / "norowlevel"
    p.mkdir()
    _bench_report(p)  # pre-contract shape
    proc = run_cli(cli, ["summary", p])
    assert proc.returncode == 0, combined(proc)
    bench_lines = [line for line in proc.stdout.splitlines()
                   if "GhostBench" in line]
    assert bench_lines and "level:" not in bench_lines[0]
