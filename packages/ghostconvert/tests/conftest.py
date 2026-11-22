"""Shared helpers for the GhostConvert black-box CLI suite.

The suite drives the real `ghostconvert` CLI as a subprocess. Discovery
order: $GHOSTCONVERT_CMD, `ghostconvert` on PATH, then
`python -m ghostconvert` with PYTHONPATH=<repo>/src. If no CLI is
discoverable the whole suite skips cleanly.

The golden bundle is built by the real GhostSlice (sibling checkout at
~/workspace/ghostslice, $GHOSTSLICE_SRC, or `ghostslice` on PATH) from
the fixture project below. Tests that need that bundle skip when
GhostSlice is not available.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- CLI ----

def _probe(cmd: list[str], env: dict) -> bool:
    try:
        proc = subprocess.run(cmd + ["targets"], capture_output=True,
                              text=True, timeout=30, env=env)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and "agents" in proc.stdout


def find_ghostconvert() -> tuple[list[str], dict] | None:
    env = dict(os.environ)
    override = os.environ.get("GHOSTCONVERT_CMD")
    if override:
        cmd = shlex.split(override)
        if _probe(cmd, env):
            return cmd, env
    on_path = shutil.which("ghostconvert")
    if on_path:
        cmd = [on_path]
        if _probe(cmd, env):
            return cmd, env
    src = REPO / "src"
    if (src / "ghostconvert" / "__main__.py").is_file():
        env2 = dict(env)
        env2["PYTHONPATH"] = str(src) + os.pathsep + env2.get("PYTHONPATH", "")
        cmd = [sys.executable, "-m", "ghostconvert"]
        if _probe(cmd, env2):
            return cmd, env2
    return None


_FOUND = find_ghostconvert()

GC_CMD, GC_ENV = _FOUND if _FOUND else ([], {})


@pytest.fixture(autouse=True)
def _require_cli():
    if _FOUND is None:
        pytest.skip("no ghostconvert CLI discoverable (set "
                    "GHOSTCONVERT_CMD, install the package, or provide "
                    "src/ghostconvert)")


def run_gc(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(GC_CMD + list(args), capture_output=True,
                          text=True, timeout=timeout, env=GC_ENV)


def combined(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout or "") + (proc.stderr or "")


# ----------------------------------------------------------- GhostSlice --

def find_ghostslice() -> tuple[list[str], dict] | None:
    env = dict(os.environ)
    src_env = os.environ.get("GHOSTSLICE_SRC")
    candidates = []
    if src_env:
        candidates.append(Path(src_env))
    candidates.append(Path.home() / "workspace" / "ghostslice" / "src")
    candidates.append(REPO.parent / "ghostslice" / "src")
    on_path = shutil.which("ghostslice")
    if on_path:
        try:
            proc = subprocess.run([on_path, "--version"], capture_output=True,
                                  text=True, timeout=30, env=env)
            if proc.returncode == 0:
                return [on_path], env
        except (OSError, subprocess.SubprocessError):
            pass
    for src in candidates:
        if (src / "ghostslice" / "__main__.py").is_file():
            env2 = dict(env)
            env2["PYTHONPATH"] = str(src) + os.pathsep + env2.get("PYTHONPATH", "")
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "ghostslice", "--version"],
                    capture_output=True, text=True, timeout=30, env=env2)
            except (OSError, subprocess.SubprocessError):
                continue
            if proc.returncode == 0:
                return [sys.executable, "-m", "ghostslice"], env2
    return None


GS = find_ghostslice()


def ghostslice_available() -> bool:
    return GS is not None


def export_bundle(project: Path, out: Path) -> subprocess.CompletedProcess:
    cmd, env = GS
    return subprocess.run(cmd + ["export", str(project), "-o", str(out)],
                          capture_output=True, text=True, timeout=120, env=env)


# ------------------------------------------------------------- fixtures --

FIXTURE_FILES = {
    "src/app.py": '''"""Demo application module."""


def greet(name, punctuation="!"):
    """Build a greeting for name."""
    message = f"Hello, {name}{punctuation}"
    return message


def add(a, b):
    return a + b


class Pair:
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def swap(self):
        return Pair(self.right, self.left)
''',
    "src/util.py": '''"""Utility helpers."""


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
''',
    "tests/test_app.py": '''from src.app import add, greet


def test_greet():
    assert greet("World") == "Hello, World!"


def test_add():
    assert add(2, 3) == 5
''',
    "docs/guide.md": """# Guide

## Install

Run the installer script.

## Usage

Call greet from the app module.
""",
    "vendor/blob.py": """# Vendored code that should be excluded.
VENDORED = True
""",
    "README.md": """# Demo Project

A tiny fixture project for conversion tests.
""",
}

FIXTURE_PROFILE = {
    "modes": {
        "src/app.py": "full",
        "src/util.py": "signatures",
        "vendor/**": "exclude",
    }
}


def write_fixture_project(root: Path) -> Path:
    for rel, text in FIXTURE_FILES.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    (root / ".ghostslice.json").write_text(
        json.dumps(FIXTURE_PROFILE, indent=2) + "\n", encoding="utf-8")
    return root


@pytest.fixture(scope="session")
def fixture_project(tmp_path_factory) -> Path:
    return write_fixture_project(tmp_path_factory.mktemp("gc-project"))


@pytest.fixture(scope="session")
def golden_bundle(fixture_project, tmp_path_factory) -> Path:
    if not ghostslice_available():
        pytest.skip("GhostSlice not available to build the golden bundle")
    out = tmp_path_factory.mktemp("gc-golden") / "bundle"
    proc = export_bundle(fixture_project, out)
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return out


@pytest.fixture()
def bundle_copy(golden_bundle, tmp_path) -> Path:
    """A private, mutable copy of the golden bundle for one test."""
    dest = tmp_path / "bundle"
    shutil.copytree(golden_bundle, dest)
    return dest


# -------------------------------------------------------------- helpers --

def read_manifest(bundle: Path) -> dict:
    return json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))


def snapshot_tree(root: Path) -> dict[str, str]:
    snap = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            snap[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return snap


def manifest_order(bundle: Path) -> list[dict]:
    return read_manifest(bundle)["files"]


def body_of(bundle: Path, rel: str) -> str | None:
    dest = bundle / "files" / rel
    if dest.is_file():
        return dest.read_text(encoding="utf-8")
    return None


def files_with_bodies(bundle: Path) -> list[dict]:
    """Manifest entries (in manifest order) that carry a body on disk."""
    return [e for e in manifest_order(bundle)
            if e.get("mode") != "exclude"
            and body_of(bundle, e["path"]) is not None]


def write_hand_bundle(root: Path, entries: list[dict],
                      bodies: dict[str, str] | None = None,
                      prompt_text: str | None = None,
                      extra_manifest: dict | None = None) -> Path:
    """Build a bundle by hand: manifest.json + optional files/ bodies
    and/or a PROMPT.md. Used for edge cases the real Slice never makes."""
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "tool": "ghostslice",
        "version": "hand-built",
        "preset": "claude-code",
        "generated_at": "2026-10-14T00:00:00+00:00",
        "root": "/hand/built/project",
        "token_method": "hand-built fixture",
        "total_original_tokens": 100,
        "total_sliced_tokens": 90,
        "total_saved_tokens": 10,
        "files": entries,
    }
    if extra_manifest:
        manifest.update(extra_manifest)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                        encoding="utf-8")
    for rel, text in (bodies or {}).items():
        dest = root / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    if prompt_text is not None:
        (root / "PROMPT.md").write_text(prompt_text, encoding="utf-8")
    return root


def entry(path: str, mode: str = "full", **kw) -> dict:
    e = {"path": path, "mode": mode, "language": kw.pop("language", "python"),
         "package": kw.pop("package", "")}
    e.update(kw)
    return e
