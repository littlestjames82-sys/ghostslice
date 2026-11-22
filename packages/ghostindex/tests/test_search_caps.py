"""Search caps are stated, never silent (ecosystem seam #8, fixed
Oct 14, 2026; see SEAM_FIX_REPORT.md).

Before the fix, a search whose matches exceeded the default limits
returned what looked like a complete result set: the ecosystem pass
saw exactly the capped number of hits on queries with far more true
matches, with nothing in either output mode saying so. These tests
pin the honesty contract: every search reports the exact total
number of matching files, whether any limit cut the result, and
which limit it was, in both --json and human output.
"""
from __future__ import annotations

import json

import pytest

N_FILES = 30


@pytest.fixture()
def many_db(cli, tmp_path, db):
    """One project holding N_FILES tiny files that all match one term."""
    proj = tmp_path / "manyproj"
    proj.mkdir()
    for i in range(N_FILES):
        (proj / f"mod{i:02d}.py").write_text(
            f'"""Module {i}."""\n\nCAPTERM = {i}\n\n\n'
            f"def f{i}():\n    return CAPTERM\n")
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proj, db


@pytest.fixture()
def windows_db(cli, tmp_path, db):
    """One file whose matches live in far more windows than the
    per-hit excerpt budget can hold."""
    proj = tmp_path / "winproj"
    proj.mkdir()
    lines = []
    for i in range(30):
        lines.append(f"needlepoint occurrence {i}")
        lines.extend(
            f"filler line {i} {j} with some ordinary words"
            for j in range(11))
    (proj / "many.py").write_text("\n".join(lines) + "\n")
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return db


def _raw_json(cli, db, query, extra=None):
    proc = cli.search(db, query, extra=(extra or []) + ["--json"])
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    return proc, json.loads(proc.stdout)


def test_limit_capped_search_reports_total_and_reason_json(cli, many_db):
    proj, db = many_db
    _, data = _raw_json(cli, db, "capterm")
    assert data["total_matches"] == N_FILES, (
        f"total_matches should count every matching file before "
        f"capping, got {data.get('total_matches')}")
    assert len(data["hits"]) == data["limits"]["limit"] == 10
    assert data["shown"] == 10
    assert data["capped"] is True
    assert data["capped_by"] == ["limit"], (
        f"the hit limit is the only limit that bound here, "
        f"got {data['capped_by']}")


def test_limit_capped_search_root_filter_keeps_the_total(cli, many_db):
    proj, db = many_db
    _, data = _raw_json(cli, db, "capterm",
                        extra=["--root", str(proj)])
    assert data["total_matches"] == N_FILES
    assert data["capped"] is True and data["capped_by"] == ["limit"]


def test_limit_capped_search_states_the_cap_in_human_output(cli, many_db):
    _, db = many_db
    proc = cli.search(db, "capterm")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "10 of 30 matching file(s)" in out, (
        f"human output must state shown vs total:\n{out}")
    assert "capped by hit limit (--limit 10)" in out, (
        f"human output must name the limit that bound:\n{out}")


def test_token_budget_capped_search_names_the_budget(cli, many_db):
    _, db = many_db
    _, data = _raw_json(cli, db, "capterm",
                        extra=["--limit", "50", "--max-tokens", "15"])
    assert data["total_matches"] == N_FILES
    assert 0 < data["shown"] < N_FILES
    assert data["capped"] is True
    assert data["capped_by"] == ["total_tokens"], (
        f"only the token budget bound here, got {data['capped_by']}")


def test_per_hit_capped_excerpt_is_flagged(cli, windows_db):
    db = windows_db
    _, data = _raw_json(cli, db, "needlepoint")
    assert data["total_matches"] == 1 and data["shown"] == 1
    assert data["capped"] is True
    assert data["capped_by"] == ["per_hit_tokens"], (
        f"every matching file was shown; only the per-hit cap cut "
        f"the excerpt, got {data['capped_by']}")
    assert data["hits"][0]["excerpt_truncated"] is True

    proc = cli.search(db, "needlepoint")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "per-hit token cap" in proc.stdout
    assert "excerpt shortened by the per-hit token cap" in proc.stdout


def test_uncapped_search_reports_itself_complete(cli, indexed):
    _, _, db = indexed
    _, data = _raw_json(cli, db, "quixotic")
    assert data["total_matches"] >= 2
    assert data["total_matches"] == data["shown"] == len(data["hits"])
    assert data["capped"] is False
    assert data["capped_by"] == []
    assert all(h["excerpt_truncated"] is False for h in data["hits"])


def test_stats_and_doctor_agree_with_search_limits(cli, many_db):
    _, db = many_db
    _, data = _raw_json(cli, db, "capterm")
    proc = cli.run_cli(["stats", "--json"], db=db)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    stats_defaults = json.loads(proc.stdout)["search_defaults"]
    proc = cli.run_cli(["doctor", "--json"], db=db)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    doctor_defaults = json.loads(proc.stdout)["search_defaults"]
    assert stats_defaults == doctor_defaults == data["limits"], (
        f"stats {stats_defaults}, doctor {doctor_defaults} and the "
        f"search limits echo {data['limits']} disagree")
    assert stats_defaults == {
        "limit": 10, "total_tokens": 2000, "per_hit_tokens": 200}
