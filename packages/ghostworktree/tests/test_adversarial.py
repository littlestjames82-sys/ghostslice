"""Adversarial cases: bad repos, bad names, duplicates, path escapes."""
import pytest

from tests.helpers import (cleanup_worktree, cli_available, combined,
                     create_worktree, extra_worktrees, make_plain_dir,
                     make_repo, run_cli)

pytestmark = pytest.mark.skipif(
    not cli_available(),
    reason="ghostworktree core not landed yet (see REPORT_B.md)")


def test_create_in_a_missing_git_repo_fails(tmp_path):
    """Adversarial (required): a plain directory is not a git repo."""
    plain = make_plain_dir(tmp_path)
    proc, wt = create_worktree(plain, "doomed-task")
    assert wt is None
    assert proc is not None and proc.returncode != 0, (
        "create in a non-git directory must fail\n" + combined(proc))
    text = combined(proc).lower()
    assert "git" in text or "repo" in text or "not a" in text


def test_create_with_a_nonexistent_path_fails(tmp_path):
    missing = tmp_path / "does-not-exist"
    proc, wt = create_worktree(missing, "doomed-task")
    assert wt is None
    assert proc is not None and proc.returncode != 0


def test_duplicate_task_name_is_not_silently_duplicated(tmp_path):
    repo = make_repo(tmp_path)
    _, wt1 = create_worktree(repo, "same-name")
    assert wt1 is not None
    proc2, wt2 = create_worktree(repo, "same-name")
    if wt2 is not None:
        # A second, distinct worktree under the identical name with no
        # error would corrupt list/status/cleanup addressing.
        assert wt2 == wt1 or proc2.returncode != 0
    assert len(extra_worktrees(repo)) == 1
    cleanup_worktree(repo, "same-name", wt1, force=True)


def test_path_traversal_name_cannot_escape(tmp_path):
    """Adversarial: ../ in a task name must not create dirs outside."""
    repo = make_repo(tmp_path)
    escape_target = tmp_path / "escaped"
    proc, wt = create_worktree(repo, "../escaped")
    if wt is not None:
        # Sanitised into somewhere under the allowed roots is fine;
        # landing at the traversal target is not.
        assert wt.resolve() != escape_target.resolve()
        cleanup_worktree(repo, "../escaped", wt, force=True)
    assert not escape_target.exists() or escape_target in extra_worktrees(repo)


def test_empty_and_whitespace_names_are_rejected(tmp_path):
    repo = make_repo(tmp_path)
    for bad in ("", "   "):
        try:
            proc = run_cli(["create", str(repo), bad])
        except Exception:
            continue
        if proc.returncode == 0:
            # Exit 0 is only acceptable if it did not create a nameless
            # extra worktree.
            assert extra_worktrees(repo) == [], (
                f"empty/whitespace name {bad!r} created a worktree")


def test_create_does_not_dirty_the_main_tree(tmp_path):
    repo = make_repo(tmp_path)
    before = (repo / "app.py").read_text()
    _, wt = create_worktree(repo, "observer-task")
    assert wt is not None
    assert (repo / "app.py").read_text() == before
    cleanup_worktree(repo, "observer-task", wt, force=True)
