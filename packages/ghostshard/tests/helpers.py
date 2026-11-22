"""Shared helpers for the GhostShard test suite (Agent B).

The tests drive the real CLI as a subprocess, exactly as a user
would:  python -m ghostshard plan|check|export-bus ...
Core (src/**) is owned by Agent A; these tests only assert the
behaviour promised in PLAN.md against the CLI's documented schema:

  shards.json: {mode, mode_label, partial, parallel_groups,
    max_parallelism, conflicts[], shards[{id, title, task,
    owns_files, owns_symbols, shared_files_readonly, shared_symbols,
    depends_on, parallel_group, rules_fired, seam_basis, bundle,
    estimated_tokens, original_tokens, unfittable}],
    totals{estimated_tokens, original_tokens}}
  per-shard bundle: <bundle>/manifest.json {shard_id, files[
    {path, mode, original_tokens, sliced_tokens, sha256}],
    total_original_tokens, total_sliced_tokens} + PROMPT.md + files/
  bus-manifest.json: {kind: ghostbus-job-manifest, jobs[{job_id,
    bundle_path, task, depends_on, approval_class, dispatch}]}

Fixture projects: only the *.py sources are copied into the temp
project. Fixture README/TASK files are harness material: the
scanner treats .md/.txt as project text, so copying them in would
pollute the very graph being measured.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def core_available() -> bool:
    return (SRC / "ghostshard" / "cli.py").is_file()


def run_cli(args, cwd=None, timeout=120):
    """Run the GhostShard CLI; return CompletedProcess (text)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "ghostshard", *[str(a) for a in args]],
        cwd=str(cwd) if cwd else None, env=env,
        capture_output=True, text=True, timeout=timeout)


def copy_fixture_project(name: str, dest: Path, sub: str = "") -> Path:
    """Copy only the Python sources of a fixture into dest, keeping
    any package subdirectories. `sub` selects a sub-folder of the
    fixture (e.g. cycle/project, skipping cycle/plan_folder).
    Returns dest."""
    src = FIXTURES / name / sub if sub else FIXTURES / name
    dest.mkdir(parents=True, exist_ok=True)
    for py in sorted(src.rglob("*.py")):
        rel = py.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(py, target)
    return dest


def plan_project(tmp: Path, fixture: str, *, task=None, task_file=None,
                 budget=None, extra=(), sub=""):
    """Plan a fixture project into tmp/out. Returns (proc, out_dir,
    shards_json_dict_or_None)."""
    project = copy_fixture_project(fixture, tmp / "project", sub=sub)
    out = tmp / "out"
    args = ["plan", project, "-o", out]
    if task_file is not None:
        args += ["--task-file", task_file]
    else:
        args += ["--task", task if task is not None else ""]
    if budget is not None:
        args += ["--budget", budget]
    args += list(extra)
    proc = run_cli(args, cwd=tmp)
    sj = out / "shards.json"
    data = json.loads(sj.read_text(encoding="utf-8")) if sj.is_file() else None
    return proc, out, data


def check_folder(folder):
    return run_cli(["check", folder])


def load_manifest(bundle_dir: Path) -> dict:
    return json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))


def shards_by_id(plan: dict) -> dict:
    return {s["id"]: s for s in plan["shards"]}
