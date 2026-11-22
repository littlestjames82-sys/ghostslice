"""Shared builders for the GhostConsole app tests: fabricated
workflow reports and a fake ghostworkflow executable. Nothing here
touches a real engine."""

from __future__ import annotations

import json
import os
import stat
import sys
import textwrap
import time
from pathlib import Path


def make_report(project_path: str, **overrides) -> dict:
    report = {
        "project": {
            "name": Path(project_path).name,
            "path": str(project_path),
        },
        "task": "Fix checkout totals using compute_total",
        "commit": None,
        "tree_hash": "sha256:0123456789abcdef",
        "tree_hash_source": "ghostbench bench-report.json task row "
                            "(project_tree_hash / project_commit)",
        "tool": "ghostworkflow",
        "tool_version": "0.1.0",
        "engines": {
            "ghostslice": {"found": True, "version": "1.0.6",
                           "how": "checkout", "home": "/engines"},
            "ghostverify": {"found": True, "version": "0.1.0",
                            "how": "checkout", "home": "/engines"},
            "ghostbench": {"found": True, "version": "0.1.0",
                           "how": "path", "home": None},
            "ghostconsole": {"found": True, "version": "0.1.0",
                             "how": "path", "home": None},
        },
        "timestamp": "2026-10-18T12:00:00+00:00",
        "run_id": "wf-20261018T120000Z-abc123",
        "verdict": "ok",
        "verification_level": "static-analysis",
        "provenance": "live",
        "steps": [
            {"name": "slice", "status": "ok",
             "argv": ["ghostslice", "task", str(project_path)],
             "exit_code": 0,
             "started_utc": "2026-10-18T12:00:00+00:00",
             "finished_utc": "2026-10-18T12:00:01+00:00",
             "duration_s": 1.0,
             "reports": [".ghostworkflow/wf/bundle/manifest.json"],
             "verdict": None, "verification_level": "static-analysis",
             "detail": "bundle written"},
            {"name": "console", "status": "ok",
             "argv": ["ghostconsole", "build", str(project_path)],
             "exit_code": 0,
             "started_utc": "2026-10-18T12:00:01+00:00",
             "finished_utc": "2026-10-18T12:00:02+00:00",
             "duration_s": 0.5,
             "reports": [".ghostworkflow/wf/board.html"],
             "verdict": None, "verification_level": "none",
             "detail": "board rendered"},
        ],
    }
    report.update(overrides)
    return report


def write_run(project_path, dirname: str, report: dict | None = None,
              board: str = "<html><body>board</body></html>") -> Path:
    run_dir = Path(project_path) / ".ghostworkflow" / dirname
    run_dir.mkdir(parents=True, exist_ok=True)
    if report is not None:
        (run_dir / "workflow-report.json").write_text(
            json.dumps(report, indent=1), encoding="utf-8")
    if board is not None:
        (run_dir / "board.html").write_text(board, encoding="utf-8")
    return run_dir


FAKE_WORKFLOW_SCRIPT = textwrap.dedent(
    """
    #!/usr/bin/env python3
    import json, os, sys, time
    from pathlib import Path

    def main():
        args = sys.argv[1:]
        if not args or args[0] != "run":
            print("fake ghostworkflow: only 'run' is supported")
            return 2
        project = Path(args[1])
        task = None
        if "--task" in args:
            task = args[args.index("--task") + 1]
        sleep = float(os.environ.get("FAKE_GW_SLEEP", "0"))
        if sleep:
            time.sleep(sleep)
        run_id = os.environ.get("FAKE_GW_RUN_ID", "wf-fake-0001")
        run_dir = project / ".ghostworkflow" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "project": {"name": project.name, "path": str(project)},
            "task": task,
            "commit": None,
            "tree_hash": "sha256:fakecafe",
            "tree_hash_source": "fake ghostworkflow",
            "tool": "ghostworkflow",
            "tool_version": "0.1.0",
            "engines": {},
            "timestamp": "2026-10-18T13:00:00+00:00",
            "run_id": run_id,
            "verdict": os.environ.get("FAKE_GW_VERDICT", "attention"),
            "verification_level": "tests-executed",
            "provenance": "live",
            "steps": [],
        }
        (run_dir / "workflow-report.json").write_text(json.dumps(report))
        (run_dir / "board.html").write_text(
            "<html><body>fake board</body></html>")
        print("fake run complete:", run_id)
        return int(os.environ.get("FAKE_GW_EXIT", "0"))

    sys.exit(main())
    """
).lstrip()


def make_fake_path_script(base: Path) -> Path:
    """A `ghostworkflow` executable in <base>/bin, for PATH discovery."""
    bin_dir = Path(base) / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "ghostworkflow"
    script.write_text(FAKE_WORKFLOW_SCRIPT, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP
                 | stat.S_IXOTH)
    return bin_dir


def make_fake_checkout(base: Path) -> Path:
    """A fake ghostworkflow checkout at <base>/ghostworkflow with
    src/ghostworkflow/__main__.py, for workflow-home discovery."""
    pkg = Path(base) / "ghostworkflow" / "src" / "ghostworkflow"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    body = FAKE_WORKFLOW_SCRIPT.split("\n", 1)[1]  # drop the shebang
    (pkg / "__main__.py").write_text(body, encoding="utf-8")
    return Path(base)


def prepend_path(monkeypatch, directory: Path) -> None:
    monkeypatch.setenv(
        "PATH", str(directory) + os.pathsep + os.environ.get("PATH", ""))


def wait_for(predicate, timeout: float = 15.0, interval: float = 0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
