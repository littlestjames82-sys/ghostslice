"""Starting ghostworkflow runs, in the background, one per project.

The app never runs an engine itself. The only thing it ever
executes is the ghostworkflow CLI, located the same way
ghostworkflow locates its engines:

1. an explicit workflow home (--workflow-home or
   GHOSTCONSOLE_APP_WORKFLOW_HOME): the ghostworkflow checkout
   itself, or a directory containing one;
2. a `ghostworkflow` console script on PATH;
3. a sibling checkout at ~/workspace/ghostworkflow (or next to this
   app's own checkout).

A checkout is invoked as ``python3 -m ghostworkflow`` with its
``src/`` on PYTHONPATH. Run state is in-memory only in v0.1: the
durable record of a run is the workflow-report.json the workflow
wrote into the project, which the app re-reads from disk.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import store

WORKFLOW_HOME_ENV = "GHOSTCONSOLE_APP_WORKFLOW_HOME"


class RunInProgress(Exception):
    """A run is already active for this project."""


class WorkflowNotFound(Exception):
    """The ghostworkflow CLI could not be located."""


def _checkout_argv(checkout: Path) -> list[str] | None:
    """Argv prefix for running a checkout tree as a module, or None
    when the directory is not a ghostworkflow checkout."""
    src = checkout / "src"
    if (src / "ghostworkflow" / "__main__.py").is_file():
        return [sys.executable, "-m", "ghostworkflow"]
    return None


def _resolve_home(home: str) -> tuple[list[str], dict, str] | None:
    """Resolve a workflow home: the checkout itself, or a directory
    containing a `ghostworkflow/` checkout."""
    root = Path(home).expanduser()
    for candidate in (root, root / "ghostworkflow"):
        argv = _checkout_argv(candidate)
        if argv is not None:
            env = {"PYTHONPATH": str(candidate / "src")}
            return argv, env, f"checkout at {candidate}"
    return None


def _candidate_checkouts() -> list[Path]:
    candidates: list[Path] = []
    # Sibling of this app's own checkout: <workspace>/ghostconsole-app
    # sits next to <workspace>/ghostworkflow in the studio layout.
    checkout_root = Path(__file__).resolve().parents[2]
    candidates.append(checkout_root.parent / "ghostworkflow")
    candidates.append(Path.home() / "workspace" / "ghostworkflow")
    seen: list[Path] = []
    for c in candidates:
        if c not in seen:
            seen.append(c)
    return seen


def find_workflow(workflow_home: str | None = None) -> tuple[list[str], dict, str]:
    """Locate the ghostworkflow CLI.

    Returns (argv_prefix, extra_env, description). Raises
    WorkflowNotFound naming what was searched."""
    home = workflow_home or os.environ.get(WORKFLOW_HOME_ENV)
    if home:
        resolved = _resolve_home(home)
        if resolved is None:
            raise WorkflowNotFound(
                f"no ghostworkflow checkout found under workflow home: {home}"
            )
        return resolved
    script = shutil.which("ghostworkflow")
    if script:
        return [script], {}, f"PATH script {script}"
    for candidate in _candidate_checkouts():
        argv = _checkout_argv(candidate)
        if argv is not None:
            env = {"PYTHONPATH": str(candidate / "src")}
            return argv, env, f"checkout at {candidate}"
    searched = ", ".join(str(c) for c in _candidate_checkouts())
    raise WorkflowNotFound(
        "ghostworkflow not found on PATH and no checkout at: " + searched
    )


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunRecord:
    project: str
    task: str | None
    status: str = "running"  # running | done | error
    argv: list[str] = field(default_factory=list)
    exit_code: int | None = None
    run_id: str | None = None  # run id stated in the workflow report
    run_dir: str | None = None  # directory name under .ghostworkflow/
    started_utc: str = ""
    finished_utc: str | None = None
    error: str | None = None
    output_tail: str = ""


class Runner:
    """Tracks at most one active run per project."""

    def __init__(self, workflow_home: str | None = None,
                 engine_home: str | None = None):
        self.workflow_home = workflow_home
        self.engine_home = engine_home
        self._lock = threading.Lock()
        self._runs: dict[str, RunRecord] = {}

    def is_running(self, project: str) -> bool:
        with self._lock:
            record = self._runs.get(project)
            return record is not None and record.status == "running"

    def status(self, project: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(project)

    def start(self, project: str, task: str | None,
              test_command: str | None) -> RunRecord:
        """Start `ghostworkflow run` for a project in a thread.

        Raises RunInProgress when the project already has an active
        run, and WorkflowNotFound when the CLI cannot be located."""
        with self._lock:
            existing = self._runs.get(project)
            if existing is not None and existing.status == "running":
                raise RunInProgress(
                    f"a workflow run is already running for {project}"
                )
        argv_prefix, extra_env, _how = find_workflow(self.workflow_home)
        argv = list(argv_prefix) + ["run", project]
        if task:
            argv += ["--task", task]
        if test_command:
            argv += ["--test-command", test_command]
        if self.engine_home:
            argv += ["--engine-home", self.engine_home]
        record = RunRecord(project=project, task=task, argv=argv,
                           started_utc=_utcnow())
        with self._lock:
            self._runs[project] = record
        before = {r["run_id"] for r in store.list_runs(project)}
        before_dirs = _run_dir_names(project)
        thread = threading.Thread(
            target=self._run_to_completion,
            args=(record, argv, extra_env, before, before_dirs),
            daemon=True,
        )
        thread.start()
        return record

    def _run_to_completion(self, record: RunRecord, argv: list[str],
                           extra_env: dict, before_ids: set,
                           before_dirs: set) -> None:
        env = dict(os.environ)
        for key, value in extra_env.items():
            if key == "PYTHONPATH" and env.get("PYTHONPATH"):
                env["PYTHONPATH"] = value + os.pathsep + env["PYTHONPATH"]
            else:
                env[key] = value
        try:
            proc = subprocess.run(
                argv, env=env, capture_output=True, text=True,
            )
            record.exit_code = proc.returncode
            record.output_tail = ((proc.stdout or "") + (proc.stderr or ""))[-2000:]
            record.status = "done"
        except OSError as exc:
            record.status = "error"
            record.error = f"could not start ghostworkflow: {exc}"
        finally:
            record.finished_utc = _utcnow()
            self._attach_run(record, before_dirs)

    def _attach_run(self, record: RunRecord, before_dirs: set) -> None:
        """Find the run directory this invocation produced: a
        .ghostworkflow subdirectory that was not there before and
        now holds a workflow report."""
        base = store.workflow_dir(record.project)
        try:
            entries = sorted(base.iterdir())
        except OSError:
            return
        best: tuple[str, dict] | None = None
        for entry in entries:
            if not entry.is_dir() or entry.name in before_dirs:
                continue
            report = store._read_report(entry)
            if report is None:
                continue
            stamp = report.get("timestamp") or ""
            if best is None or stamp >= (best[1].get("timestamp") or ""):
                best = (entry.name, report)
        if best is not None:
            record.run_dir = best[0]
            record.run_id = best[1].get("run_id") or best[0]


def _run_dir_names(project: str) -> set:
    base = store.workflow_dir(project)
    try:
        return {e.name for e in base.iterdir() if e.is_dir()}
    except OSError:
        return set()
