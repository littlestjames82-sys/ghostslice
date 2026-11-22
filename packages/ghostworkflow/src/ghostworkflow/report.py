"""The workflow report: assembly, validation, and writing.

One ``workflow-report.json`` per run, next to the board. The report
carries the shared evidence contract fields and is validated
against them (see evidence.py) before it is written: the CLI
refuses to write a report that fails its own validation.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .evidence import validate_report


def now_iso() -> str:
    """Current UTC time, ISO 8601, seconds precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"wf-{stamp}-{uuid.uuid4().hex[:6]}"


class ReportValidationError(Exception):
    """Raised when a report fails its own evidence validation."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass
class Step:
    """One engine step of a run, as recorded in the report."""

    name: str
    status: str = "ok"                # ok | attention | failed | skipped
    argv: list | None = None
    exit_code: int | None = None
    started_utc: str | None = None
    finished_utc: str | None = None
    duration_s: float | None = None
    reports: list = field(default_factory=list)
    verdict: str | None = None
    verification_level: str = "none"
    detail: str = ""

    def begin(self) -> None:
        self.started_utc = now_iso()
        self._clock = time.monotonic()

    def finish(self) -> None:
        self.finished_utc = now_iso()
        clock = getattr(self, "_clock", None)
        if clock is not None:
            self.duration_s = round(time.monotonic() - clock, 3)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "argv": self.argv,
            "exit_code": self.exit_code,
            "started_utc": self.started_utc,
            "finished_utc": self.finished_utc,
            "duration_s": self.duration_s,
            "reports": list(self.reports),
            "verdict": self.verdict,
            "verification_level": self.verification_level,
            "detail": self.detail,
        }


def build_report(*, project_name: str, project_path: str,
                 task: str | None, commit, tree_hash, tree_hash_source: str,
                 engines: dict, timestamp: str, run_id: str, verdict: str,
                 verification_level: str, steps: list) -> dict:
    """Assemble the report dict from a finished run's pieces."""
    return {
        "project": {"name": project_name, "path": project_path},
        "task": task,
        "commit": commit,
        "tree_hash": tree_hash,
        "tree_hash_source": tree_hash_source,
        "tool": "ghostworkflow",
        "tool_version": __version__,
        "engines": engines,
        "timestamp": timestamp,
        "run_id": run_id,
        "verdict": verdict,
        "verification_level": verification_level,
        "provenance": "live",
        "steps": [step.to_dict() for step in steps],
    }


def write_report(report: dict, path) -> Path:
    """Validate, then write the report as JSON. Refuses invalid reports."""
    errors = validate_report(report)
    if errors:
        raise ReportValidationError(errors)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return target
