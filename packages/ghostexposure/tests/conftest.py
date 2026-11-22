"""Shared fixtures and CLI discovery for GhostExposure tests.

Contract source: PLAN.md (MVP v0.1).

Assumed CLI (documented in REPORT_B.md):
    ghostexposure scan   <project> --surface <pack>
    ghostexposure export <project> --surface <pack> -o <folder>
    ghostexposure verify <bundle-folder>

The CLI is discovered in this order:
  1. an installed ``ghostexposure`` executable on PATH
  2. ``python -m ghostexposure`` with ``src/`` on PYTHONPATH (repo layout,
     same as GhostSlice)

If neither is available, CLI tests skip with "core not ready" instead of
failing: Agent B (tests/docs) is built in parallel with Agent A (core).
Fixture and documentation tests do not need the core and always run.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The planted secret used by the planted-key fixture and tests. It is a
# FAKE, test-only literal in a secret shape so a secrets guard can see it.
# It is not, and has never been, a real credential.
FAKE_SECRET = "sk-test-000000000000000000000000PLANTED"


def core_available() -> bool:
    if shutil.which("ghostexposure"):
        return True
    pkg = ROOT / "src" / "ghostexposure"
    return pkg.is_dir() and ((pkg / "__main__.py").exists() or (pkg / "cli.py").exists() or (pkg / "__init__.py").exists())


def run_cli(args, cwd=None, timeout=120):
    """Run the GhostExposure CLI and return the CompletedProcess (text)."""
    env = dict(os.environ)
    cmd = None
    exe = shutil.which("ghostexposure")
    if exe:
        cmd = [exe]
    else:
        src = ROOT / "src"
        env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
        cmd = [sys.executable, "-m", "ghostexposure"]
    return subprocess.run(
        cmd + [str(a) for a in args],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture()
def cli():
    if not core_available():
        pytest.skip("core not ready: no ghostexposure executable or src/ghostexposure package yet")
    return run_cli


@pytest.fixture()
def surface_pack() -> Path:
    return FIXTURES / "surfaces" / "starter-surface.json"


def copy_fixture(name: str, dest: Path) -> Path:
    src = FIXTURES / name
    dst = dest / name
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst
