"""Shared helpers for the GhostRecipes test suite (Agent B).

ASSUMED CORE INTERFACE (see REPORT_B.md; if Agent A's core differs,
only the helpers in this file should need changing):

  Layout:    src/ghostrecipes/ package, run as `python -m ghostrecipes`
             with PYTHONPATH=<repo>/src, or a `ghostrecipes` binary.
  Commands (aligned to Agent A's landed cli.py, read read-only):
             ghostrecipes create --id ID --name NAME -o FILE
             ghostrecipes list [--library DIR] [--json]
             ghostrecipes show <id-or-path>
             ghostrecipes validate <path-or-id-or-folder>
             ghostrecipes export <id-or-path> -o DIR
             ghostrecipes import <pack-folder> [--library DIR]
             ghostrecipes render <id-or-path> [-o FILE] [--var k=v]
  Format:    a recipe is one JSON object in a <id>.recipe.json file:
             {id (slug), name, version (semver), description, steps,
              tags[], author, date, category, tools[], inputs[], notes}
             Steps: {id, title, kind, detail, command_hint, tools,
              gate, repeat}. Kind is one of manual / check / run /
              review / approve / note. Unknown keys are rejected, which
              is what keeps execution hooks out of the format.
             A command_hint is data text ONLY, labelled "run manually"
              when rendered: no GhostRecipes operation ever executes
              it (v0.1 central rule).

Export/render/create helpers try the documented form first, then a
small set of common alternatives, so a CLI spelling difference shows up
as one helper change, not a suite rewrite.

Tests are stdlib + pytest only, no network, writes only under tmp dirs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
EXAMPLES = REPO_ROOT / "examples"

STARTER_IDS = ["slice-marathon-loop", "audit-improve-verify",
               "creator-pitch-draft-first"]


def core_available() -> bool:
    return (SRC / "ghostrecipes" / "__main__.py").exists() or (
        shutil.which("ghostrecipes") is not None)


def require_core():
    if not core_available():
        pytest.fail("ghostrecipes core not ready: expected "
                    "src/ghostrecipes/__main__.py or a ghostrecipes "
                    "executable (Agent A core)")


def run_ghostrecipes(*args: str, stdin: str = "", cwd: Path | None = None,
                     timeout: int = 60) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if (SRC / "ghostrecipes" / "__main__.py").exists():
        env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
        cmd = [sys.executable, "-m", "ghostrecipes", *args]
    elif shutil.which("ghostrecipes"):
        cmd = ["ghostrecipes", *args]
    else:
        return subprocess.CompletedProcess(
            args=list(args), returncode=127, stdout="",
            stderr="ghostrecipes core not found")
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                          cwd=str(cwd) if cwd else None, env=env,
                          timeout=timeout)


def combined(proc) -> str:
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def validate(path: Path):
    return run_ghostrecipes("validate", str(path))


def show(path: Path):
    return run_ghostrecipes("show", str(path))


def list_dir(path: Path):
    return run_ghostrecipes("list", "--library", str(path))


def render(path: Path, out: Path | None = None):
    if out is not None:
        proc = run_ghostrecipes("render", str(path), "-o", str(out))
        if proc.returncode == 2:
            proc = run_ghostrecipes("render", str(path), "--output", str(out))
        return proc
    proc = run_ghostrecipes("render", str(path))
    if proc.returncode == 2 or "checklist" not in combined(proc).lower() \
            and "- [" not in combined(proc):
        alt = run_ghostrecipes("render", str(path), "--format", "checklist")
        if alt.returncode == 0:
            return alt
    return proc


def export(path: Path, out: Path):
    proc = run_ghostrecipes("export", str(path), "-o", str(out))
    if proc.returncode == 2:
        proc = run_ghostrecipes("export", str(path), str(out))
    if proc.returncode == 2:
        proc = run_ghostrecipes("export", str(path), "--output", str(out))
    return proc


def create(recipe_id: str, out: Path, name: str = "Weekly Review"):
    forms = [
        ("create", "--id", recipe_id, "--name", name, "-o", str(out)),
        ("create", recipe_id, "-o", str(out)),
    ]
    last = None
    for form in forms:
        last = run_ghostrecipes(*form)
        if last.returncode == 0 and (out.exists() or out.parent.exists()):
            return last
    return last


# ---------------------------------------------------------------- recipes

def valid_recipe(**overrides) -> dict:
    recipe = {
        "id": "demo-loop",
        "version": "1.0.0",
        "name": "Demo Loop",
        "description": "A small valid recipe used by the tests, "
                       "working on {{target}}.",
        "tags": ["demo"],
        "inputs": [{"name": "target", "description": "What to work on.",
                    "required": True}],
        "steps": [
            {"id": "look", "title": "Look at the target", "kind": "manual",
             "detail": "Read {{target}} in full."},
            {"id": "check", "title": "Check the result", "kind": "check",
             "detail": "Compare the result with the goal.",
             "gate": "Do not skip this step."},
        ],
        "notes": "Checked result is the output.",
    }
    recipe.update(overrides)
    return recipe


def write_recipe(base: Path, recipe: dict | None = None,
                 name: str = "demo-loop.recipe.json", raw: str | None = None) -> Path:
    path = base / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        path.write_text(raw)
    else:
        path.write_text(json.dumps(
            valid_recipe() if recipe is None else recipe, indent=2) + "\n")
    return path


@pytest.fixture()
def recipe_factory(tmp_path):
    def _make(recipe: dict | None = None, name: str = "demo-loop.recipe.json",
              raw: str | None = None) -> Path:
        return write_recipe(tmp_path, recipe=recipe, name=name, raw=raw)
    return _make


def load_example(recipe_id: str) -> dict:
    return json.loads((EXAMPLES / f"{recipe_id}.recipe.json").read_text())
