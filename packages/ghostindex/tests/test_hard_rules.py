"""The hard rules, pinned: ignored and binary files are not indexed,
nothing outside the named roots is indexed, indexing writes nothing
into the roots, and search answers come from the index, not a live
rescan of the tree."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("term,why", [
    ("ignoredtermxyz", "file listed in the root's .gitignore"),
    ("logtermxyz", "file matched by the root's *.log .gitignore rule"),
    ("nodemoduletermxyz", "file inside node_modules, a default ignore dir"),
    ("binarytermxyz", "term planted only inside a binary (.zip) file"),
])
def test_ignored_and_binary_terms_are_never_searchable(cli, indexed, term, why):
    _, _, db = indexed
    proc = cli.search(db, term)
    assert proc.returncode == 1, (
        f"term from a {why} was searchable (rc={proc.returncode}):\n"
        + proc.stdout + proc.stderr)
    # Note: the CLI's "no matches for '<term>'" line echoes the query
    # itself; that is the query, not indexed content, so the exit code
    # is the assertion that matters here.


def test_nothing_outside_named_roots_is_indexed(cli, alpha, beta, db,
                                                tmp_path):
    outside = cli.copy_fixture("outside_project", tmp_path)
    proc = cli.index_roots(db, [alpha, beta])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = cli.search(db, "outsidetermxyz")
    assert result.returncode == 1, (
        "a project that was never named as a root is searchable:\n"
        + result.stdout + result.stderr)
    assert (outside / "outside.py").is_file()  # it exists, it is just not a root


def test_index_search_and_update_write_nothing_into_roots(cli, alpha,
                                                          beta, db):
    before_a = cli.tree_snapshot(alpha)
    before_b = cli.tree_snapshot(beta)
    proc = cli.index_roots(db, [alpha, beta])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert cli.search(db, "quixotic").returncode == 0
    upd = cli.update_roots(db, [alpha, beta])
    assert upd.returncode == 0, upd.stdout + upd.stderr
    assert cli.tree_snapshot(alpha) == before_a, "indexing changed project_alpha"
    assert cli.tree_snapshot(beta) == before_b, "indexing changed project_beta"
    # The database lives at the --db path, never inside a root.
    assert db.is_file()
    assert not str(db).startswith(str(alpha))
    assert not str(db).startswith(str(beta))


def test_search_answers_come_from_the_index_not_a_live_scan(cli, indexed):
    alpha, _, db = indexed
    # A file created after indexing, with no update run, is not in the
    # index and must not be found: search reads the index only.
    (alpha / "src" / "late.py").write_text(
        'MARKER = "livetreeterm added after indexing"\n')
    proc = cli.search(db, "livetreeterm")
    assert proc.returncode == 1, (
        "search found a file that was never indexed; it appears to "
        "rescan the live tree instead of reading the index:\n"
        + proc.stdout)
