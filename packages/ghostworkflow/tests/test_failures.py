"""Failure semantics: attention is not failure, failure is honest."""

from __future__ import annotations

import json

from conftest import FAKES, find_workflow_report
from ghostworkflow.cli import main
from ghostworkflow.evidence import validate_report


def _load_report(project):
    return json.loads(
        find_workflow_report(project).read_text(encoding="utf-8"))


def _steps(report):
    return {step["name"]: step for step in report["steps"]}


def test_verify_gaps_found_is_attention_not_failure(
        fake_env, empty_home, project, monkeypatch):
    monkeypatch.setenv("FAKE_VERIFY_VERDICT", "gaps_found")
    rc = main(["run", str(project), "--task", "Fix the thing",
               "--engine-home", str(empty_home)])
    assert rc == 0
    report = _load_report(project)
    assert validate_report(report) == []
    assert report["verdict"] == "attention"
    steps = _steps(report)
    assert steps["verify"]["status"] == "attention"
    assert steps["verify"]["verdict"] == "gaps_found"
    assert steps["verify"]["exit_code"] == 1  # the engine's own code, recorded
    # The run continues past an attention outcome.
    assert steps["bench"]["status"] == "ok"
    assert steps["console"]["status"] == "ok"


def test_verify_could_not_verify_is_failure(
        fake_env, empty_home, project, monkeypatch):
    monkeypatch.setenv("FAKE_VERIFY_VERDICT", "could_not_verify")
    rc = main(["run", str(project), "--task", "Fix the thing",
               "--engine-home", str(empty_home)])
    assert rc == 1
    report = _load_report(project)
    assert validate_report(report) == []
    assert report["verdict"] == "failed"
    steps = _steps(report)
    assert steps["verify"]["status"] == "failed"
    assert steps["bench"]["status"] == "skipped"
    assert steps["console"]["status"] == "ok"  # still attempted


def test_slice_failure_skips_engines_but_still_renders(
        fake_env, empty_home, project, monkeypatch):
    monkeypatch.setenv("FAKE_SLICE_FAIL", "1")
    rc = main(["run", str(project), "--task", "Fix the thing",
               "--engine-home", str(empty_home)])
    assert rc == 1
    report_path = find_workflow_report(project)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert validate_report(report) == []
    assert report["verdict"] == "failed"
    steps = _steps(report)
    assert steps["slice"]["status"] == "failed"
    assert steps["slice"]["exit_code"] == 3
    assert steps["verify"]["status"] == "skipped"
    assert steps["bench"]["status"] == "skipped"
    assert steps["console"]["status"] == "ok"  # still attempted
    assert (report_path.parent / "board.html").is_file()
    # Nothing was measured: the level must not claim static evidence.
    assert report["verification_level"] == "none"


def test_bench_nonzero_exit_is_failure(
        fake_env, empty_home, project, monkeypatch):
    monkeypatch.setenv("FAKE_BENCH_FAIL", "1")
    rc = main(["run", str(project), "--task", "Fix the thing",
               "--engine-home", str(empty_home)])
    assert rc == 1
    report = _load_report(project)
    assert validate_report(report) == []
    steps = _steps(report)
    assert steps["bench"]["status"] == "failed"
    assert steps["console"]["status"] == "ok"  # still attempted
    assert report["verdict"] == "failed"


def test_bench_failing_tasks_are_attention(
        fake_env, empty_home, project, monkeypatch):
    monkeypatch.setenv("FAKE_BENCH_FAILING", "2")
    rc = main(["run", str(project), "--task", "Fix the thing",
               "--engine-home", str(empty_home)])
    assert rc == 0
    report = _load_report(project)
    assert report["verdict"] == "attention"
    steps = _steps(report)
    assert steps["bench"]["status"] == "attention"
    assert steps["bench"]["verdict"] == "tasks_failed"


def test_verify_report_missing_is_failure(
        fake_env, empty_home, project, monkeypatch):
    monkeypatch.setenv("FAKE_VERIFY_NOREPORT", "1")
    rc = main(["run", str(project), "--task", "Fix the thing",
               "--engine-home", str(empty_home)])
    assert rc == 1
    report = _load_report(project)
    steps = _steps(report)
    assert steps["verify"]["status"] == "failed"
    assert "verify-report.json" in steps["verify"]["detail"]


def test_missing_engine_is_an_honest_failed_step(
        make_fake_bin, empty_home, project, monkeypatch):
    # Every engine except ghostconsole is available as a fake.
    bin_dir = make_fake_bin(
        [name for name in FAKES if name != "ghostconsole"])
    # PATH keeps /usr/bin:/bin so the fakes' python3 shebang resolves,
    # but no ghostconsole script exists in any of these directories.
    monkeypatch.setenv(
        "PATH", str(bin_dir) + ":/usr/bin:/bin")
    monkeypatch.delenv("GHOSTWORKFLOW_ENGINE_HOME", raising=False)
    rc = main(["run", str(project), "--task", "Fix the thing",
               "--engine-home", str(empty_home)])
    assert rc == 1
    report = _load_report(project)
    assert validate_report(report) == []
    steps = _steps(report)
    assert steps["console"]["status"] == "failed"
    assert "not found" in steps["console"]["detail"]
    assert report["engines"]["ghostconsole"]["found"] is False
    assert report["engines"]["ghostconsole"]["version"] is None
    # The other steps still ran; the failure is only the missing engine.
    assert steps["slice"]["status"] == "ok"
    assert steps["bench"]["status"] == "ok"
