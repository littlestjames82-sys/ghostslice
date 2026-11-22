"""Pipeline tests: happy paths with fake engines, one real end-to-end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import find_workflow_report
from ghostworkflow.cli import main
from ghostworkflow.evidence import validate_report

ENGINE_NAMES = ("ghostslice", "ghostverify", "ghostbench", "ghostconsole")
WORKSPACE = Path(__file__).resolve().parents[2]


def _steps_by_name(report):
    return {step["name"]: step for step in report["steps"]}


def test_happy_path_fake_engines(fake_env, empty_home, project):
    rc = main(["run", str(project), "--task", "Fix the thing",
               "--engine-home", str(empty_home)])
    assert rc == 0
    report_path = find_workflow_report(project)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert validate_report(report) == []
    assert report["verdict"] == "ok"
    assert report["provenance"] == "live"
    assert report["task"] == "Fix the thing"
    assert report["tree_hash"] == "sha256:fake-tree-hash"
    assert "bench-report" in report["tree_hash_source"]
    # No --test-command: static evidence only.
    assert report["verification_level"] == "static-analysis"

    steps = _steps_by_name(report)
    assert [s["status"] for s in report["steps"]] == ["ok"] * 4
    for step in report["steps"]:
        assert isinstance(step["argv"], list)
        assert step["exit_code"] == 0
    assert steps["verify"]["verdict"] == "sufficient"
    assert steps["bench"]["verification_level"] == "static-analysis"
    board = report_path.parent / "board.html"
    assert board.is_file()
    assert "fake board" in board.read_text(encoding="utf-8")

    engines = report["engines"]
    for name in ENGINE_NAMES:
        assert engines[name]["found"] is True
        assert engines[name]["version"] == "9.9.9"
        assert engines[name]["how"] == "path"


def test_happy_path_with_test_command(fake_env, empty_home, project):
    rc = main(["run", str(project), "--task", "Fix the thing",
               "--test-command", "python3 -m pytest -q",
               "--engine-home", str(empty_home)])
    assert rc == 0
    report = json.loads(
        find_workflow_report(project).read_text(encoding="utf-8"))
    assert validate_report(report) == []
    steps = _steps_by_name(report)
    assert steps["bench"]["verification_level"] == "tests-executed"
    assert "--run-tests" in steps["bench"]["argv"]
    assert report["verification_level"] == "tests-executed"
    # The starter task in the created corpus carries the test command.
    corpus = json.loads(
        (project / ".ghostworkflow" / "corpus.json").read_text(
            encoding="utf-8"))
    task = corpus["projects"][0]["tasks"][0]
    assert task["test_command"] == "python3 -m pytest -q"
    assert task["prompt"] == "Fix the thing"


def test_existing_corpus_is_reused(fake_env, empty_home, project):
    rc_first = main(["run", str(project), "--task", "First task",
                     "--engine-home", str(empty_home)])
    assert rc_first == 0
    corpus_path = project / ".ghostworkflow" / "corpus.json"
    before = corpus_path.read_text(encoding="utf-8")
    out_dir = project / "second-run"
    rc_second = main(["run", str(project), "--task", "Second task",
                      "--out", str(out_dir),
                      "--engine-home", str(empty_home)])
    assert rc_second == 0
    # Same corpus file, still exactly one project entry: no re-add.
    after = json.loads(corpus_path.read_text(encoding="utf-8"))
    assert len(after["projects"]) == 1
    assert corpus_path.read_text(encoding="utf-8") != "" and before
    # --out is honored: report and board live there.
    report = json.loads(
        (out_dir / "workflow-report.json").read_text(encoding="utf-8"))
    assert validate_report(report) == []
    assert (out_dir / "board.html").is_file()
    steps = _steps_by_name(report)
    assert "created" not in steps["bench"]["detail"]


def test_usage_error_for_missing_project(empty_home, tmp_path):
    rc = main(["run", str(tmp_path / "does-not-exist"),
               "--engine-home", str(empty_home)])
    assert rc == 2


# ------------------------------------------------------------ real engines

_SIBLINGS_PRESENT = all(
    (WORKSPACE / name / "src" / name / "__init__.py").is_file()
    for name in ENGINE_NAMES)


@pytest.mark.skipif(
    not _SIBLINGS_PRESENT,
    reason="one or more real engine checkouts (ghostslice, ghostverify, "
           "ghostbench, ghostconsole) are absent next to the "
           "ghostworkflow checkout")
def test_real_end_to_end(project):
    """A synthetic mini project through the REAL four sibling engines."""
    rc = main(["run", str(project),
               "--task", "Add a multiply function to calc.py",
               "--test-command", "python3 -m pytest -q"])
    # Attention (gaps predicted / a task scored down) is a completed
    # run; failure is not.
    assert rc == 0
    report_path = find_workflow_report(project)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert validate_report(report) == []
    assert report["verdict"] in ("ok", "attention")
    assert report["tree_hash"]
    board = report_path.parent / "board.html"
    assert board.is_file() and board.stat().st_size > 0

    steps = _steps_by_name(report)
    assert steps["slice"]["status"] == "ok"
    assert steps["verify"]["status"] in ("ok", "attention")
    assert steps["bench"]["status"] in ("ok", "attention")
    assert steps["console"]["status"] == "ok"
    # A --test-command was passed: the bench evidence is at least
    # static-analysis, and the contained tests make it tests-executed.
    bench_level = steps["bench"]["verification_level"]
    assert bench_level in ("static-analysis", "tests-executed")
    assert bench_level == "tests-executed"
    assert report["verification_level"] == "tests-executed"
    for name in ENGINE_NAMES:
        assert report["engines"][name]["found"] is True
        assert report["engines"][name]["how"] in ("path", "checkout")
