"""Incremental update (PLAN verification bar): an edited file is
re-indexed, a deleted file is dropped, an added file appears, and
update reports the exact counts."""
from __future__ import annotations


def test_update_with_no_changes_reports_zeroes(cli, indexed):
    alpha, beta, db = indexed
    proc = cli.update_roots(db, [alpha, beta])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    counts = cli.parse_update_counts(proc.stdout)
    for key in ("added", "changed", "removed"):
        assert counts[key] == 0, (
            f"no-change update reported {key}={counts[key]}; "
            f"output was:\n{proc.stdout}")
    # And the index still answers.
    assert cli.search(db, "quixotic").returncode == 0


def test_update_with_no_roots_covers_indexed_roots(cli, indexed):
    _, _, db = indexed
    proc = cli.update_roots(db, [])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    counts = cli.parse_update_counts(proc.stdout)
    assert counts["added"] in (0, None) and counts["removed"] in (0, None)


def test_incremental_edit_delete_add(cli, indexed):
    alpha, beta, db = indexed

    # Sanity: the original terms are searchable before the edit.
    assert cli.search(db, "utilstermoriginal").returncode == 0
    assert cli.search(db, "onboarding").returncode == 0

    # 1 changed: rewrite the planted term in utils.py.
    utils = alpha / "src" / "utils.py"
    utils.write_text(utils.read_text().replace(
        "utilstermoriginal", "utilstermreplaced"))
    # 1 removed: delete the beta guide.
    (beta / "docs" / "guide.md").unlink()
    # 1 added: a new file in alpha.
    (alpha / "src" / "added.py").write_text(
        '"""Added after the first index."""\nADDED = "addedtermnew"\n')

    proc = cli.update_roots(db, [alpha, beta])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    counts = cli.parse_update_counts(proc.stdout)
    assert counts["added"] == 1, f"counts: {counts}\noutput:\n{proc.stdout}"
    assert counts["changed"] == 1, f"counts: {counts}\noutput:\n{proc.stdout}"
    assert counts["removed"] == 1, f"counts: {counts}\noutput:\n{proc.stdout}"

    # The edited file's new text is searchable, its old text is gone.
    proc_new, hits = cli.search_json(db, "utilstermreplaced")
    assert proc_new.returncode == 0 and hits
    assert {h["path"] for h in hits} == {"src/utils.py"}
    assert cli.search(db, "utilstermoriginal").returncode == 1

    # The deleted file no longer answers.
    assert cli.search(db, "onboarding").returncode == 1

    # The added file answers.
    proc_add, hits_add = cli.search_json(db, "addedtermnew")
    assert proc_add.returncode == 0 and hits_add
    assert {h["path"] for h in hits_add} == {"src/added.py"}


def test_ranking_prefers_the_file_about_the_term(cli, tmp_path, db):
    """PLAN verification bar: a file whose body is about the term
    ranks above a file that mentions it once in passing."""
    root = tmp_path / "rank_project"
    (root / "src").mkdir(parents=True)
    about = "\n".join(
        ["# Harvest notes"] +
        [f"# The harvest festival planning line {i} covers harvest "
         f"food, harvest music and harvest stalls." for i in range(12)])
    (root / "src" / "about_harvest.py").write_text(about + "\n")
    passing = "\n".join(
        [f"# unrelated ledger line {i} about invoices and receipts"
         for i in range(20)] + ["# one passing mention of harvest here"])
    (root / "src" / "passing.py").write_text(passing + "\n")

    proc = cli.index_roots(db, [root])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc, hits = cli.search_json(db, "harvest")
    assert proc.returncode == 0 and hits and len(hits) >= 2
    assert hits[0]["path"].endswith("about_harvest.py"), (
        f"ranking put {hits[0]['path']} first; expected about_harvest.py. "
        f"All hits: {[h['path'] for h in hits]}")
