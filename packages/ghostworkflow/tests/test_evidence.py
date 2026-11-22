"""Evidence contract: the validator, the levels, the schema, tree hashes."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from conftest import find_workflow_report
from ghostworkflow import evidence
from ghostworkflow.cli import main
from ghostworkflow.report import ReportValidationError, write_report

SCHEMA_PATH = (Path(__file__).resolve().parents[1]
               / "schemas" / "workflow-report.schema.json")


def _valid_report():
    step = {
        "name": "slice", "status": "ok", "argv": ["ghostslice"],
        "exit_code": 0, "started_utc": "2026-10-18T00:00:00+00:00",
        "finished_utc": "2026-10-18T00:00:01+00:00", "duration_s": 1.0,
        "reports": [], "verdict": "exported",
        "verification_level": "static-analysis", "detail": "",
    }
    return {
        "project": {"name": "mini", "path": "/tmp/mini"},
        "task": "Fix the thing",
        "commit": None,
        "tree_hash": "sha256:abc",
        "tree_hash_source": "test fixture",
        "tool": "ghostworkflow",
        "tool_version": "0.1.0",
        "engines": {
            name: {"found": True, "version": "1.0.0",
                   "how": "path", "home": None}
            for name in evidence.ENGINE_NAMES
        },
        "timestamp": "2026-10-18T00:00:00+00:00",
        "run_id": "wf-test",
        "verdict": "ok",
        "verification_level": "static-analysis",
        "provenance": "live",
        "steps": [step],
    }


def test_valid_report_passes():
    assert evidence.validate_report(_valid_report()) == []


@pytest.mark.parametrize("field", evidence.REQUIRED_FIELDS)
def test_missing_top_level_field_fails(field):
    report = _valid_report()
    del report[field]
    errors = evidence.validate_report(report)
    assert any(field in error for error in errors)


@pytest.mark.parametrize("bad", [
    ("verdict", "great"),
    ("verification_level", "certified-gold"),
    ("provenance", "sample"),
    ("tool", "ghostconsole"),
    ("commit", 42),
    ("tree_hash_source", ""),
    ("timestamp", ""),
])
def test_bad_top_level_values_fail(bad):
    field, value = bad
    report = _valid_report()
    report[field] = value
    assert evidence.validate_report(report) != []


@pytest.mark.parametrize("bad_step", [
    ("status", "crashed"),
    ("verification_level", "vibes"),
    ("argv", "ghostslice export"),
    ("exit_code", "0"),
    ("reports", "manifest.json"),
])
def test_bad_step_values_fail(bad_step):
    field, value = bad_step
    report = _valid_report()
    report["steps"][0][field] = value
    assert evidence.validate_report(report) != []


def test_engines_map_must_cover_all_engines():
    report = _valid_report()
    del report["engines"]["ghostbench"]
    assert evidence.validate_report(report) != []


def test_strongest_level_ordering():
    assert evidence.strongest([]) == "none"
    assert evidence.strongest(["none", "none"]) == "none"
    assert evidence.strongest(
        ["static-analysis", "none"]) == "static-analysis"
    assert evidence.strongest(
        ["static-analysis", "tests-executed"]) == "tests-executed"
    assert evidence.strongest(
        ["tests-executed", "live-agent", "static-analysis"]) == "live-agent"
    # Unknown values never inflate a level.
    assert evidence.strongest(["certified-gold"]) == "none"


def test_schema_file_matches_validator():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert sorted(schema["required"]) == sorted(evidence.REQUIRED_FIELDS)
    step_schema = schema["$defs"]["step"]
    assert sorted(step_schema["required"]) == sorted(
        evidence.STEP_REQUIRED_FIELDS)
    assert schema["properties"]["verification_level"]["enum"] == evidence.LEVELS
    assert schema["properties"]["verdict"]["enum"] == list(evidence.VERDICTS)


def test_write_report_refuses_invalid_report(tmp_path):
    target = tmp_path / "workflow-report.json"
    bad = _valid_report()
    bad["verdict"] = "great"
    with pytest.raises(ReportValidationError):
        write_report(bad, target)
    assert not target.exists()


def test_tree_hash_never_invented(
        fake_env, empty_home, project, monkeypatch):
    """When neither bench rows nor the corpus carry a hash, it is null."""
    monkeypatch.setenv("FAKE_BENCH_NOTREE", "1")
    rc = main(["run", str(project), "--task", "Fix the thing",
               "--engine-home", str(empty_home)])
    assert rc == 0
    report = json.loads(
        find_workflow_report(project).read_text(encoding="utf-8"))
    assert report["tree_hash"] is None
    assert report["commit"] is None
    assert "unavailable" in report["tree_hash_source"]
    assert evidence.validate_report(report) == []


def test_report_copies_are_independent():
    report = _valid_report()
    clone = copy.deepcopy(report)
    clone["steps"][0]["status"] = "failed"
    assert evidence.validate_report(report) == []
