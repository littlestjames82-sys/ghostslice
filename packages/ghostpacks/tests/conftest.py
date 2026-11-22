"""Shared helpers for the GhostPacks test suite (Agent B).

ASSUMED CORE INTERFACE (see REPORT_B.md — if Agent A's core differs,
only the helpers in this file should need changing):

  Layout:    src/ghostpacks/ package, run as `python -m ghostpacks`
             with PYTHONPATH=<repo>/src (GhostSlice house layout),
             or a `ghostpacks` executable on PATH.
  Commands:  ghostpacks lint  <pack-dir>
             ghostpacks show  <pack-dir>
             ghostpacks merge <pack-dir> <project-dir> [--yes]
             ghostpacks remove <project-dir> <pack-id> [--yes]
             Without --yes the interactive commands read a yes/no
             confirmation on stdin; the helpers answer "y" by default.
             (This matches the core CLI that Agent A shipped in
             src/ghostpacks/cli.py during this build; the helpers are
             still the single place to change if it moves.)
  Pack format (per PLAN.md):
             <pack>/pack.json     manifest: id, version, kind="context",
                                  stack, ghostslice, author, date,
                                  profile_file, optional bench
             <pack>/profile.json  profile fragment in the exact
                                  .ghostslice.json schema (top-level
                                  keys: ignore, modes, model,
                                  budget_tokens, entry_points, preset,
                                  auto_shrink, redact, plugins, lint,
                                  duplicates, ci)
             bench (when scored): {"score": <number>,
                                  "report": "bench-report.json", ...}
                                  and the report file must exist.
  Merge writes <project>/.ghostslice.json and records provenance in
  <project>/.ghostslice-packs.json (the lockfile in PLAN.md).

These tests are stdlib + pytest only, make no network calls, and write
only under pytest tmp dirs.
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
PACKS_SRC = REPO_ROOT / "src"

# GhostSlice lives in the sibling checkout in this workspace. The
# round-trip test uses its real exporter so "export totals" means the
# real manifest totals, not a re-implementation.
GHOSTSLICE_SRC = Path(
    os.environ.get("GHOSTSLICE_SRC", Path.home() / "workspace" / "ghostslice" / "src")
)


# ---------------------------------------------------------------- CLI

def core_available() -> bool:
    return (PACKS_SRC / "ghostpacks" / "__main__.py").exists() or (
        shutil.which("ghostpacks") is not None
    )


def run_ghostpacks(*args: str, stdin: str = "", cwd: Path | None = None,
                   timeout: int = 60) -> subprocess.CompletedProcess:
    """Run the GhostPacks CLI. Returns a CompletedProcess even when the
    core is missing (returncode 127, explanatory stderr) so tests fail
    with a readable message instead of an import traceback."""
    env = dict(os.environ)
    if (PACKS_SRC / "ghostpacks" / "__main__.py").exists():
        env["PYTHONPATH"] = str(PACKS_SRC) + os.pathsep + env.get("PYTHONPATH", "")
        cmd = [sys.executable, "-m", "ghostpacks", *args]
    elif shutil.which("ghostpacks"):
        cmd = ["ghostpacks", *args]
    else:
        return subprocess.CompletedProcess(
            args=list(args), returncode=127, stdout="",
            stderr="ghostpacks core not found: expected "
                   "src/ghostpacks/__main__.py or a ghostpacks executable",
        )
    return subprocess.run(
        cmd, input=stdin, capture_output=True, text=True,
        cwd=str(cwd) if cwd else None, env=env, timeout=timeout,
    )


def lint(pack_dir: Path) -> subprocess.CompletedProcess:
    return run_ghostpacks("lint", str(pack_dir))


def show(pack_dir: Path) -> subprocess.CompletedProcess:
    return run_ghostpacks("show", str(pack_dir))


def merge(pack_dir: Path, project: Path, answer: str = "y\n") -> subprocess.CompletedProcess:
    return run_ghostpacks("merge", str(pack_dir), str(project), stdin=answer)


def remove(pack_id: str, project: Path, answer: str = "y\n") -> subprocess.CompletedProcess:
    return run_ghostpacks("remove", str(project), pack_id, stdin=answer)


def combined(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


# ---------------------------------------------------------------- packs

DEFAULT_FRAGMENT = {
    "ignore": ["generated/**"],
    "modes": {"src/**": "signatures"},
}


def make_pack(base: Path, *, pack_id: str = "demo-python",
              fragment: dict | None = None,
              manifest_overrides: dict | None = None,
              bench: dict | None = "unset",
              write_bench_report: bool = False,
              extra_files: dict[str, str] | None = None) -> Path:
    """Create a data-only pack folder under `base` and return its path.

    bench="unset"  -> no bench key at all (an unscored pack).
    bench={...}    -> manifest bench section with that content.
    write_bench_report -> also write the referenced report file.
    """
    pack = base / pack_id
    pack.mkdir(parents=True)
    frag = DEFAULT_FRAGMENT if fragment is None else fragment
    (pack / "profile.json").write_text(json.dumps(frag, indent=2) + "\n")
    manifest = {
        "id": pack_id,
        "version": "0.1.0",
        "kind": "context",
        "stack": ["python"],
        "ghostslice": ">=1.0,<2.0",
        "author": "GhostPacks tests",
        "date": "2026-10-14",
        "profile_file": "profile.json",
    }
    if bench != "unset":
        manifest["bench"] = bench
    if manifest_overrides:
        manifest.update(manifest_overrides)
    (pack / "pack.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if write_bench_report:
        report_name = "bench-report.json"
        if isinstance(manifest.get("bench"), dict):
            report_name = manifest["bench"].get("report", report_name)
        (pack / report_name).write_text(json.dumps({
            "tool": "ghostbench", "tier": "A",
            "reference_project": "fixture-project",
            "score": 42.0, "savings_percent": 42.0,
        }, indent=2) + "\n")
    for name, content in (extra_files or {}).items():
        target = pack / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return pack


@pytest.fixture()
def pack_factory(tmp_path):
    def _make(**kwargs) -> Path:
        return make_pack(tmp_path / "packs", **kwargs)
    return _make


# ---------------------------------------------------------------- project

APP_PY = '''"""Demo application module."""


def compute_total(items):
    """Sum the priced items."""
    total = 0
    for item in items:
        total += item_price(item) * item_count(item)
    return total


def item_price(item):
    """Return the price field of one item."""
    return item["price"]


def item_count(item):
    """Return the count field of one item."""
    return item.get("count", 1)


def render_total(total):
    """Format a total for display."""
    return "Total: %.2f" % total
'''

UTIL_PY = '''"""Demo utility module."""


def slugify(text):
    """Turn display text into a slug."""
    return "-".join(text.lower().split())


def clamp(value, low, high):
    """Clamp a value into a range."""
    return max(low, min(high, value))
'''

BASE_PROFILE = {"ignore": [], "modes": {}}


def make_project(base: Path, profile: dict | None = None) -> Path:
    project = base / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text(APP_PY)
    (project / "src" / "util.py").write_text(UTIL_PY)
    prof = BASE_PROFILE if profile is None else profile
    (project / ".ghostslice.json").write_text(json.dumps(prof, indent=2) + "\n")
    return project


@pytest.fixture()
def project_factory(tmp_path):
    def _make(profile: dict | None = None) -> Path:
        return make_project(tmp_path, profile=profile)
    return _make


# ---------------------------------------------------------------- ghostslice export

def ghostslice_available() -> bool:
    return (GHOSTSLICE_SRC / "ghostslice" / "__main__.py").exists()


def export_totals(project: Path, out: Path) -> dict:
    """Run a real GhostSlice export and return its manifest totals."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(GHOSTSLICE_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "ghostslice", "export", str(project),
         "-o", str(out)],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert proc.returncode == 0, (
        f"ghostslice export failed:\n{proc.stdout}\n{proc.stderr}")
    manifest = json.loads((out / "manifest.json").read_text())
    return {
        "total_original_tokens": manifest["total_original_tokens"],
        "total_sliced_tokens": manifest["total_sliced_tokens"],
        "total_saved_tokens": manifest["total_saved_tokens"],
    }
