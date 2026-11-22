"""Evidence contract support: verification levels and report validation.

The shared evidence contract (EVIDENCE_CONTRACT_DRAFT.md) requires a
report to identify its project, task, commit or tree hash, tool
version, timestamp, verdict and verification level. This module owns
the level ordering and a focused, stdlib-only validator for the
workflow report. The validator mirrors schemas/workflow-report.
schema.json; it is deliberately NOT a general JSON-Schema engine -
it checks exactly the fields and types that schema declares.
"""

from __future__ import annotations

import json
from pathlib import Path

# Verification levels, weakest to strongest (contract enum).
LEVELS = ["none", "static-analysis", "tests-executed", "live-agent"]
LEVEL_RANK = {level: rank for rank, level in enumerate(LEVELS)}

VERDICTS = ("ok", "attention", "failed")
STEP_STATUSES = ("ok", "attention", "failed", "skipped")
PROVENANCE = "live"

# Top-level fields the workflow report must carry (mirrors the
# "required" list in schemas/workflow-report.schema.json).
REQUIRED_FIELDS = [
    "project",
    "task",
    "commit",
    "tree_hash",
    "tree_hash_source",
    "tool",
    "tool_version",
    "engines",
    "timestamp",
    "run_id",
    "verdict",
    "verification_level",
    "provenance",
    "steps",
]

ENGINE_NAMES = ("ghostslice", "ghostverify", "ghostbench", "ghostconsole")

STEP_REQUIRED_FIELDS = [
    "name",
    "status",
    "argv",
    "exit_code",
    "started_utc",
    "finished_utc",
    "duration_s",
    "reports",
    "verdict",
    "verification_level",
    "detail",
]


def strongest(levels) -> str:
    """Strongest verification level from an iterable of level strings.

    Unknown or missing values count as "none": a level is only ever
    as strong as a value the contract actually defines.
    """
    best = "none"
    for level in levels or []:
        if level in LEVEL_RANK and LEVEL_RANK[level] > LEVEL_RANK[best]:
            best = level
    return best


def _is_str_or_none(value) -> bool:
    return value is None or isinstance(value, str)


def _is_int_or_none(value) -> bool:
    return value is None or (isinstance(value, int)
                             and not isinstance(value, bool))


def _is_num_or_none(value) -> bool:
    return value is None or (isinstance(value, (int, float))
                             and not isinstance(value, bool))


def _schema_required() -> list | None:
    """Required-field list from the shipped schema, when findable.

    The schema lives at <repo>/schemas/workflow-report.schema.json,
    two levels above this package's src directory in a checkout. An
    installed package may not ship it; absence is not an error, the
    in-code checks below are the contract. When it IS present, its
    required list must agree with REQUIRED_FIELDS.
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "schemas" / "workflow-report.schema.json",
        Path.cwd() / "schemas" / "workflow-report.schema.json",
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                required = data.get("required")
                if isinstance(required, list):
                    return required
        except (OSError, ValueError):
            return None
    return None


def validate_report(report) -> list:
    """Return a list of validation error strings ([] means valid)."""
    errors = []
    if not isinstance(report, dict):
        return ["report is not a JSON object"]

    for field in REQUIRED_FIELDS:
        if field not in report:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors

    schema_required = _schema_required()
    if schema_required is not None and sorted(schema_required) != sorted(REQUIRED_FIELDS):
        errors.append(
            "schema required list disagrees with the validator: "
            f"schema={sorted(schema_required)} code={sorted(REQUIRED_FIELDS)}")

    project = report["project"]
    if not isinstance(project, dict):
        errors.append("project is not an object")
    else:
        if not isinstance(project.get("name"), str) or not project.get("name"):
            errors.append("project.name must be a non-empty string")
        if not isinstance(project.get("path"), str) or not project.get("path"):
            errors.append("project.path must be a non-empty string")

    if not _is_str_or_none(report["task"]):
        errors.append("task must be a string or null")
    if not _is_str_or_none(report["commit"]):
        errors.append("commit must be a string or null")
    if not _is_str_or_none(report["tree_hash"]):
        errors.append("tree_hash must be a string or null")
    if not isinstance(report["tree_hash_source"], str) \
            or not report["tree_hash_source"]:
        errors.append("tree_hash_source must be a non-empty string")

    if report["tool"] != "ghostworkflow":
        errors.append("tool must be 'ghostworkflow'")
    if not isinstance(report["tool_version"], str) \
            or not report["tool_version"]:
        errors.append("tool_version must be a non-empty string")

    engines = report["engines"]
    if not isinstance(engines, dict):
        errors.append("engines is not an object")
    else:
        for name in ENGINE_NAMES:
            entry = engines.get(name)
            if not isinstance(entry, dict):
                errors.append(f"engines.{name} missing or not an object")
                continue
            if not isinstance(entry.get("found"), bool):
                errors.append(f"engines.{name}.found must be a boolean")
            if not _is_str_or_none(entry.get("version")):
                errors.append(f"engines.{name}.version must be a string or null")
            if entry.get("how") not in ("path", "checkout", None):
                errors.append(
                    f"engines.{name}.how must be 'path', 'checkout' or null")

    if not isinstance(report["timestamp"], str) or not report["timestamp"]:
        errors.append("timestamp must be a non-empty ISO UTC string")
    if not isinstance(report["run_id"], str) or not report["run_id"]:
        errors.append("run_id must be a non-empty string")
    if report["verdict"] not in VERDICTS:
        errors.append(f"verdict must be one of {list(VERDICTS)}")
    if report["verification_level"] not in LEVEL_RANK:
        errors.append(
            f"verification_level must be one of {LEVELS}")
    if report["provenance"] != PROVENANCE:
        errors.append("provenance must be 'live'")

    steps = report["steps"]
    if not isinstance(steps, list) or not steps:
        errors.append("steps must be a non-empty array")
    else:
        for index, step in enumerate(steps):
            errors.extend(_validate_step(index, step))
    return errors


def _validate_step(index: int, step) -> list:
    errors = []
    where = f"steps[{index}]"
    if not isinstance(step, dict):
        return [f"{where} is not an object"]
    for field in STEP_REQUIRED_FIELDS:
        if field not in step:
            errors.append(f"{where} missing required field: {field}")
    if errors:
        return errors
    if not isinstance(step["name"], str) or not step["name"]:
        errors.append(f"{where}.name must be a non-empty string")
    if step["status"] not in STEP_STATUSES:
        errors.append(f"{where}.status must be one of {list(STEP_STATUSES)}")
    argv = step["argv"]
    if argv is not None and not (
            isinstance(argv, list)
            and all(isinstance(part, str) for part in argv)):
        errors.append(f"{where}.argv must be an array of strings or null")
    if not _is_int_or_none(step["exit_code"]):
        errors.append(f"{where}.exit_code must be an integer or null")
    for field in ("started_utc", "finished_utc"):
        if not _is_str_or_none(step[field]):
            errors.append(f"{where}.{field} must be a string or null")
    if not _is_num_or_none(step["duration_s"]):
        errors.append(f"{where}.duration_s must be a number or null")
    reports = step["reports"]
    if not isinstance(reports, list) \
            or not all(isinstance(path, str) for path in reports):
        errors.append(f"{where}.reports must be an array of strings")
    if not _is_str_or_none(step["verdict"]):
        errors.append(f"{where}.verdict must be a string or null")
    if step["verification_level"] not in LEVEL_RANK:
        errors.append(f"{where}.verification_level must be one of {LEVELS}")
    if not isinstance(step["detail"], str):
        errors.append(f"{where}.detail must be a string")
    return errors
