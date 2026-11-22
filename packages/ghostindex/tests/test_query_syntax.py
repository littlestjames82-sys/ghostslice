"""Query syntax deepening: quoted phrases and -term exclusions.

Before this, every query word was an independent term: "sunflower
festival" as two ANDed words also matched a file that mentioned
both words pages apart, and there was no way to say "but not the
draft files" short of post-filtering agent-side. These tests pin
the richer syntax end to end through the CLI:

- "two words" matches only files where the words occur in order,
  adjacent as FTS tokens, and its excerpts mark the phrase lines.
- -term, -term* and -"two words" drop every file containing the
  excluded unit, and total_matches is the post-exclusion total.
- A query of exclusions only cannot run (exit 2, no traceback).
- Neither feature resurrects ignored or unindexed content: both
  only ever subtract from, or narrow, rows already in the index.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture()
def syntax_db(cli, tmp_path, db):
    """One project, four files that separate phrase from AND and
    give exclusions something to bite on."""
    proj = tmp_path / "syntaxproj"
    proj.mkdir()
    (proj / "adjacent.py").write_text(
        "sunflower festival parade plans\nsharedterm marker\n")
    (proj / "scattered.py").write_text(
        "sunflower is bright and the festival is much later\n"
        "sharedterm marker\n")
    (proj / "draft.py").write_text(
        "sunflower festival draftterm internal notes\n"
        "sharedterm marker\n")
    (proj / "guide.md").write_text(
        "# Guide\n\nThe sunflower festival returns each spring.\n")
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proj, db


def _paths(cli, db, query, extra=None):
    proc, hits = cli.search_json(db, query, extra=extra)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert hits is not None, "search --json did not return JSON"
    return proc, {h["path"] for h in hits}, hits


def _raw(cli, db, query):
    proc = cli.search(db, query, extra=["--json"])
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def test_and_search_matches_scattered_words_but_phrase_does_not(
        cli, syntax_db):
    _, db = syntax_db
    _, and_paths, _ = _paths(cli, db, "sunflower festival")
    assert and_paths == {"adjacent.py", "scattered.py", "draft.py",
                         "guide.md"}
    _, phrase_paths, _ = _paths(cli, db, '"sunflower festival"')
    assert phrase_paths == {"adjacent.py", "draft.py", "guide.md"}, (
        "a quoted phrase must not match a file holding both words "
        f"apart, got {phrase_paths}")


def test_phrase_search_on_the_shared_fixtures(cli, indexed):
    alpha, beta, db = indexed
    # alpha's auth.py holds the contiguous line "Quixotic login
    # handler"; beta's payments.py holds "Quixotic billing", so the
    # phrase "quixotic login" belongs to alpha alone, while the two
    # words ANDed span both projects (see test_build_search).
    _, paths, hits = _paths(cli, db, '"quixotic login"')
    assert paths == {"src/auth.py"}
    assert "quixotic login" in hits[0]["excerpt"].lower()


def test_phrase_excerpt_marks_the_phrase_line(cli, syntax_db):
    _, db = syntax_db
    _, _, hits = _paths(cli, db, '"sunflower festival"')
    guide = [h for h in hits if h["path"] == "guide.md"]
    assert guide, "phrase hit for guide.md missing"
    assert "sunflower festival" in guide[0]["excerpt"]
    assert guide[0]["raw"]["name_only"] is False, (
        "a phrase match in the body must not be reported as a "
        "name-only match with a head excerpt")


def test_excluded_term_drops_matching_files(cli, syntax_db):
    _, db = syntax_db
    _, paths, _ = _paths(cli, db, "sunflower -draftterm")
    assert paths == {"adjacent.py", "scattered.py", "guide.md"}
    data = _raw(cli, db, "sunflower -draftterm")
    assert data["total_matches"] == 3, (
        "total_matches must be the post-exclusion total, not the "
        f"4 files matching the positive term, got {data['total_matches']}")
    assert data["shown"] == 3 and data["capped"] is False


def test_excluded_prefix_drops_matching_files(cli, syntax_db):
    _, db = syntax_db
    _, paths, _ = _paths(cli, db, "sunflower -draft*")
    assert "draft.py" not in paths
    assert paths == {"adjacent.py", "scattered.py", "guide.md"}


def test_excluded_phrase_drops_only_phrase_files(cli, syntax_db):
    _, db = syntax_db
    _, paths, _ = _paths(cli, db, 'sunflower -"sunflower festival"')
    assert paths == {"scattered.py"}, (
        "excluding the phrase must keep the file that holds both "
        f"words apart, got {paths}")


def test_exclusion_applies_with_any_terms(cli, syntax_db):
    _, db = syntax_db
    _, paths, _ = _paths(cli, db, "parade draftterm -draftterm",
                         extra=["--any"])
    assert paths == {"adjacent.py"}, (
        "--any widens the positive side; the exclusion must still "
        f"drop draft.py, got {paths}")


def test_excluding_everything_is_a_clean_no_match(cli, syntax_db):
    _, db = syntax_db
    proc = cli.search(db, "sunflower -sunflower")
    assert proc.returncode == 1, (
        f"excluding every match must exit 1 (no matches), got "
        f"{proc.returncode}\n{proc.stdout}{proc.stderr}")
    assert "Traceback" not in proc.stderr


def test_exclusions_only_query_cannot_run(cli, syntax_db):
    _, db = syntax_db
    # The leading space keeps argparse from reading -draftterm as a
    # flag of its own; whitespace is insignificant to the parser, so
    # this is the same query as "-draftterm" alone.
    proc = cli.search(db, " -draftterm")
    assert proc.returncode == 2, (
        f"a query with no positive term must exit 2, got "
        f"{proc.returncode}\n{proc.stdout}{proc.stderr}")
    assert "Traceback" not in proc.stderr


def test_phrase_and_exclusion_never_resurrect_ignored_files(
        cli, indexed):
    _, _, db = indexed
    # ignoredtermxyz lives only in a .gitignore'd file of alpha.
    proc = cli.search(db, 'quixotic -"no such phrase anywhere"')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ignored_secret" not in proc.stdout
    proc = cli.search(db, '"ignoredtermxyz" -quixotic')
    assert proc.returncode == 1, (
        "a phrase search for an ignored file's term found it:\n"
        + proc.stdout + proc.stderr)
