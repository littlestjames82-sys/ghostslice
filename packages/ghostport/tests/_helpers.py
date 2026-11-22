"""Shared helpers for the GhostPort test suite (stdlib only).

Two layers of tests use this module:

* Layer 1 (fixture integrity) never imports the product. It validates that
  the fixtures under ``tests/fixtures/`` actually encode what the plan's
  verification bar requires (positive triggers present, look-alike
  negatives clean, ordering/cycle/ledger structures as documented).
* Layer 2 (core black-box) drives the GhostPort CLI exactly as PLAN.md
  specifies it: ``scan``, ``plan``, ``bundle``, ``status``. When the core
  package is not on disk yet, layer-2 tests skip with an explicit reason
  instead of failing; REPORT_B.md records that honestly.

Pack-id / output-contract assumptions are documented in REPORT_B.md.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

TESTS_DIR = pathlib.Path(__file__).resolve().parent
FIXTURES = TESTS_DIR / "fixtures"
REPO_ROOT = TESTS_DIR.parent
SRC_DIR = REPO_ROOT / "src"

#: Pack id assumed for the first pack (PLAN.md: a Python version-upgrade
#: pattern set). ``discover_pack_id`` overrides this from patterns/** when
#: Agent A's pack data is present.
FALLBACK_PACK_ID = "python-upgrade"


def core_available() -> bool:
    """True when the ghostport package can be imported from src/ or site."""
    if SRC_DIR.is_dir():
        spec = importlib.util.spec_from_file_location(
            "_gp_probe", SRC_DIR / "ghostport" / "__init__.py"
        ) if (SRC_DIR / "ghostport" / "__init__.py").is_file() else None
        if spec is not None:
            return True
    return importlib.util.find_spec("ghostport") is not None


CORE_AVAILABLE = core_available()
SKIP_CORE = "ghostport core (src/) not present yet; see REPORT_B.md assumptions"


def discover_pack_id() -> str:
    """Find the first pack's id from patterns/** if Agent A has landed it."""
    patterns_dir = REPO_ROOT / "patterns"
    if patterns_dir.is_dir():
        for candidate in sorted(patterns_dir.rglob("*")):
            if candidate.suffix in {".json", ".toml"} and candidate.is_file():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(data, dict):
                    for key in ("pack_id", "id"):
                        if isinstance(data.get(key), str) and data[key]:
                            return data[key]
                    packs = data.get("packs")
                    if isinstance(packs, list) and packs and isinstance(packs[0], dict):
                        pid = packs[0].get("pack_id") or packs[0].get("id")
                        if isinstance(pid, str) and pid:
                            return pid
    return FALLBACK_PACK_ID


PACK_ID = discover_pack_id()


def copy_fixture(name: str, dest: pathlib.Path) -> pathlib.Path:
    """Copy a fixture project into a temp dir so CLI runs never mutate fixtures."""
    src = FIXTURES / name
    target = dest / name
    shutil.copytree(src, target)
    return target


def run_cli(args: list[str], cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    """Run the GhostPort CLI as PLAN.md specifies it.

    Prefers the module entry point (``python -m ghostport``) with src/ on
    PYTHONPATH when present, and falls back to a ``ghostport`` console
    script on PATH. No network is used either way.
    """
    env = dict(os.environ)
    if SRC_DIR.is_dir():
        env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    if (SRC_DIR / "ghostport").is_dir() or importlib.util.find_spec("ghostport"):
        cmd = [sys.executable, "-m", "ghostport", *args]
    elif shutil.which("ghostport"):
        cmd = ["ghostport", *args]
    else:  # caller is expected to skip via CORE_AVAILABLE first
        raise FileNotFoundError("no ghostport entry point found")
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, env=env,
        capture_output=True, text=True, timeout=120,
    )


def parse_json_output(proc: subprocess.CompletedProcess) -> dict:
    """Best-effort JSON parse of CLI stdout (assumption: commands accept --json)."""
    text = proc.stdout.strip()
    start = text.find("{")
    if start == -1:
        raise AssertionError(f"no JSON object in CLI output:\n{proc.stdout}\n{proc.stderr}")
    return json.loads(text[start:])


def unit_file_lists(plan: dict) -> list[list[str]]:
    """Extract per-unit file lists from a port-plan.json, tolerating key names.

    Assumption (REPORT_B.md): port-plan.json has a ``units`` list in plan
    order; each unit names its files under one of files/modules/paths.
    """
    units = plan.get("units")
    assert isinstance(units, list), "port-plan.json has no 'units' list"
    out: list[list[str]] = []
    for unit in units:
        files = None
        for key in ("files", "modules", "paths", "members"):
            if isinstance(unit.get(key), list):
                files = [str(f) for f in unit[key]]
                break
        if files is None and isinstance(unit.get("file"), str):
            files = [unit["file"]]
        out.append(files or [])
    return out


def flatten(units: list[list[str]]) -> list[str]:
    return [f for unit in units for f in unit]


def load_expected(*parts: str) -> dict:
    return json.loads((FIXTURES.joinpath(*parts)).read_text(encoding="utf-8"))
