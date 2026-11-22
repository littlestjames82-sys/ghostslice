"""Create / list / status: the happy path (integration, CLI-driven)."""
import pytest

from tests.helpers import (cleanup_worktree, cli_available, combined,
                     create_worktree, extra_worktrees, list_worktrees,
                     make_repo, status_worktree)

pytestmark = pytest.mark.skipif(
    not cli_available(),
    reason="ghostworktree core not landed yet (see REPORT_B.md)")


def test_create_makes_a_real_git_worktree(tmp_path):
    repo = make_repo(tmp_path)
    proc, wt = create_worktree(repo, "agent-a-task")
    assert proc is not None and proc.returncode == 0, combined(proc)
    assert wt is not None, (
        "create exited 0 but git reports no new worktree\n" + combined(proc))
    assert wt.exists()
    assert wt in extra_worktrees(repo)
    # A worktree, not a plain copy: .git is a file pointing at the main repo.
    assert (wt / ".git").exists()
    # The committed code is checked out there.
    assert (wt / "app.py").exists()
    cleanup_worktree(repo, "agent-a-task", wt, force=True)


def test_created_worktree_is_isolated_from_main_tree(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "isolated-task")
    assert wt is not None
    (wt / "agent-note.txt").write_text("only in the worktree\n")
    assert not (repo / "agent-note.txt").exists()
    cleanup_worktree(repo, "isolated-task", wt, force=True)


def test_list_shows_the_created_worktree(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "listed-task")
    assert wt is not None
    proc = list_worktrees(repo)
    assert proc is not None and proc.returncode == 0, combined(proc)
    out = combined(proc)
    assert "listed-task" in out or str(wt) in out, (
        "list output names neither the task nor its path:\n" + out)
    cleanup_worktree(repo, "listed-task", wt, force=True)


def test_list_on_fresh_repo_does_not_crash(tmp_path):
    repo = make_repo(tmp_path)
    proc = list_worktrees(repo)
    assert proc is not None
    assert "Traceback" not in combined(proc)


def test_status_reports_the_worktree(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "status-task")
    assert wt is not None
    proc = status_worktree(repo, "status-task")
    assert proc is not None and proc.returncode == 0, combined(proc)
    out = combined(proc)
    assert "status-task" in out or str(wt) in out
    cleanup_worktree(repo, "status-task", wt, force=True)


def test_status_for_unknown_task_is_an_error_not_a_crash(tmp_path):
    repo = make_repo(tmp_path)
    proc = status_worktree(repo, "no-such-task-xyz")
    assert proc is not None
    # Either a clean non-zero error, or a zero exit that says not found.
    text = combined(proc).lower()
    assert proc.returncode != 0 or "not found" in text or "no such" in text
    assert "Traceback" not in combined(proc)


def test_two_worktrees_coexist(tmp_path):
    repo = make_repo(tmp_path)
    _, wt1 = create_worktree(repo, "task-one")
    _, wt2 = create_worktree(repo, "task-two")
    assert wt1 is not None and wt2 is not None
    assert wt1 != wt2
    assert len(extra_worktrees(repo)) == 2
    cleanup_worktree(repo, "task-one", wt1, force=True)
    cleanup_worktree(repo, "task-two", wt2, force=True)
    assert extra_worktrees(repo) == []
