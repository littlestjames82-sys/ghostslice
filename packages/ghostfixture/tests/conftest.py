"""Pytest fixtures for the GhostFixture suite.

Each test gets a fresh copy of a fixture project in a temp dir
plus a GhostSlice-shaped bundle built from that copy, so the
"did the tool touch the source project" checks compare real
bytes and the bundle manifest root points at the real copy.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402


@pytest.fixture()
def repro_project(tmp_path):
    dest = tmp_path / "repro_project"
    shutil.copytree(helpers.REPRO_PROJECT, dest)
    return dest


@pytest.fixture()
def repro_bundle(repro_project, tmp_path):
    return helpers.build_bundle(
        repro_project, tmp_path / "repro_bundle",
        helpers.REPRO_BUNDLE_FILES)


@pytest.fixture()
def big_project(tmp_path):
    dest = tmp_path / "big_project"
    shutil.copytree(helpers.BIG_PROJECT, dest)
    return dest


@pytest.fixture()
def big_bundle(big_project, tmp_path):
    return helpers.build_bundle(
        big_project, tmp_path / "big_bundle", helpers.BIG_BUNDLE_FILES)


@pytest.fixture()
def requires_cli():
    if not helpers.cli_available():
        pytest.skip(
            "ghostfixture CLI not discoverable "
            "(GHOSTFIXTURE_CMD, PATH, or python -m ghostfixture); "
            "see REPORT_B.md")
