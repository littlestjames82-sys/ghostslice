"""Build and search behaviour against the real CLI (PLAN contract)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def test_index_creates_sqlite_fts5_database(indexed, db):
    alpha, beta, _ = indexed
    assert db.is_file()
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    schema = " ".join((sql or "").lower() for _, sql in rows)
    assert "fts5" in schema, f"no FTS5 virtual table in index schema: {rows}"


def test_search_unique_term_returns_only_owning_project(cli, indexed):
    alpha, beta, db = indexed
    proc, hits = cli.search_json(db, "betaonlyterm")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert hits is not None, (
        "search --json did not return JSON; PLAN promises --json output.\n"
        + proc.stdout + proc.stderr)
    assert hits, "no hits for a term planted in project_beta"
    paths = {h["path"] for h in hits}
    assert paths == {"src/payments.py"}, f"unexpected hit paths: {paths}"
    for h in hits:
        assert "project_beta" in h["root"] or not h["root"], (
            f"hit root does not name project_beta: {h['root']!r}")


def test_search_shared_term_spans_both_projects(cli, indexed):
    alpha, beta, db = indexed
    proc, hits = cli.search_json(db, "quixotic")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert hits is not None and hits, "shared term produced no hits"
    roots = " ".join(h["root"] for h in hits)
    paths = {h["path"] for h in hits}
    assert "src/auth.py" in paths and "src/payments.py" in paths, (
        f"shared term should hit both projects, got paths {paths} roots {roots}")


def test_search_no_match_exit_code_is_1(cli, indexed):
    _, _, db = indexed
    proc = cli.search(db, "termthatdoesnotexistanywhere")
    assert proc.returncode == 1, (
        f"PLAN: no matches must exit 1, got {proc.returncode}\n"
        + proc.stdout + proc.stderr)


def test_search_without_index_exit_code_is_2(cli, tmp_path):
    missing = tmp_path / "never-built.db"
    proc = cli.search(missing, "quixotic")
    assert proc.returncode == 2, (
        f"PLAN: searching with no index must exit 2, got {proc.returncode}\n"
        + proc.stdout + proc.stderr)
    assert "Traceback" not in proc.stderr


def test_search_root_filter_limits_results(cli, indexed):
    alpha, beta, db = indexed
    proc, hits = cli.search_json(db, "quixotic",
                                 extra=["--root", str(beta)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert hits, "root-filtered search found nothing in beta"
    for h in hits:
        if h["root"]:
            assert "project_beta" in h["root"], (
                f"--root beta returned a hit from {h['root']!r}")
    assert {h["path"] for h in hits} == {"src/payments.py"}


def test_search_limit_caps_hits(cli, indexed):
    _, _, db = indexed
    proc, hits = cli.search_json(db, "quixotic", extra=["--limit", "1"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert hits is not None and len(hits) == 1, (
        f"--limit 1 should return exactly one hit, got {hits}")


def test_search_any_flag_widens_match(cli, indexed):
    _, _, db = indexed
    # No single file holds both terms, so the default AND search misses.
    proc_and = cli.search(db, "betaonlyterm checklist")
    assert proc_and.returncode == 1, (
        "default AND search should miss when no file holds both terms: "
        + proc_and.stdout)
    proc, hits = cli.search_json(db, "betaonlyterm checklist",
                                 extra=["--any"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert hits, "--any search returned no hits"


def test_list_and_stats_report_the_index(cli, indexed):
    alpha, beta, db = indexed
    proc = cli.run_cli(["list"], db=db)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert str(alpha) in out or "project_alpha" in out
    assert str(beta) in out or "project_beta" in out

    proc = cli.run_cli(["stats"], db=db)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert str(db) in proc.stdout or "index.db" in proc.stdout


def test_doctor_reports_fts5(cli, indexed):
    _, _, db = indexed
    proc = cli.run_cli(["doctor"], db=db)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    low = (proc.stdout + proc.stderr).lower()
    assert "fts5" in low and "sqlite" in low


def test_remove_root_drops_only_that_root(cli, indexed):
    alpha, beta, db = indexed
    proc = cli.run_cli(["remove", str(beta)], db=db)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert cli.search(db, "betaonlyterm").returncode == 1
    proc2, hits = cli.search_json(db, "quixotic")
    assert proc2.returncode == 0 and hits
    assert {h["path"] for h in hits} != {"src/payments.py"}
    # remove never deletes project files
    assert (beta / "src" / "payments.py").is_file()
