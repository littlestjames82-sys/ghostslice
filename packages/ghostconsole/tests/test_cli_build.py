"""Build/summary contract tests: missing-tool bar, read-only bar,
--root mode, text summary parity, stale window behaviour."""
from __future__ import annotations

import hashlib
import json
import os
import time

from conftest import (combined, empty_project, healthy_project, run_cli,
                      slice_history, verify_history)

TOOLS = ["slice", "verify", "bench", "scope", "ledger", "watch", "approve"]
NO_REPORT = "no report found"


def _tree_hashes(root):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


def test_bare_project_complete_board_exit_0(cli, tmp_path):
    """Missing-tool bar: no Ghost artifacts at all still renders a
    complete board with a 'no report found' row per tool, exit 0."""
    empty = empty_project(tmp_path)
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", empty, "-o", out])
    assert proc.returncode == 0, combined(proc)
    html = out.read_text(encoding="utf-8").lower()
    assert html.count(NO_REPORT) >= len(TOOLS), (
        f"expected at least {len(TOOLS)} '{NO_REPORT}' rows, "
        f"found {html.count(NO_REPORT)}")
    for tool in TOOLS:
        assert tool in html, f"no row for {tool}"


def test_build_is_read_only_for_projects(cli, tmp_path):
    """Read-only bar: building a board changes nothing in the project
    trees (the board file itself lives outside them)."""
    healthy = healthy_project(tmp_path)
    before = _tree_hashes(healthy)
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", healthy, "-o", out])
    assert proc.returncode == 0, combined(proc)
    assert _tree_hashes(healthy) == before


def test_root_mode_takes_subdirectories(cli, tmp_path):
    root = tmp_path / "ws"
    healthy_project(root, "alpha")
    empty_project(root, "beta")
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", "--root", root, "-o", out])
    assert proc.returncode == 0, combined(proc)
    html = out.read_text(encoding="utf-8").lower()
    assert "alpha" in html and "beta" in html


def test_summary_command_matches_board(cli, tmp_path):
    healthy = healthy_project(tmp_path)
    proc = run_cli(cli, ["summary", healthy])
    assert proc.returncode == 0, combined(proc)
    text = (proc.stdout or "").lower()
    assert "healthy" in text
    assert "verified" in text
    assert "no report found" not in text  # every tool present and ok


def test_summary_json_parses(cli, tmp_path):
    healthy = healthy_project(tmp_path)
    proc = run_cli(cli, ["summary", healthy, "--json"])
    assert proc.returncode == 0, combined(proc)
    model = json.loads(proc.stdout)
    assert "healthy" in json.dumps(model).lower()


def test_stale_window_moves_old_evidence_to_stale(cli, tmp_path):
    """A project whose only evidence is old is Stale under the default
    window and Verified under a wide one. Both the embedded timestamps
    and the file mtimes are set old, so either clock the adapter uses
    sees the same age."""
    p = tmp_path / "oldie"
    p.mkdir()
    old = "2026-08-01T08:00:00+00:00"
    slice_history(p, at=old)
    verify_history(p, at=old)
    old_ts = time.time() - 74 * 24 * 3600
    for f in p.rglob("*"):
        if f.is_file():
            os.utime(f, (old_ts, old_ts))
    out = tmp_path / "board.html"
    proc = run_cli(cli, ["build", p, "-o", out])
    assert proc.returncode == 0, combined(proc)
    html = out.read_text(encoding="utf-8")
    from test_columns import _column_of
    assert _column_of(html, "oldie") == "stale"
    proc = run_cli(cli, ["build", p, "-o", out, "--stale-days", "120"])
    assert proc.returncode == 0, combined(proc)
    html = out.read_text(encoding="utf-8")
    assert _column_of(html, "oldie") == "verified"


def test_default_output_name(cli, tmp_path):
    """No -o: the board lands as ghostconsole.html in the cwd."""
    healthy = healthy_project(tmp_path)
    proc = run_cli(cli, ["build", healthy], cwd=tmp_path)
    assert proc.returncode == 0, combined(proc)
    assert (tmp_path / "ghostconsole.html").is_file()
