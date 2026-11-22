"""Fixture-validity tests: the planted gaps really are planted.

These read the fixture projects directly (no CLI needed) so a failure
here means the fixtures drifted, not the tool.
"""
from __future__ import annotations

import json

from conftest import (write_clean_python_project, write_node_gap_project,
                      write_no_manifest_project, write_python_gap_project)


def test_python_fixture_plants_both_gaps(tmp_path):
    root = write_python_gap_project(tmp_path / "p")
    pyproject = (root / "pyproject.toml").read_text()
    app = (root / "app.py").read_text()
    for declared in ("requests", "colorama", "Pillow"):
        assert declared in pyproject
    assert "import numpy" in app          # imported, never declared
    assert "numpy" not in pyproject
    assert "colorama" not in app         # declared, never imported
    assert "from PIL import" in app      # import name differs from dist name
    pins = (root / "requirements.txt").read_text()
    assert "requests==2.31.0" in pins
    assert "Pillow==10.2.0" in pins


def test_node_fixture_plants_both_gaps(tmp_path):
    root = write_node_gap_project(tmp_path / "n")
    pkg = json.loads((root / "package.json").read_text())
    index = (root / "index.js").read_text()
    assert set(pkg["dependencies"]) == {"express", "lodash"}
    assert "require('axios')" in index    # imported, never declared
    assert "axios" not in pkg["dependencies"]
    assert "lodash" not in index          # declared, never imported
    lock = json.loads((root / "package-lock.json").read_text())
    assert lock["lockfileVersion"] == 3
    assert lock["packages"]["node_modules/express"]["version"] == "4.18.2"
    assert lock["packages"]["node_modules/lodash"]["version"] == "4.17.21"


def test_clean_fixture_has_no_gap(tmp_path):
    root = write_clean_python_project(tmp_path / "c")
    assert "requests" in (root / "pyproject.toml").read_text()
    assert "import requests" in (root / "main.py").read_text()


def test_no_manifest_fixture_has_no_manifest(tmp_path):
    root = write_no_manifest_project(tmp_path / "b")
    names = {p.name for p in root.iterdir()}
    for manifest in ("pyproject.toml", "requirements.txt", "package.json",
                     "package-lock.json", "Cargo.toml", "setup.py",
                     "setup.cfg", "Pipfile", "go.mod", "Gemfile"):
        assert manifest not in names
