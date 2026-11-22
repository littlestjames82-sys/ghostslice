"""Pytest fixtures: real git repos built fresh per test."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import helpers  # noqa: E402


@pytest.fixture()
def fixture_repo(tmp_path):
    """The PLAN verification-bar repo (branch, 3 commits, staged +
    unstaged + untracked changes, a stash, 3 markers, a failing
    verify report)."""
    return helpers.make_fixture_repo(tmp_path / "fixture-project")


@pytest.fixture()
def clean_repo(tmp_path):
    """A finished repo: one commit, clean tree, nothing to hand off."""
    return helpers.make_clean_repo(tmp_path / "clean-project")


@pytest.fixture()
def plain_folder(tmp_path):
    """Not a git repo: a folder with one marker in one file."""
    return helpers.make_plain_folder(tmp_path / "plain-project")
