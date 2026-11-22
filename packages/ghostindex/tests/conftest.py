"""Shared fixtures for the GhostIndex suite.

CLI tests skip cleanly while the core CLI is not discoverable yet
(Agent A's core lands in parallel); fixture and documentation tests
always run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import helpers  # noqa: E402


@pytest.fixture(scope="session")
def cli():
    if not helpers.cli_available():
        pytest.skip("ghostindex CLI not available yet "
                    "(no GHOSTINDEX_CMD, no ghostindex on PATH, "
                    "no runnable src/ghostindex package)")
    return helpers


@pytest.fixture()
def db(tmp_path) -> Path:
    return tmp_path / "state" / "index.db"


@pytest.fixture()
def alpha(tmp_path) -> Path:
    return helpers.copy_fixture("project_alpha", tmp_path)


@pytest.fixture()
def beta(tmp_path) -> Path:
    return helpers.copy_fixture("project_beta", tmp_path)


@pytest.fixture()
def indexed(cli, alpha, beta, db):
    """Both fixture projects copied to tmp and indexed. Returns
    (alpha, beta, db)."""
    proc = cli.index_roots(db, [alpha, beta])
    assert proc.returncode == 0, (
        f"index failed rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    assert db.is_file(), "index command did not create the --db database file"
    return alpha, beta, db
