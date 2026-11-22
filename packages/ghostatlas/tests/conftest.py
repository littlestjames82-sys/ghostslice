"""Shared helpers for the GhostAtlas test suite.

Core contract assumed here (from PLAN.md, v0.1 MVP items 1-3):

* The tool is importable / runnable the GhostSlice way:
  ``PYTHONPATH=src python3 -m ghostatlas ...`` from this repo, or a
  ``ghostatlas`` console script on PATH once installed.
* ``ghostatlas build <project> -o <atlas.html>`` builds the map and,
  in the same run, an ``ATLAS.md`` architecture brief. ATLAS.md is
  looked for next to the HTML output first, then in the current
  working directory, then in the project root.
* If the run also emits ``atlas.json`` (structured data next to the
  HTML), the tests prefer it for graph / reading-order assertions;
  otherwise they parse the HTML and ATLAS.md text.

If Agent A's core makes different choices, these helpers are the
single place to adjust, and REPORT_B.md records the assumption.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
GHOSTSLICE_SRC = Path.home() / "workspace" / "ghostslice" / "src"

PLANTED_SECRET = "ATLASPLANTEDSECRET9f3c7d2e51aa"


def ghostslice_available() -> bool:
    return (GHOSTSLICE_SRC / "ghostslice").is_dir()


def core_available() -> bool:
    if (REPO_ROOT / "src" / "ghostatlas").is_dir():
        return True
    if shutil.which("ghostatlas"):
        return True
    return False


def atlas_command() -> list[str] | None:
    """Return the base command used to invoke the GhostAtlas CLI."""
    env_cmd = os.environ.get("GHOSTATLAS_CMD")
    if env_cmd:
        return env_cmd.split()
    if (REPO_ROOT / "src" / "ghostatlas").is_dir():
        return [sys.executable, "-m", "ghostatlas"]
    script = shutil.which("ghostatlas")
    if script:
        return [script]
    return None


def run_atlas(args: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    cmd = atlas_command()
    assert cmd is not None, "GhostAtlas core not found (see REPORT_B.md assumptions)"
    env = dict(os.environ)
    src = REPO_ROOT / "src"
    if src.is_dir():
        env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        cmd + args,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class AtlasBuild:
    def __init__(self, result, workdir: Path, html_path: Path):
        self.result = result
        self.workdir = workdir
        self.html_path = html_path

    @property
    def ok(self) -> bool:
        return self.result.returncode == 0 and self.html_path.is_file()

    @property
    def html(self) -> str:
        return self.html_path.read_text(encoding="utf-8", errors="replace") if self.html_path.is_file() else ""

    @property
    def atlas_md_path(self) -> Path | None:
        candidates = [
            self.html_path.parent / "ATLAS.md",
            self.workdir / "ATLAS.md",
        ]
        for cand in candidates:
            if cand.is_file():
                return cand
        hits = sorted(self.workdir.rglob("ATLAS.md"))
        return hits[0] if hits else None

    @property
    def atlas_md(self) -> str:
        path = self.atlas_md_path
        return path.read_text(encoding="utf-8", errors="replace") if path else ""

    @property
    def data(self) -> dict | None:
        """Structured data: atlas.json if emitted, else the JSON the
        core embeds in the HTML (the landed core embeds its full run
        data in a script block; that is a readable, stable surface)."""
        candidates = [self.html_path.parent / "atlas.json"]
        candidates += sorted(self.workdir.rglob("atlas.json"))
        for cand in candidates:
            if cand.is_file():
                try:
                    return json.loads(cand.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return None
        html = self.html
        for blob in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S):
            blob = blob.strip()
            if blob.startswith("{"):
                try:
                    parsed = json.loads(blob)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return None


@pytest.fixture()
def ground_truth(tmp_path: Path) -> Path:
    """A writable copy of the ground-truth fixture project."""
    dst = tmp_path / "gt_project"
    shutil.copytree(FIXTURES / "ground_truth" / "project", dst)
    return dst


@pytest.fixture()
def secret_project(tmp_path: Path) -> Path:
    dst = tmp_path / "secret_project"
    shutil.copytree(FIXTURES / "secret_project" / "project", dst)
    return dst


@pytest.fixture()
def truth() -> dict:
    return json.loads((FIXTURES / "ground_truth" / "TRUTH.json").read_text(encoding="utf-8"))


@pytest.fixture()
def build(tmp_path: Path):
    """Factory: build an Atlas for a project dir, return AtlasBuild."""

    def _build(project: Path, extra_args: list[str] | None = None) -> AtlasBuild:
        out_dir = tmp_path / "atlas_out"
        out_dir.mkdir(exist_ok=True)
        html_path = out_dir / "atlas.html"
        args = ["build", str(project), "-o", str(html_path)]
        if extra_args:
            args += extra_args
        result = run_atlas(args, cwd=tmp_path)
        return AtlasBuild(result, tmp_path, html_path)

    return _build


requires_core = pytest.mark.skipif(
    not core_available(),
    reason="GhostAtlas core (src/ghostatlas or ghostatlas script) not present yet",
)


def section_after(text: str, *needles: str, span: int = 4000) -> str:
    """Return the section following the first heading-ish needle
    match, stopping at the next heading so sections do not bleed
    into each other."""
    low = text.lower()
    for needle in needles:
        idx = low.find(needle.lower())
        if idx >= 0:
            chunk = text[idx : idx + span]
            stops = [
                pos
                for marker in ("\n## ", "\n# ", "<h2", "<h3")
                for pos in [chunk.find(marker, len(needle) + 1)]
                if pos > 0
            ]
            if stops:
                chunk = chunk[: min(stops)]
            return chunk
    return ""


def numbers_on_lines_with(text: str, needle: str) -> list[int]:
    out: list[int] = []
    for line in text.splitlines():
        if needle.lower() in line.lower():
            for raw in re.findall(r"\d[\d,]*", line):
                out.append(int(raw.replace(",", "")))
    return out
