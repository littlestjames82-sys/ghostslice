"""The workflow itself: Slice -> Verify -> Bench -> Console.

Each engine is invoked through its CLI and writes its own native
reports; this module only sequences them, records what happened,
and derives the run's verdict honestly:

- A step FAILS when its engine exits nonzero (outside the verdicts
  an engine states in its own report), cannot be found, times out,
  or its expected report is missing or unreadable. A failed step
  stops the engine sequence: later engine steps are recorded as
  skipped, the Console render is still attempted, and the workflow
  report is still written. The run exits 1.
- A gaps_found Verify verdict and a Bench run with failing tasks
  are recorded outcomes (step status "attention"), not failures.
  The run's verdict is "attention" and it exits 0.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import adapters
from .evidence import LEVEL_RANK, strongest
from .report import Step, build_report, new_run_id, now_iso, write_report

DEFAULT_TIMEOUT = 600


def _tail(text: str, limit: int = 300) -> str:
    text = (text or "").strip()
    return text[-limit:] if text else ""


def _read_json(path: Path):
    """(object, error) - exactly one of the two is not None."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # missing or corrupt is a state, not a crash
        return None, str(exc)


def _not_found_detail(name: str, engine_home) -> str:
    homes = ", ".join(str(home) for home in adapters.engine_homes(engine_home))
    return (f"engine {name} not found: no console script on PATH and no "
            f"checkout tree under the engine home(s) searched: {homes}")


def _skipped(step_name: str, failed_step: str) -> Step:
    step = Step(name=step_name, status="skipped")
    step.detail = f"skipped: step '{failed_step}' failed"
    return step


def _project_id(project: Path) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", project.name.lower()).strip("-")
    return slug or "project"


# ---------------------------------------------------------------- Slice

def _step_slice(handle, project: Path, task, bundle_dir: Path,
                timeout: int, engine_home=None) -> Step:
    step = Step(name="slice", verification_level="static-analysis")
    if not handle.found:
        step.status = "failed"
        step.detail = _not_found_detail("ghostslice", engine_home)
        return step
    if task:
        args = ["task", str(project), "--task", task, "-o", str(bundle_dir)]
    else:
        args = ["export", str(project), "-o", str(bundle_dir)]
    step.begin()
    result = adapters.run_argv(handle, args, timeout=timeout)
    step.finish()
    step.argv = result.argv
    step.exit_code = result.exit_code
    if result.timed_out:
        step.status = "failed"
        step.detail = f"ghostslice timed out after {timeout}s"
        return step
    manifest_path = bundle_dir / "manifest.json"
    manifest, error = _read_json(manifest_path)
    if result.exit_code != 0:
        step.status = "failed"
        step.detail = (f"ghostslice exited {result.exit_code}: "
                       f"{_tail(result.stderr) or _tail(result.stdout)}")
        return step
    if error is not None or not isinstance(manifest, dict):
        step.status = "failed"
        step.detail = (f"ghostslice exited 0 but its bundle manifest is "
                       f"missing or unreadable: {error}")
        return step
    step.status = "ok"
    step.verdict = "exported"
    step.reports = [str(manifest_path)]
    files = manifest.get("files")
    count = len(files) if isinstance(files, list) else None
    original = manifest.get("total_original_tokens")
    sliced = manifest.get("total_sliced_tokens")
    parts = ["bundle written"]
    if count is not None:
        parts.append(f"{count} file(s)")
    if isinstance(original, int) and isinstance(sliced, int):
        parts.append(f"{original} -> {sliced} estimated tokens")
    step.detail = "; ".join(parts)
    return step


# ---------------------------------------------------------------- Verify

def _step_verify(handle, project: Path, task, bundle_dir: Path,
                 verify_dir: Path, timeout: int, engine_home=None) -> Step:
    step = Step(name="verify", verification_level="static-analysis")
    if not handle.found:
        step.status = "failed"
        step.detail = _not_found_detail("ghostverify", engine_home)
        return step
    args = ["pre", str(project), str(bundle_dir)]
    if task:
        args += ["--task", task]
    args += ["--out-dir", str(verify_dir)]
    step.begin()
    result = adapters.run_argv(handle, args, timeout=timeout)
    step.finish()
    step.argv = result.argv
    step.exit_code = result.exit_code
    if result.timed_out:
        step.status = "failed"
        step.detail = f"ghostverify timed out after {timeout}s"
        return step
    report_path = verify_dir / "verify-report.json"
    report, error = _read_json(report_path)
    if error is not None or not isinstance(report, dict):
        step.status = "failed"
        step.detail = (f"ghostverify exited {result.exit_code} and no "
                       f"readable verify-report.json was produced: {error}")
        return step
    step.reports = [str(report_path)]
    verdict = report.get("verdict")
    step.verdict = verdict if isinstance(verdict, str) else None
    if verdict == "sufficient":
        if result.exit_code == 0:
            step.status = "ok"
            step.detail = "bundle sufficient for the task (static check)"
        else:
            step.status = "failed"
            step.detail = (f"ghostverify reported 'sufficient' but exited "
                           f"{result.exit_code}; not trusted as a pass")
    elif verdict == "gaps_found":
        step.status = "attention"
        gaps = report.get("gaps")
        count = len(gaps) if isinstance(gaps, list) else None
        step.detail = ("bundle has gaps for the task (static check)"
                       + (f": {count} gap(s) recorded" if count else ""))
    elif verdict == "could_not_verify":
        step.status = "failed"
        step.detail = "ghostverify could not verify the bundle (never a pass)"
    else:
        step.status = "failed"
        step.detail = f"unrecognized ghostverify verdict: {verdict!r}"
    return step


# ---------------------------------------------------------------- Bench

def _corpus_entry_for(corpus_path: Path, project: Path):
    """(data, entry) when a corpus file records this project, else (None, None)."""
    data, error = _read_json(corpus_path)
    if error is not None or not isinstance(data, dict):
        return None, None
    projects = data.get("projects")
    if not isinstance(projects, list):
        return None, None
    for entry in projects:
        if not isinstance(entry, dict):
            continue
        raw_path = entry.get("path")
        if not isinstance(raw_path, str):
            continue
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = corpus_path.parent / candidate
        try:
            if candidate.resolve() == project:
                return data, entry
        except OSError:
            continue
    return None, None


def _find_corpus(project: Path):
    """(corpus_path, data, entry) for an existing corpus, else (None,)*3."""
    candidates = [project / ".ghostworkflow" / "corpus.json",
                  project / "corpus.json"]
    for candidate in candidates:
        if candidate.is_file():
            data, entry = _corpus_entry_for(candidate, project)
            if entry is not None:
                return candidate, data, entry
    return None, None, None


def _step_bench(handle, project: Path, task, test_command,
                bench_dir: Path, timeout: int, engine_home=None):
    """Run the Bench step; also return (commit, tree_hash, source)."""
    step = Step(name="bench")
    tree_info = (None, None,
                 "unavailable: ghostbench did not run, so no corpus or "
                 "bench report exists to take a tree hash from")
    if not handle.found:
        step.status = "failed"
        step.detail = _not_found_detail("ghostbench", engine_home)
        return step, tree_info

    corpus_path, data, entry = _find_corpus(project)
    created = False
    if entry is None:
        corpus_path = project / ".ghostworkflow" / "corpus.json"
        corpus_path.parent.mkdir(parents=True, exist_ok=True)
        args = ["add", str(corpus_path), "--project", str(project),
                "--id", _project_id(project), "--name", "ghostworkflow"]
        step.begin()
        result = adapters.run_argv(handle, args, timeout=timeout)
        if result.timed_out or result.exit_code != 0:
            step.finish()
            step.argv = result.argv
            step.exit_code = result.exit_code
            step.status = "failed"
            step.detail = (f"ghostbench add timed out after {timeout}s"
                           if result.timed_out else
                           f"ghostbench add exited {result.exit_code}: "
                           f"{_tail(result.stderr) or _tail(result.stdout)}")
            return step, tree_info
        created = True
        data, entry = _corpus_entry_for(corpus_path, project)
        if entry is None:
            step.finish()
            step.argv = result.argv
            step.exit_code = result.exit_code
            step.status = "failed"
            step.detail = "ghostbench add ran but the corpus does not record this project"
            return step, tree_info

    # A starter task when the recorded project has none yet.
    if not entry.get("tasks"):
        starter = {
            "id": "wf-001-starter-task",
            "prompt": task or f"Work on the {project.name} project",
            "expected_files": [],
            "expected_symbols": [],
            "recorded_patch": None,
            "test_command": test_command,
        }
        entry["tasks"] = [starter]
        corpus_path.write_text(json.dumps(data, indent=2) + "\n",
                               encoding="utf-8")

    args = ["run", str(corpus_path), "--out", str(bench_dir)]
    if test_command:
        args.append("--run-tests")
    if not step.started_utc:
        step.begin()
    result = adapters.run_argv(handle, args, timeout=timeout)
    step.finish()
    step.argv = result.argv
    step.exit_code = result.exit_code
    if result.timed_out:
        step.status = "failed"
        step.detail = f"ghostbench timed out after {timeout}s"
        return step, tree_info
    report_path = bench_dir / "bench-report.json"
    report, error = _read_json(report_path)
    if result.exit_code != 0:
        step.status = "failed"
        step.detail = (f"ghostbench exited {result.exit_code}: "
                       f"{_tail(result.stderr) or _tail(result.stdout)}")
        return step, tree_info
    if error is not None or not isinstance(report, dict):
        step.status = "failed"
        step.detail = (f"ghostbench exited 0 but bench-report.json is "
                       f"missing or unreadable: {error}")
        return step, tree_info

    step.reports = [str(report_path)]
    bench_md = bench_dir / "BENCH.md"
    if bench_md.is_file():
        step.reports.append(str(bench_md))

    level = report.get("verification_level")
    if level not in LEVEL_RANK:
        level = "tests-executed" if test_command else "static-analysis"
    step.verification_level = level

    rows = report.get("tasks")
    rows = rows if isinstance(rows, list) else []
    totals = report.get("totals")
    totals = totals if isinstance(totals, dict) else {}
    failing = totals.get("tasks_failed")
    if not isinstance(failing, int) or isinstance(failing, bool):
        failing = totals.get("fail")
    if not isinstance(failing, int) or isinstance(failing, bool):
        failing = sum(1 for row in rows
                      if isinstance(row, dict)
                      and row.get("status") in ("fail", "failed"))

    commit = None
    tree_hash = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if tree_hash is None and isinstance(row.get("project_tree_hash"), str):
            tree_hash = row["project_tree_hash"]
        if commit is None and isinstance(row.get("project_commit"), str):
            commit = row["project_commit"]
    if tree_hash is not None:
        source = ("ghostbench bench-report.json task row "
                  "(project_tree_hash / project_commit)")
    elif isinstance(entry.get("tree_hash"), str):
        tree_hash = entry["tree_hash"]
        source = "ghostbench corpus record (tree_hash recorded by ghostbench add)"
    else:
        source = ("unavailable: neither the bench report rows nor the "
                  "corpus record carries a commit or tree hash")
    tree_info = (commit, tree_hash, source)

    if failing and failing > 0:
        step.status = "attention"
        step.verdict = "tasks_failed"
        step.detail = (f"bench run recorded {failing} failing task(s) "
                       f"(level: {level})"
                       + ("; corpus created by this run" if created else ""))
    else:
        step.status = "ok"
        step.verdict = "ok"
        step.detail = (f"bench run complete, no failing tasks "
                       f"(level: {level})"
                       + ("; corpus created by this run" if created else ""))
    return step, tree_info


# ---------------------------------------------------------------- Console

def _step_console(handle, project: Path, board_path: Path,
                  timeout: int, engine_home=None) -> Step:
    step = Step(name="console")
    if not handle.found:
        step.status = "failed"
        step.detail = _not_found_detail("ghostconsole", engine_home)
        return step
    args = ["build", str(project), "-o", str(board_path)]
    step.begin()
    result = adapters.run_argv(handle, args, timeout=timeout)
    step.finish()
    step.argv = result.argv
    step.exit_code = result.exit_code
    if result.timed_out:
        step.status = "failed"
        step.detail = f"ghostconsole timed out after {timeout}s"
    elif result.exit_code == 0 and board_path.is_file():
        step.status = "ok"
        step.verdict = "rendered"
        step.reports = [str(board_path)]
        step.detail = "board rendered from the reports on disk"
    else:
        step.status = "failed"
        step.detail = (f"ghostconsole exited {result.exit_code} or wrote "
                       f"no board: {_tail(result.stderr) or _tail(result.stdout)}")
    return step


# ---------------------------------------------------------------- Run

def run_workflow(project, task=None, test_command=None, out=None,
                 engine_home=None, timeout=DEFAULT_TIMEOUT):
    """Run the full workflow. Returns (report, exit_code, report_path)."""
    project = Path(project).expanduser().resolve()
    run_id = new_run_id()
    started = now_iso()
    out_dir = (Path(out).expanduser().resolve() if out
               else project / ".ghostworkflow" / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir = out_dir / "bundle"
    verify_dir = out_dir / "verify"
    bench_dir = out_dir / "bench"
    board_path = out_dir / "board.html"
    report_path = out_dir / "workflow-report.json"

    handles = adapters.discover_engines(engine_home=engine_home)
    engines_map = {name: handle.describe()
                   for name, handle in handles.items()}

    steps = []
    commit = tree_hash = None
    tree_source = ("unavailable: the slice manifest carries no commit or "
                   "tree hash and ghostbench did not run")

    slice_step = _step_slice(handles["ghostslice"], project, task,
                             bundle_dir, timeout, engine_home=engine_home)
    steps.append(slice_step)
    failed_at = "slice" if slice_step.status == "failed" else None

    if failed_at:
        steps.append(_skipped("verify", failed_at))
    else:
        verify_step = _step_verify(handles["ghostverify"], project, task,
                                   bundle_dir, verify_dir, timeout,
                                   engine_home=engine_home)
        steps.append(verify_step)
        if verify_step.status == "failed":
            failed_at = "verify"

    if failed_at:
        steps.append(_skipped("bench", failed_at))
    else:
        bench_step, tree_info = _step_bench(
            handles["ghostbench"], project, task, test_command,
            bench_dir, timeout, engine_home=engine_home)
        steps.append(bench_step)
        commit, tree_hash, tree_source = tree_info
        if bench_step.status == "failed":
            failed_at = "bench"

    console_step = _step_console(handles["ghostconsole"], project,
                                 board_path, timeout, engine_home=engine_home)
    steps.append(console_step)

    for step in steps:
        if step.status == "failed":
            # A failed step produced no evidence, whatever it attempted.
            step.verification_level = "none"

    any_failed = any(step.status == "failed" for step in steps)
    any_attention = any(step.status == "attention" for step in steps)
    if any_failed:
        verdict, exit_code = "failed", 1
    elif any_attention:
        verdict, exit_code = "attention", 0
    else:
        verdict, exit_code = "ok", 0

    level = strongest(step.verification_level for step in steps
                      if step.status in ("ok", "attention"))
    report = build_report(
        project_name=project.name, project_path=str(project), task=task,
        commit=commit, tree_hash=tree_hash, tree_hash_source=tree_source,
        engines=engines_map, timestamp=started, run_id=run_id,
        verdict=verdict, verification_level=level, steps=steps)
    write_report(report, report_path)
    return report, exit_code, report_path
