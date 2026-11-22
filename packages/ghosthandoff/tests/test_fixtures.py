"""Fixture validity: the repos the CLI tests lean on really are in
the state the PLAN verification bar describes. Ground truth here is
git itself (porcelain status, log, stash list), never the tool under
test, and these tests run whether or not the CLI exists yet.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402
from helpers import git  # noqa: E402


def test_fixture_repo_branch_and_head(fixture_repo):
    branch = git(fixture_repo, "branch", "--show-current").stdout.strip()
    assert branch == helpers.BRANCH
    subject = git(fixture_repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject == helpers.SESSION_SUBJECTS[-1]


def test_fixture_repo_commit_count_and_window_split(fixture_repo):
    subjects = git(fixture_repo, "log", "--format=%s").stdout.splitlines()
    assert len(subjects) == 3
    assert helpers.OLD_SUBJECT in subjects
    for subject in helpers.SESSION_SUBJECTS:
        assert subject in subjects
    # The old commit really is old: its commit date predates the two
    # session commits by days, so a 12h default window excludes it.
    dates = git(fixture_repo, "log", "--format=%ct").stdout.split()
    newest, _, oldest = (int(d) for d in dates)
    assert newest - oldest > 24 * 3600


def test_fixture_repo_porcelain_state(fixture_repo):
    lines = helpers.porcelain(fixture_repo).splitlines()
    codes = {}
    for line in lines:
        codes[line[3:]] = line[:2]
    assert codes.get(helpers.STAGED_FILE) == "M "
    assert codes.get(helpers.MODIFIED_FILE) == " M"
    assert codes.get(helpers.UNTRACKED_FILE) == "??"
    # The verify artifacts are untracked too; nothing else is dirty.
    assert set(codes) == {
        helpers.STAGED_FILE, helpers.MODIFIED_FILE,
        helpers.UNTRACKED_FILE, "verify-report.json", "VERIFY.md",
    }


def test_fixture_repo_has_one_stash(fixture_repo):
    stash = git(fixture_repo, "stash", "list").stdout.strip().splitlines()
    assert len(stash) == 1
    assert helpers.STASH_MESSAGE in stash[0]


def test_fixture_repo_marker_count(fixture_repo):
    found = helpers.count_markers(fixture_repo)
    assert len(found) == 3
    by_file = {rel for rel, _, _ in found}
    assert by_file == set(helpers.MARKER_FILES)
    for rel, _, line in found:
        assert helpers.MARKER_FILES[rel] in line


def test_fixture_repo_verify_report_is_failing(fixture_repo):
    report = json.loads(
        (fixture_repo / "verify-report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "failed"
    assert (fixture_repo / "VERIFY.md").exists()


def test_clean_repo_is_clean(clean_repo):
    assert helpers.porcelain(clean_repo) == ""
    assert git(clean_repo, "stash", "list").stdout.strip() == ""
    assert helpers.count_markers(clean_repo) == []
    assert not (clean_repo / "verify-report.json").exists()


def test_plain_folder_is_not_a_repo(plain_folder):
    assert not (plain_folder / ".git").exists()
    found = helpers.count_markers(plain_folder)
    assert len(found) == 1
    assert found[0][0] == "notes.txt"
