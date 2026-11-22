"""Shared helpers for the GhostConsole black-box CLI suite.

The tests treat GhostConsole as a black box: they build fixture report
trees in the shapes the sibling Ghost tools actually write (see
PLAN.md, "How it pairs with the suite"), run the CLI, and check the
board it renders. Nothing here imports the package under test.

CLI discovery order:
  1. GHOSTCONSOLE_CMD environment variable (full command prefix)
  2. `ghostconsole` on PATH
  3. `python -m ghostconsole` with PYTHONPATH=<repo>/src
CLI tests skip cleanly when no CLI is discoverable; fixture-validity
tests always run.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from datetime import datetime, timedelta, timezone

_FIXTURE_BASE = datetime.now(timezone.utc).replace(
    minute=0, second=0, microsecond=0)


def fixture_iso(minutes=0, days=0):
    """Clock-relative fixture stamps (Cycle 2 I3): the
    board's stale window is measured against wall-clock
    now, so pinned calendar dates rot (they did, twice);
    these are computed from today and never do. The
    minute/day offsets preserve the fixtures' original
    relative spacing."""
    t = _FIXTURE_BASE + timedelta(days=days, minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%S+00:00")

REPO = Path(__file__).resolve().parents[1]

# Distinctive fixture numbers. Tests assert these exact figures reach
# the board unchanged, so they are chosen to not collide with each
# other or with plausible counts (project counts, ages, defaults).
SLICE_BEFORE = 123456
SLICE_AFTER = 45678
VERIFY_HARD_GAPS = 3
BENCH_TASKS_TOTAL = 5
BENCH_TASKS_FAILED = 1
LEDGER_LOOP_WARNINGS = 1
APPROVE_REQUESTS = 3
APPROVE_DECIDED = 1
APPROVE_PENDING = APPROVE_REQUESTS - APPROVE_DECIDED  # 2
SCOPE_TOP_RISK = 50


def cli_prefix() -> list[str] | None:
    env = os.environ.get("GHOSTCONSOLE_CMD")
    if env:
        return shlex.split(env)
    exe = shutil.which("ghostconsole")
    if exe:
        return [exe]
    if (REPO / "src" / "ghostconsole").is_dir():
        return [sys.executable, "-m", "ghostconsole"]
    return None


def cli_env() -> dict:
    env = dict(os.environ)
    src = str(REPO / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


@pytest.fixture(scope="session")
def cli():
    prefix = cli_prefix()
    if prefix is None:
        pytest.skip("ghostconsole CLI not discoverable (set "
                    "GHOSTCONSOLE_CMD, install it, or provide src/)")
    return prefix


def run_cli(cli, args, cwd=None, timeout=120):
    return subprocess.run(cli + [str(a) for a in args],
                          capture_output=True, text=True,
                          cwd=cwd, env=cli_env(), timeout=timeout)


def combined(proc) -> str:
    return (proc.stdout or "") + (proc.stderr or "")


# ---------------------------------------------------------------------
# Fixture report writers. Shapes mirror the sibling tools' writers:
# Slice ledger.py / exporter manifest, Verify reports.py,
# Bench bench-report.json, Scope scope.json, Ledger report.py,
# Watch core.py report dict, Approve store layout.
# ---------------------------------------------------------------------

def write_json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    return path


def write_jsonl(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows),
                    encoding="utf-8")
    return path


def slice_history(project: Path, at=fixture_iso(0)):
    return write_jsonl(project / ".ghostslice-history.jsonl", [{
        "at": at, "kind": "export", "bundle": ".claude_context",
        "before_tokens": SLICE_BEFORE, "after_tokens": SLICE_AFTER,
        "saved_tokens": SLICE_BEFORE - SLICE_AFTER, "estimator": "v2",
    }])


def slice_manifest(project: Path):
    return write_json(project / "bundle" / "manifest.json", {
        "tool": "ghostslice", "version": "1.0.6",
        "generated_at": fixture_iso(0),
        "root": str(project), "token_method": "ghostslice-estimator-v2",
        "files": [{"path": "src/app.py", "mode": "full",
                   "original_tokens": SLICE_BEFORE,
                   "sliced_tokens": SLICE_AFTER}],
        "total_original_tokens": SLICE_BEFORE,
        "total_sliced_tokens": SLICE_AFTER,
        "total_saved_tokens": SLICE_BEFORE - SLICE_AFTER,
    })


def verify_history(project: Path, verdict="sufficient", hard_gaps=0,
                   at=fixture_iso(5)):
    return write_jsonl(project / ".ghostverify-history.jsonl", [{
        "at": at, "tool": "ghostverify", "task": "fixture task",
        "bundle": "bundle", "bundle_manifest_sha256": "0" * 64,
        "verdict": verdict, "hard_gaps": hard_gaps, "soft_gaps": 0,
        "tokens_before": SLICE_AFTER, "tokens_after": SLICE_AFTER,
        "patch_result": None,
    }])


def verify_report(project: Path, verdict="sufficient", hard_gaps=0):
    gaps = [{"symbol": f"missing_{i}", "needed_by": "src/app.py:main"}
            for i in range(hard_gaps)]
    return write_json(project / "bundle" / "verify-report.json", {
        "tool": "ghostverify", "version": "0.1.0", "task": "fixture task",
        "bundle": "bundle", "verdict": verdict, "exit_code": 0,
        "gaps": gaps, "soft_gaps": [],
        "tokens": {"bundle_sliced": SLICE_AFTER,
                   "expanded_sliced": SLICE_AFTER},
    })


def bench_history(project: Path, at=fixture_iso(10),
                  failed=BENCH_TASKS_FAILED):
    return write_jsonl(project / ".ghostbench-history.jsonl", [{
        "at": at, "tool": "ghostbench", "run_id": "fixture-run-1",
        "corpus": "fixture", "tier": "A",
        "tasks_total": BENCH_TASKS_TOTAL,
        "tasks_failed": failed,
    }])


def bench_report(project: Path, failed=BENCH_TASKS_FAILED):
    tasks = []
    for i in range(BENCH_TASKS_TOTAL):
        is_failed = i < failed
        tasks.append({"id": f"task-{i + 1}", "project": "fixture",
                      "passed": not is_failed,
                      "status": "failed" if is_failed else "passed"})
    return write_json(project / "runs" / "bench-report.json", {
        "tool": "ghostbench", "version": "0.1.0",
        "run_id": "fixture-run-1", "created_utc": fixture_iso(10).replace("+00:00", "Z"),
        "tier": "A (static, no model, no spend)",
        "tasks": tasks,
        "failures_visible": [{"project": "fixture", "task": "task-1",
                              "failures": ["verify predicted 1 hard gap"]}],
    })


def workflow_report(project: Path, verdict="ok",
                    at=fixture_iso(10)):
    """One GhostWorkflow run: report + the board it rendered, under
    .ghostworkflow/<run-id>/, in the writer's documented shape."""
    run_id = "wf-20261014T081000Z-fixture"
    step = {"argv": [], "exit_code": 0, "started_utc": at,
            "finished_utc": at, "duration_s": 0.1, "reports": [],
            "detail": ""}
    steps = [
        dict(step, name="slice", status="ok", verdict="exported",
             verification_level="static-analysis"),
        dict(step, name="verify", status="ok", verdict="sufficient",
             verification_level="static-analysis"),
        dict(step, name="bench", status="ok", verdict="tasks_passed",
             verification_level="tests-executed"),
        dict(step, name="console", status="ok", verdict="rendered",
             verification_level="none"),
    ]
    engine = {"found": True, "version": "0.1.0", "how": "checkout",
              "home": "/fixture"}
    path = write_json(project / ".ghostworkflow" / run_id /
                      "workflow-report.json", {
        "project": {"name": project.name, "path": str(project)},
        "task": "fixture task", "commit": None,
        "tree_hash": "sha256:" + "0" * 64,
        "tree_hash_source": "fixture",
        "tool": "ghostworkflow", "tool_version": "0.1.0",
        "engines": {"ghostslice": dict(engine, version="1.0.6"),
                    "ghostverify": engine, "ghostbench": engine,
                    "ghostconsole": engine},
        "timestamp": at, "run_id": run_id, "verdict": verdict,
        "verification_level": "tests-executed", "provenance": "live",
        "steps": steps,
    })
    (path.parent / "board.html").write_text(
        "<!DOCTYPE html><title>fixture run board</title>\n",
        encoding="utf-8")
    return path


def scope_pack(project: Path):
    return write_json(project / "pack" / "scope.json", {
        "base": "HEAD~1", "head": "HEAD",
        "files": [{"path": "shared.py", "distance": 0, "mode": "full",
                   "changed_symbols": ["compute_total"],
                   "direct_callers": 6, "risk": SCOPE_TOP_RISK,
                   "risk_reasons": ["exported API", "6 callers"],
                   "covering_tests": ["tests/test_shared.py"]}],
        "notes": [],
    })


def ledger_report(project: Path, loop_warnings=0):
    warnings = [{"entry": "run-7", "reason": "actual cost far above estimate"}
                for _ in range(loop_warnings)]
    return write_json(project / "ledger-report.json", {
        "tool": "ghostledger", "version": "0.1.0",
        "generated_at": fixture_iso(15),
        "entries": 9, "loop_warnings": warnings,
        "totals": {"estimated_cost": 1.25, "actual_cost": 1.31},
    })


def watch_report(project: Path, verdict="fresh"):
    return write_json(project / "watch" / "watch-report.json", {
        "tool": "ghostwatch", "version": "0.1.0",
        "checked_at": fixture_iso(20),
        "bundle": "bundle", "verdict": verdict,
        "findings": {"missing_bundle_file": [], "stale_symbols": []},
    })


def approve_store(project: Path, total=APPROVE_REQUESTS,
                  decided=APPROVE_DECIDED):
    store = project / ".ghostapprove"
    for i in range(total):
        write_json(store / "requests" / f"req-{i + 1}.json", {
            "id": f"req-{i + 1}", "kind": "shell",
            "summary": f"fixture request {i + 1}",
            "requested_at": fixture_iso(25),
        })
    rows = [{"id": f"req-{i + 1}", "decision": "approved",
             "at": fixture_iso(30)} for i in range(decided)]
    write_jsonl(store / "ledger.jsonl", rows)
    return store


def healthy_project(base: Path, name="healthy") -> Path:
    """Every adapter present, everything ok, all timestamps recent."""
    p = base / name
    p.mkdir(parents=True)
    slice_history(p)
    slice_manifest(p)
    verify_history(p)
    verify_report(p)
    bench_history(p, failed=0)
    bench_report(p, failed=0)
    workflow_report(p)
    scope_pack(p)
    ledger_report(p, loop_warnings=0)
    watch_report(p, verdict="fresh")
    approve_store(p, total=1, decided=1)  # store present, nothing pending
    return p


def attention_project(base: Path, name="attention") -> Path:
    """Failed Verify verdict + pending approvals: attention twice over."""
    p = base / name
    p.mkdir(parents=True)
    slice_history(p)
    verify_history(p, verdict="gaps_found", hard_gaps=VERIFY_HARD_GAPS)
    verify_report(p, verdict="gaps_found", hard_gaps=VERIFY_HARD_GAPS)
    watch_report(p, verdict="fresh")
    approve_store(p)  # 2 pending
    return p


def stale_project(base: Path, name="stale") -> Path:
    """Watch says stale; that alone puts the project in Stale."""
    p = base / name
    p.mkdir(parents=True)
    slice_history(p)
    watch_report(p, verdict="stale")
    return p


def empty_project(base: Path, name="empty") -> Path:
    p = base / name
    p.mkdir(parents=True)
    (p / "README.md").write_text("# nothing ghost here\n", encoding="utf-8")
    return p
