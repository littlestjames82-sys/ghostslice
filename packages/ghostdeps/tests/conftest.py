"""Shared helpers for the GhostDeps black-box CLI tests.

The tests treat ghostdeps as a black box: they discover a runnable CLI
(GHOSTDEPS_CMD env override, then `ghostdeps` on PATH, then
`python -m ghostdeps` with PYTHONPATH=src) and skip cleanly when no CLI
is discoverable, so the suite is honest before the core lands and exact
once it does.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"

# ---------------------------------------------------------------------------
# CLI discovery
# ---------------------------------------------------------------------------

_DISCOVERED: list[str] | None = None
_DISCOVERY_DONE = False


def _candidate_cmds():
    env = os.environ.get("GHOSTDEPS_CMD")
    if env:
        yield env.split()
    exe = shutil.which("ghostdeps")
    if exe:
        yield [exe]
    src = REPO / "src"
    if (src / "ghostdeps").is_dir():
        yield [sys.executable, "-m", "ghostdeps"]


def _probe(cmd: list[str]) -> bool:
    try:
        proc = subprocess.run(
            cmd + ["--help"],
            capture_output=True,
            text=True,
            timeout=30,
            env=_env_for(cmd),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    blob = (proc.stdout + proc.stderr).lower()
    if "no module named" in blob or "modulenotfounderror" in blob:
        return False
    if "traceback" in blob:
        return False
    return proc.returncode in (0, 2)


def _env_for(cmd: list[str]):
    env = dict(os.environ)
    if "-m" in cmd:
        src = str(REPO / "src")
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = src + (os.pathsep + existing if existing else "")
    return env


def ghostdeps_cmd() -> list[str] | None:
    global _DISCOVERED, _DISCOVERY_DONE
    if not _DISCOVERY_DONE:
        _DISCOVERY_DONE = True
        for cand in _candidate_cmds():
            if _probe(cand):
                _DISCOVERED = cand
                break
    return _DISCOVERED


def ghostdeps_available() -> bool:
    return ghostdeps_cmd() is not None


needs_cli = pytest.mark.skipif(
    not ghostdeps_available(),
    reason="no ghostdeps CLI discoverable "
    "(set GHOSTDEPS_CMD, install the package, or provide src/ghostdeps)",
)


def run_ghostdeps(args: list[str], cwd: Path | None = None,
                  timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = ghostdeps_cmd()
    assert cmd is not None, "ghostdeps CLI not discoverable"
    return subprocess.run(
        cmd + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        env=_env_for(cmd),
    )


def combined(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


# ---------------------------------------------------------------------------
# Pack output location
# ---------------------------------------------------------------------------

def find_pack(*roots: Path) -> tuple[Path, Path] | None:
    """Return (DEPS.md, deps-manifest.json) paths searching roots in order."""
    for root in roots:
        if root is None:
            continue
        for deps_md in sorted(root.rglob("DEPS.md")):
            manifest = deps_md.parent / "deps-manifest.json"
            if manifest.is_file():
                return deps_md, manifest
        # manifest might exist under a slightly different report name set;
        # fall back to any deps-manifest.json with a sibling DEPS.md found
        for manifest in sorted(root.rglob("deps-manifest.json")):
            deps_md = manifest.parent / "DEPS.md"
            if deps_md.is_file():
                return deps_md, manifest
    return None


def run_pack(project: Path, out: Path, cwd: Path | None = None):
    """Run `ghostdeps pack <project> -o <out>` and locate the outputs."""
    proc = run_ghostdeps(["pack", str(project), "-o", str(out)], cwd=cwd)
    found = find_pack(out, project, cwd or Path.cwd())
    return proc, found


# ---------------------------------------------------------------------------
# Fixture projects (planted, hand-checkable)
# ---------------------------------------------------------------------------

def write_python_gap_project(root: Path) -> Path:
    """Python project with planted gaps.

    Declared (pyproject + requirements pins):
      requests  -> imported in app.py        (declared-and-used)
      Pillow    -> imported as PIL in app.py (declared-and-used, name map)
      colorama  -> never imported            (declared-not-imported)
    Imported but not declared:
      numpy     -> imported in app.py        (imported-not-declared)
    os is stdlib and helper is a local module: neither may be flagged.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        "[build-system]\n"
        'requires = ["setuptools"]\n'
        'build-backend = "setuptools.build_meta"\n\n'
        "[project]\n"
        'name = "fixture-python"\n'
        'version = "0.1.0"\n'
        "dependencies = [\n"
        '    "requests>=2.28",\n'
        '    "colorama==0.4.6",\n'
        '    "Pillow>=10.0",\n'
        "]\n"
    )
    (root / "requirements.txt").write_text(
        "requests==2.31.0\n"
        "colorama==0.4.6\n"
        "Pillow==10.2.0\n"
    )
    (root / "helper.py").write_text(
        "def greet(name):\n"
        "    return 'hello ' + name\n"
    )
    (root / "app.py").write_text(
        "import os\n"
        "\n"
        "import numpy\n"
        "import requests\n"
        "from PIL import Image\n"
        "\n"
        "from helper import greet\n"
        "\n"
        "\n"
        "def main():\n"
        "    print(greet(os.environ.get('USER', 'world')))\n"
        "    return requests, Image, numpy\n"
    )
    return root


def write_node_gap_project(root: Path) -> Path:
    """Node project with planted gaps.

    Declared (package.json):
      express   -> required in index.js  (declared-and-used)
      lodash    -> never imported        (declared-not-imported)
      typescript (dev) -> never imported (declared-not-imported)
    Imported but not declared:
      axios     -> required in index.js  (imported-not-declared)
    ./util is a local module: never flagged.
    package-lock.json pins express 4.18.2 and lodash 4.17.21 exactly,
    padded with transitive entries so the raw lockfile dwarfs the pack.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps({
        "name": "fixture-node",
        "version": "1.0.0",
        "private": True,
        "dependencies": {
            "express": "^4.18.2",
            "lodash": "^4.17.21",
        },
        "devDependencies": {
            "typescript": "^5.4.0",
        },
    }, indent=2) + "\n")
    packages: dict = {
        "": {
            "name": "fixture-node",
            "version": "1.0.0",
            "dependencies": {"express": "^4.18.2", "lodash": "^4.17.21"},
            "devDependencies": {"typescript": "^5.4.0"},
        },
        "node_modules/express": {
            "version": "4.18.2",
            "resolved": "https://registry.invalid/express/-/express-4.18.2.tgz",
            "integrity": "sha512-fixture",
        },
        "node_modules/lodash": {
            "version": "4.17.21",
            "resolved": "https://registry.invalid/lodash/-/lodash-4.17.21.tgz",
            "integrity": "sha512-fixture",
        },
        "node_modules/typescript": {
            "version": "5.4.5",
            "resolved": "https://registry.invalid/typescript/-/typescript-5.4.5.tgz",
            "integrity": "sha512-fixture",
        },
    }
    for i in range(80):
        packages[f"node_modules/transitive-{i:03d}"] = {
            "version": f"0.0.{i}",
            "resolved": f"https://registry.invalid/t{i}/-/t{i}-0.0.{i}.tgz",
            "integrity": "sha512-" + "x" * 88,
            "dependencies": {"nested": "^1.0.0"},
        }
    (root / "package-lock.json").write_text(json.dumps({
        "name": "fixture-node",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": packages,
    }, indent=2) + "\n")
    (root / "util.js").write_text(
        "function shout(s) { return String(s).toUpperCase(); }\n"
        "module.exports = { shout };\n"
    )
    (root / "index.js").write_text(
        "const express = require('express');\n"
        "const axios = require('axios');\n"
        "const { shout } = require('./util');\n"
        "\n"
        "const app = express();\n"
        "app.get('/', (req, res) => res.send(shout('ok')));\n"
        "module.exports = { app, axios };\n"
    )
    return root


def write_clean_python_project(root: Path) -> Path:
    """Declared set exactly matches imports: no gaps either way."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "fixture-clean"\n'
        'version = "0.1.0"\n'
        'dependencies = ["requests>=2.28"]\n'
    )
    (root / "main.py").write_text(
        "import requests\n"
        "\n"
        "\n"
        "def fetch(url):\n"
        "    return requests.get(url, timeout=5)\n"
    )
    return root


def write_no_manifest_project(root: Path) -> Path:
    """Code but no manifest or lockfile of any ecosystem."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "lonely.py").write_text(
        "import os\n"
        "\n"
        "print(os.getcwd())\n"
    )
    return root


@pytest.fixture()
def python_gap_project(tmp_path):
    return write_python_gap_project(tmp_path / "pyproj")


@pytest.fixture()
def node_gap_project(tmp_path):
    return write_node_gap_project(tmp_path / "nodeproj")


@pytest.fixture()
def clean_project(tmp_path):
    return write_clean_python_project(tmp_path / "cleanproj")


@pytest.fixture()
def no_manifest_project(tmp_path):
    return write_no_manifest_project(tmp_path / "bareproj")
