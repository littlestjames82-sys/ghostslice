"""Cleanup: clean trees go, dirty trees are refused by default.

Adversarial core of the suite: the scope says cleanup must refuse a
dirty worktree by default. A cleanup that silently deletes uncommitted
agent work is the worst failure this tool can have.
"""
import pytest

from tests.helpers import (cleanup_worktree, cli_available, combined,
                     create_worktree, extra_worktrees, make_repo)

pytestmark = pytest.mark.skipif(
    not cli_available(),
    reason="ghostworktree core not landed yet (see REPORT_B.md)")


def test_cleanup_removes_a_clean_worktree(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "clean-task")
    assert wt is not None
    proc = cleanup_worktree(repo, "clean-task", wt)
    assert proc is not None and getattr(proc, "returncode", 1) == 0, (
        combined(proc) if proc is not None else "no cleanup form ran")
    assert wt not in extra_worktrees(repo)
    assert not wt.exists()


def test_cleanup_refuses_a_dirty_worktree_by_default(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "dirty-task")
    assert wt is not None
    # Dirty = a tracked file modified inside the worktree.
    (wt / "app.py").write_text('"""Edited, uncommitted agent work."""\n')
    proc = cleanup_worktree(repo, "dirty-task", wt)  # no --force
    # Safety invariant, checked by effect, not just exit code: the
    # worktree and the uncommitted edit must still be there.
    assert wt in extra_worktrees(repo), (
        "cleanup removed a DIRTY worktree without --force\n"
        + (combined(proc) if proc is not None else ""))
    assert wt.exists()
    assert "uncommitted" in (wt / "app.py").read_text()
    # And with the explicit override it must go.
    proc = cleanup_worktree(repo, "dirty-task", wt, force=True)
    assert proc is not None and getattr(proc, "returncode", 1) == 0
    assert wt not in extra_worktrees(repo)


def test_cleanup_refuses_untracked_files_by_default(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "untracked-task")
    assert wt is not None
    (wt / "new-output.txt").write_text("agent output, never committed\n")
    cleanup_worktree(repo, "untracked-task", wt)  # no --force
    assert wt in extra_worktrees(repo), (
        "cleanup removed a worktree holding untracked files by default")
    assert (wt / "new-output.txt").exists()
    cleanup_worktree(repo, "untracked-task", wt, force=True)
    assert wt not in extra_worktrees(repo)


def test_cleanup_unknown_task_is_an_error_not_a_crash(tmp_path):
    repo = make_repo(tmp_path)
    proc = cleanup_worktree(repo, "ghost-task-xyz", None)
    assert proc is not None
    text = combined(proc) if hasattr(proc, "stdout") else str(proc)
    assert "Traceback" not in text


def test_cleanup_does_not_touch_the_main_tree(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "side-task")
    assert wt is not None
    cleanup_worktree(repo, "side-task", wt, force=True)
    assert (repo / "app.py").exists()
    assert extra_worktrees(repo) == []
