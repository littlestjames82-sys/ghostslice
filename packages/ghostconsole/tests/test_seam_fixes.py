"""Seam-fix tests (Oct 14, 2026), from the ecosystem pass record
(~/workspace/ghostslice-companions/ECOSYSTEM.md, seams 3 and 4).

Seam 3: reports shipped inside a project as test/example material
(under tests/, fixtures/, examples/) are fixture evidence, not the
project's live state. They are shown on the card, labelled, and never
drive the project's column. On the live ecosystem board all three
Attention rows were fixture reports (a Bench sample run, a Verify
report in tests/fixtures/, Console's own examples/fixture_reports/).

Seam 4: adapters for the Wave 4 report types the board could not read
at all: GhostHandoff packs (handoff.json), GhostLogs incident packs
(manifest.json beside INCIDENT.md), GhostDeps manifests
(deps-manifest.json), GhostData packs (manifest.json beside
PROMPT.md). Fixture shapes below mirror the sibling tools' real
writers and shipped examples, not inventions.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import conftest
from conftest import fixture_iso, combined, run_cli, write_json, write_jsonl

NOW = fixture_iso(40)


def _board(cli, project: Path) -> dict:
    proc = run_cli(cli, ["summary", project, "--json"])
    assert proc.returncode == 0, combined(proc)
    return json.loads(proc.stdout)["projects"][0]


def _section(board: dict, tool: str) -> dict:
    for section in board["sections"]:
        if section["tool"] == tool:
            return section
    raise AssertionError(f"no {tool} section in {board['sections']}")


# ------------------------------------------------------------- Seam 3

def _fixture_verify(p: Path, verdict="gaps_found"):
    return write_json(p / "tests" / "fixtures" / "reports"
                      / "verify-report.json", {
                          "tool": "ghostverify", "version": "0.1.0",
                          "verdict": verdict, "exit_code": 1,
                          "gaps": [{"symbol": "missing_0",
                                    "needed_by": "src/app.py:main"}]})


def _fixture_bench(p: Path, failed=1):
    tasks = [{"id": "task-1", "status": "failed" if failed else "passed"},
             {"id": "task-2", "status": "passed"}]
    return write_json(p / "examples" / "runs" / "bench-report.json", {
        "tool": "ghostbench", "run_id": "SAMPLE-run-b", "tasks": tasks})


def test_fixture_reports_shown_labelled_but_do_not_place(cli, tmp_path):
    p = tmp_path / "fixonly"
    p.mkdir()
    _fixture_verify(p)
    _fixture_bench(p)
    board = _board(cli, p)
    assert board["column"] == "stale"
    assert board["column"] != "attention"
    assert "no live reports found" in board["column_reason"]
    assert "fixture/example" in board["column_reason"]
    verify = _section(board, "GhostVerify")
    assert verify["provenance"] == "fixture"
    assert verify["state"] == "attention"  # evidence kept, not hidden
    assert "(fixture/example report)" in verify["summary"]
    bench = _section(board, "GhostBench")
    assert bench["provenance"] == "fixture"
    assert bench["state"] == "attention"


def test_live_failing_report_still_attention_despite_fixtures(
        cli, tmp_path):
    p = tmp_path / "mixed"
    p.mkdir()
    conftest.verify_report(p, verdict="gaps_found", hard_gaps=2)
    _fixture_bench(p)
    board = _board(cli, p)
    assert board["column"] == "attention"
    assert "Verify verdict" in board["column_reason"]
    assert _section(board, "GhostVerify")["provenance"] == "live"
    assert _section(board, "GhostBench")["provenance"] == "fixture"


def test_live_report_wins_over_newer_fixture_same_tool(cli, tmp_path):
    p = tmp_path / "livewins"
    p.mkdir()
    conftest.verify_report(p, verdict="sufficient")
    fixture = _fixture_verify(p, verdict="gaps_found")
    future = time.time() + 3600
    os.utime(fixture, (future, future))  # fixture is NEWER on disk
    board = _board(cli, p)
    verify = _section(board, "GhostVerify")
    assert verify["provenance"] == "live"
    assert verify["state"] == "ok"
    assert board["column"] == "verified"


def test_fixture_unreadable_report_does_not_place(cli, tmp_path):
    p = tmp_path / "fixcorrupt"
    p.mkdir()
    bad = p / "examples" / "verify-report.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{ not json", encoding="utf-8")
    board = _board(cli, p)
    verify = _section(board, "GhostVerify")
    assert verify["state"] == "unreadable"
    assert verify["provenance"] == "fixture"
    assert board["column"] == "stale"


def test_fixture_watch_stale_reason_is_not_the_live_reason(cli, tmp_path):
    p = tmp_path / "fixwatch"
    p.mkdir()
    conftest.watch_report(p / "examples" / "demo")
    board = _board(cli, p)
    watch = _section(board, "GhostWatch")
    assert watch["provenance"] == "fixture"
    assert board["column"] == "stale"
    assert "no live reports found" in board["column_reason"]


def test_fixture_approve_store_does_not_place(cli, tmp_path):
    p = tmp_path / "fixapprove"
    p.mkdir()
    conftest.slice_history(p)
    store = p / "examples" / "demo" / ".ghostapprove"
    write_json(store / "requests" / "req-1.json", {
        "id": "req-1", "kind": "shell", "summary": "fixture request"})
    write_jsonl(store / "ledger.jsonl", [])
    board = _board(cli, p)
    approve = _section(board, "GhostApprove")
    assert approve["provenance"] == "fixture"
    assert approve["state"] == "attention"  # 1 pending, as evidence
    assert "(fixture/example report)" in approve["summary"]
    assert board["column"] == "verified"  # live Slice row is ok


def test_fresh_fixture_does_not_defeat_age_staleness(cli, tmp_path):
    p = tmp_path / "oldlive"
    p.mkdir()
    conftest.slice_history(p, at="2026-08-01T08:00:00+00:00")
    _fixture_verify(p, verdict="sufficient")
    old_ts = time.time() - 74 * 24 * 3600
    for f in (p / ".ghostslice-history.jsonl",):
        os.utime(f, (old_ts, old_ts))
    board = _board(cli, p)
    assert board["column"] == "stale"
    assert "day(s) old" in board["column_reason"]


def test_fixture_labelling_visible_in_html(cli, tmp_path):
    p = tmp_path / "fixhtml"
    p.mkdir()
    _fixture_verify(p)
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", p, "-o", out])
    assert proc.returncode == 0, combined(proc)
    html = out.read_text(encoding="utf-8")
    assert "(fixture/example report)" in html
    assert "no live reports found" in html


# ------------------------------------------------------------- Seam 4

def _handoff_pack(p: Path, git_available=True, loops=2, steps=1):
    git = {"available": git_available}
    if git_available:
        git.update({
            "head": "f7d5b826fedbfc3c9f4cceb82fb1fd723a466d6d",
            "head_short": "f7d5b82", "branch": "master",
            "detached": False,
            "status": {"staged": [], "unstaged": ["src/app.py"],
                       "untracked": ["notes.md"],
                       "staged_count": 0, "unstaged_count": 1,
                       "untracked_count": 1},
        })
    else:
        git["reason"] = "not a git work tree (or git not on PATH)"
    return write_json(p / "handoff-out" / "handoff.json", {
        "tool": "ghosthandoff", "version": "0.1.0",
        "generated_at": NOW,
        "project": {"path": str(p), "name": p.name},
        "session_window": "last 12 hours (default) plus all "
                          "uncommitted changes",
        "git": git,
        "markers": {"total": 0, "code_total": 0, "docs_total": 0,
                    "items": []},
        "reports": [],
        "open_loops": [{"kind": "uncommitted-changes",
                        "detail": "2 file(s) changed",
                        "source": "git status"}] * loops,
        "next_steps": [{"text": "Decide on the changed files.",
                        "source": "git status"}] * steps,
    })


def test_handoff_pack_row_states_state_and_loops(cli, tmp_path):
    p = tmp_path / "handed"
    p.mkdir()
    _handoff_pack(p)
    board = _board(cli, p)
    section = _section(board, "GhostHandoff")
    assert section["state"] == "ok"
    assert section["provenance"] == "live"
    assert "master@f7d5b82" in section["summary"]
    assert "2 uncommitted change(s)" in section["summary"]
    assert "2 open loop(s)" in section["summary"]
    assert "1 next step(s)" in section["summary"]
    assert board["column"] == "verified"


def test_handoff_pack_without_git_still_rows(cli, tmp_path):
    p = tmp_path / "nogit"
    p.mkdir()
    _handoff_pack(p, git_available=False, loops=0, steps=0)
    board = _board(cli, p)
    section = _section(board, "GhostHandoff")
    assert section["state"] == "ok"
    assert "git state not recorded" in section["summary"]
    assert "0 open loop(s)" in section["summary"]


def test_handoff_corrupt_pack_is_unreadable_and_attention(cli, tmp_path):
    p = tmp_path / "badhand"
    p.mkdir()
    bad = p / "handoff-out" / "handoff.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{ nope", encoding="utf-8")
    board = _board(cli, p)
    section = _section(board, "GhostHandoff")
    assert section["state"] == "unreadable"
    assert board["column"] == "attention"


def _logs_pack(p: Path, over_budget=False, reconciles=True):
    pack = p / "incident-pack"
    (pack / "INCIDENT.md").parent.mkdir(parents=True, exist_ok=True)
    (pack / "INCIDENT.md").write_text("# Incident pack\n",
                                      encoding="utf-8")
    return write_json(pack / "manifest.json", {
        "tool": "ghostlogs", "version": "0.1.0", "generated_at": NOW,
        "source": {"path": "app.log", "bytes": 1894, "lines": 33},
        "budget_tokens": 2000, "pack_estimated_tokens": 752,
        "over_budget": over_budget,
        "counts": {"total_lines": 33, "kept": 15, "collapsed": 18,
                   "dropped": 0, "dropped_by_reason": {},
                   "reconciles": reconciles},
        "windows": {"matched": 1, "emitted": 1, "list": []},
        "duplicates": {"groups": 2, "list": []},
        "redaction": {"enabled": True,
                      "counts": {"aws-access-key": 1}, "total": 1},
    })


def test_logs_pack_row_states_incident(cli, tmp_path):
    p = tmp_path / "logged"
    p.mkdir()
    _logs_pack(p)
    board = _board(cli, p)
    section = _section(board, "GhostLogs")
    assert section["state"] == "ok"
    assert "33 line(s)" in section["summary"]
    assert "15 kept" in section["summary"]
    assert "1 of 1 error window(s)" in section["summary"]
    assert "752 of 2,000 budget tokens" in section["summary"]
    assert "1 redaction(s)" in section["summary"]
    assert board["column"] == "verified"


def test_logs_over_budget_is_attention(cli, tmp_path):
    p = tmp_path / "overbudget"
    p.mkdir()
    _logs_pack(p, over_budget=True)
    board = _board(cli, p)
    section = _section(board, "GhostLogs")
    assert section["state"] == "attention"
    assert "over its token budget" in section["reason"]
    assert board["column"] == "attention"


def test_logs_unreconciled_counts_are_attention(cli, tmp_path):
    p = tmp_path / "unreconciled"
    p.mkdir()
    _logs_pack(p, reconciles=False)
    board = _board(cli, p)
    assert _section(board, "GhostLogs")["state"] == "attention"
    assert board["column"] == "attention"


def test_corrupt_manifest_claimed_only_with_companion(cli, tmp_path):
    """A corrupt bare manifest.json is ambiguous (Slice, Logs, and
    Data all use the name). Logs claims it only when INCIDENT.md sits
    beside it; Data only with PROMPT.md."""
    p = tmp_path / "ambiguous"
    p.mkdir()
    pack = p / "some-pack"
    pack.mkdir()
    (pack / "manifest.json").write_text("{ broken", encoding="utf-8")
    board = _board(cli, p)
    assert _section(board, "GhostLogs")["state"] == "absent"
    assert _section(board, "GhostData")["state"] == "absent"
    (pack / "INCIDENT.md").write_text("# Incident pack\n",
                                      encoding="utf-8")
    board = _board(cli, p)
    assert _section(board, "GhostLogs")["state"] == "unreadable"
    assert _section(board, "GhostData")["state"] == "absent"
    assert board["column"] == "attention"


def _deps_manifest(p: Path, imported_not_declared=1,
                   declared_not_imported=1):
    return write_json(p / "deps" / "deps-manifest.json", {
        "tool": "ghostdeps", "version": "0.1.0", "generated_at": NOW,
        "root": str(p),
        "counts": {"declared": 3, "declared_and_used": 1,
                   "declared_not_imported": declared_not_imported,
                   "imported_not_declared": imported_not_declared,
                   "pins_recorded": 4, "pins_transitive_recorded": 2,
                   "build_requirements": 1},
        "sections": {"declared_and_used": [], "declared_not_imported": [],
                     "imported_not_declared": [], "pins": [],
                     "transitive_pins": []},
    })


def test_deps_imported_not_declared_is_attention(cli, tmp_path):
    p = tmp_path / "depsgap"
    p.mkdir()
    _deps_manifest(p, imported_not_declared=2)
    board = _board(cli, p)
    section = _section(board, "GhostDeps")
    assert section["state"] == "attention"
    assert "2 imported package(s) not declared" in section["reason"]
    assert "3 declared" in section["summary"]
    assert "6 pin(s) recorded" in section["summary"]
    assert board["column"] == "attention"


def test_deps_declared_not_imported_alone_is_ok(cli, tmp_path):
    """GhostDeps' own notes: declared-not-imported is "a lead for a
    human, not a verdict". It is stated on the row, never a column."""
    p = tmp_path / "depslead"
    p.mkdir()
    _deps_manifest(p, imported_not_declared=0, declared_not_imported=2)
    board = _board(cli, p)
    section = _section(board, "GhostDeps")
    assert section["state"] == "ok"
    assert "2 declared not imported" in section["summary"]
    assert board["column"] == "verified"


def _data_pack(p: Path, malformed=0):
    pack = p / "customers-pack"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "PROMPT.md").write_text("# Data pack\n", encoding="utf-8")
    columns = [{"name": name, "type": "string", "redacted": False}
               for name in ("id", "name", "plan", "seats", "email")]
    columns[-1]["redacted"] = True
    return write_json(pack / "manifest.json", {
        "tool": "ghostdata", "version": "0.1.0", "generated_at": NOW,
        "source": {"file": "customers.csv", "format": "csv",
                   "bytes": 310},
        "counts": {"rows_parsed": 6, "rows_malformed": malformed,
                   "rows_total": 6 + malformed, "blank_lines": 0,
                   "truncated": False},
        "columns": columns,
        "redaction": {"enabled": True,
                      "columns": [{"name": "email",
                                   "reason": "column name matches "
                                             "email"}]},
    })


def test_data_pack_row_states_rows_and_redaction(cli, tmp_path):
    p = tmp_path / "datapacked"
    p.mkdir()
    _data_pack(p)
    board = _board(cli, p)
    section = _section(board, "GhostData")
    assert section["state"] == "ok"
    assert "customers.csv (csv)" in section["summary"]
    assert "6 of 6 row(s) parsed" in section["summary"]
    assert "5 column(s)" in section["summary"]
    assert "1 redacted column(s)" in section["summary"]
    assert board["column"] == "verified"


def test_data_malformed_rows_are_attention(cli, tmp_path):
    p = tmp_path / "databad"
    p.mkdir()
    _data_pack(p, malformed=2)
    board = _board(cli, p)
    section = _section(board, "GhostData")
    assert section["state"] == "attention"
    assert "2 malformed row(s)" in section["reason"]
    assert board["column"] == "attention"


def test_slice_manifest_not_claimed_by_logs_or_data(cli, tmp_path):
    p = tmp_path / "sliceonly"
    p.mkdir()
    conftest.slice_manifest(p)
    board = _board(cli, p)
    assert _section(board, "GhostSlice")["state"] == "ok"
    assert _section(board, "GhostLogs")["state"] == "absent"
    assert _section(board, "GhostData")["state"] == "absent"


def test_new_adapters_have_absent_rows_on_empty_project(cli, tmp_path):
    p = conftest.empty_project(tmp_path)
    board = _board(cli, p)
    for tool, wording in (("GhostHandoff", "no handoff pack found"),
                          ("GhostLogs", "no incident pack found"),
                          ("GhostDeps", "no deps pack found"),
                          ("GhostData", "no data pack found")):
        section = _section(board, tool)
        assert section["state"] == "absent"
        assert section["summary"] == wording
        assert section["provenance"] == "live"


def test_new_adapter_summaries_escape_hostile_file_strings(
        cli, tmp_path):
    p = tmp_path / "hostilehand"
    p.mkdir()
    pack = _handoff_pack(p)
    data = json.loads(pack.read_text(encoding="utf-8"))
    data["git"]["branch"] = "<script>alert('xss-probe')</script>"
    pack.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", p, "-o", out])
    assert proc.returncode == 0, combined(proc)
    html = out.read_text(encoding="utf-8")
    assert "<script" not in html.lower()
    assert "xss-probe" in html  # shown as escaped text, not dropped
