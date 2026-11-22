"""Fixture validity tests: these pass with no core present and pin the
ground truth every other test relies on."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from conftest import FIXTURES, PLANTED_SECRET

pytestmark = []  # no core needed; runs even when the CLI is absent


def _text(path):
    return Path(path).read_text()


def test_starter_fixture_shape():
    root = FIXTURES / "starter_project"
    data = tomllib.loads(_text(root / "pyproject.toml"))
    assert data["project"]["name"] == "widgetforge"
    assert data["project"]["version"] == "0.3.2"
    assert data["project"]["scripts"]["widgetforge"] == "widgetforge.main:main"
    main = _text(root / "src/widgetforge/main.py")
    assert "def main(" in main


def test_fanin_ground_truth():
    pkg = FIXTURES / "starter_project" / "src" / "widgetforge"
    importers = []
    for module in pkg.glob("*.py"):
        if module.name == "core.py":
            continue
        if re.search(r"from widgetforge\.core import|import widgetforge\.core",
                     module.read_text()):
            importers.append(module.name)
    assert len(importers) >= 3, importers  # core is the fan-in hub


def test_orphan_ground_truth():
    pkg = FIXTURES / "starter_project" / "src" / "widgetforge"
    for module in pkg.glob("*.py"):
        if module.name == "orphan.py":
            continue
        text = module.read_text()
        assert "orphan" not in text, f"{module.name} references the orphan"
    assert "ORPHAN_MARKER" in _text(pkg / "orphan.py")


def test_secret_fixture_really_plants_the_secret():
    agents = _text(FIXTURES / "secretmem_project" / "AGENTS.md")
    assert PLANTED_SECRET in agents


def test_recall_fixture_has_current_and_superseded():
    decisions = _text(FIXTURES / "recallproj" / "DECISIONS.md")
    assert "Hold all releases until the security review is complete." in decisions
    assert "Release hold lifted." in decisions
    assert "Supersedes: D-010" in decisions
