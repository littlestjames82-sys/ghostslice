"""Project registry and read-only access to workflow run evidence.

The registry is a JSON file at ``<app home>/projects.json`` where the
app home is ``$GHOSTCONSOLE_APP_HOME`` or ``~/.ghostconsole-app``.
It stores nothing but the absolute paths the user registered.

Run evidence is read, never written: a run is a directory
``<project>/.ghostworkflow/<run-id>/`` holding the
``workflow-report.json`` ghostworkflow wrote and the ``board.html``
GhostConsole rendered. Every lookup that turns a user-supplied
run id or project path into a filesystem path goes through the
containment checks here, so a crafted value cannot escape the
project's ``.ghostworkflow/`` directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_HOME_ENV = "GHOSTCONSOLE_APP_HOME"
REGISTRY_NAME = "projects.json"
WORKFLOW_DIR = ".ghostworkflow"
REPORT_NAME = "workflow-report.json"
BOARD_NAME = "board.html"


class StoreError(Exception):
    """A user-facing registry or lookup problem (bad path, bad id)."""


def app_home() -> Path:
    """The app's state directory, honoring GHOSTCONSOLE_APP_HOME."""
    override = os.environ.get(APP_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".ghostconsole-app"


def registry_path() -> Path:
    return app_home() / REGISTRY_NAME


def _load_registry() -> list[str]:
    """Registered project paths. A missing or corrupt registry reads
    as empty: the app must start and explain itself, never crash on a
    file the user (or a crash mid-write) left behind."""
    path = registry_path()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    projects = data.get("projects")
    if not isinstance(projects, list):
        return []
    return [p for p in projects if isinstance(p, str) and p]


def _save_registry(projects: list[str]) -> None:
    home = app_home()
    home.mkdir(parents=True, exist_ok=True)
    payload = {"projects": projects}
    tmp = registry_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(registry_path())


def list_projects() -> list[str]:
    """Registered project paths, in registration order."""
    return list(_load_registry())


def is_registered(project: str) -> bool:
    return _canonical(project) in {_canonical(p) for p in _load_registry()}


def _canonical(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def add_project(path: str) -> str:
    """Register a project directory. Returns its canonical absolute
    path. Raises StoreError for anything that is not an existing
    directory, or that is already registered."""
    if not path or not path.strip():
        raise StoreError("project path is empty")
    candidate = Path(_canonical(path.strip()))
    if not candidate.exists():
        raise StoreError(f"no such directory: {path}")
    if not candidate.is_dir():
        raise StoreError(f"not a directory: {path}")
    canonical = str(candidate)
    projects = _load_registry()
    if canonical in projects:
        raise StoreError(f"already registered: {canonical}")
    projects.append(canonical)
    _save_registry(projects)
    return canonical


def remove_project(path: str) -> str:
    """Unregister a project. Its files are never touched. Raises
    StoreError when the path is not registered."""
    canonical = _canonical(path) if path else ""
    projects = _load_registry()
    if canonical not in projects:
        raise StoreError(f"not registered: {path}")
    projects.remove(canonical)
    _save_registry(projects)
    return canonical


# --- Run evidence (read-only) ---------------------------------------


def workflow_dir(project: str) -> Path:
    return Path(project) / WORKFLOW_DIR


def _validate_run_id(run_id: str) -> str:
    """Run ids are single path components. Anything carrying a
    separator, dot segment, or NUL is refused before it reaches the
    filesystem."""
    if not run_id or run_id in (".", ".."):
        raise StoreError("invalid run id")
    if "/" in run_id or "\\" in run_id or "\x00" in run_id:
        raise StoreError("invalid run id")
    if run_id.startswith("."):
        raise StoreError("invalid run id")
    return run_id


def run_dir(project: str, run_id: str) -> Path:
    """Resolve <project>/.ghostworkflow/<run-id> and prove the result
    stays inside the project's .ghostworkflow directory, symlinks
    included."""
    _validate_run_id(run_id)
    base = Path(os.path.realpath(workflow_dir(project)))
    candidate = Path(os.path.realpath(base / run_id))
    if candidate != base and base not in candidate.parents:
        raise StoreError("run path escapes the workflow directory")
    return candidate


def _read_report(run_directory: Path) -> dict | None:
    try:
        data = json.loads((run_directory / REPORT_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def summarize_report(report: dict, directory_name: str) -> dict:
    """The fields the UI shows for one run, taken only from the
    report itself. A missing field stays missing (None), never
    invented."""
    return {
        "run_id": report.get("run_id") or directory_name,
        "dir": directory_name,
        "timestamp": report.get("timestamp"),
        "task": report.get("task"),
        "verdict": report.get("verdict"),
        "verification_level": report.get("verification_level"),
        "tool_version": report.get("tool_version"),
    }


def list_runs(project: str) -> list[dict]:
    """All runs for a project, newest first by report timestamp.
    Directories without a readable workflow-report.json are skipped:
    a half-written or foreign directory is not a run."""
    base = workflow_dir(project)
    runs: list[dict] = []
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        report = _read_report(entry)
        if report is None:
            continue
        runs.append(summarize_report(report, entry.name))
    runs.sort(key=lambda r: (r["timestamp"] or "", r["run_id"]), reverse=True)
    return runs


def latest_run(project: str) -> dict | None:
    runs = list_runs(project)
    return runs[0] if runs else None


def load_report(project: str, run_id: str) -> dict | None:
    """The full workflow report for one run, or None when the run or
    its report does not exist. Raises StoreError on a crafted id."""
    directory = run_dir(project, run_id)
    if not directory.is_dir():
        return None
    return _read_report(directory)


def board_path(project: str, run_id: str) -> Path | None:
    """Path to a run's board.html, contained exactly like run_dir,
    or None when the run has no board."""
    directory = run_dir(project, run_id)
    board = directory / BOARD_NAME
    return board if board.is_file() else None
