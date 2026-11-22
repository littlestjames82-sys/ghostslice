"""Registry behaviour and JSON status: missing trees, corruption,
port reuse, and the branch-kept-by-default rule (PLAN.md)."""
import json
import shutil

import pytest

from tests.helpers import (cleanup_worktree, cli_available, combined,
                           create_worktree, extra_worktrees, git_ok,
                           make_repo, registry_path, run_cli)

pytestmark = pytest.mark.skipif(
    not cli_available(),
    reason="ghostworktree core not landed yet (see REPORT_B.md)")


def _json_cli(*args):
    proc = run_cli([*args, "--json"])
    return proc, (json.loads(proc.stdout) if proc.returncode == 0
                  and proc.stdout.strip() else None)


def test_registry_records_the_worktree(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "recorded-task")
    assert wt is not None
    reg = registry_path(repo)
    assert reg.exists(), f"no registry at the PLAN location {reg}"
    data = json.loads(reg.read_text())
    records = data["worktrees"] if isinstance(data, dict) else data
    match = [r for r in records if r.get("name") == "recorded-task"]
    assert match, f"task not in registry: {data}"
    rec = match[0]
    assert str(wt) == rec["path"]
    assert isinstance(rec["port"], int) and 0 < rec["port"] < 65536
    assert rec["branch"]  # a branch name is recorded
    cleanup_worktree(repo, "recorded-task", wt, force=True)


def test_status_json_reports_clean_then_dirty(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "json-task")
    assert wt is not None
    proc, rows = _json_cli("status", str(repo), "json-task")
    assert proc.returncode == 0, combined(proc)
    assert rows, "status --json returned no rows"
    row = rows[0] if isinstance(rows, list) else rows
    assert row.get("status") == "clean" or row.get("dirty") is False
    (wt / "app.py").write_text('"""Changed."""\n')
    proc, rows = _json_cli("status", str(repo), "json-task")
    assert proc.returncode == 0, combined(proc)
    row = rows[0] if isinstance(rows, list) else rows
    assert row.get("status") == "dirty" or row.get("dirty") is True
    cleanup_worktree(repo, "json-task", wt, force=True)


def test_missing_tree_is_reported_missing_not_clean(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "vanishing-task")
    assert wt is not None
    shutil.rmtree(wt)
    git_ok(repo, "worktree", "prune")
    proc = run_cli(["status", str(repo), "vanishing-task"])
    text = combined(proc).lower()
    assert proc.returncode == 0 or "missing" in text
    assert "missing" in text, (
        "a deleted tree must be reported missing, not clean:\n" + text)
    # A missing tree may be unregistered without --force.
    cleanup_worktree(repo, "vanishing-task", wt)
    assert registry_path(repo).exists()
    data = json.loads(registry_path(repo).read_text())
    records = data["worktrees"] if isinstance(data, dict) else data
    assert all(r.get("name") != "vanishing-task" for r in records)


def test_corrupt_registry_fails_named_never_silently_empty(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "guarded-task")
    assert wt is not None
    reg = registry_path(repo)
    reg.write_text("{ this is not json")
    proc = run_cli(["list", str(repo)])
    assert proc.returncode != 0, (
        "corrupt registry must fail, not return a silent empty list")
    assert "registr" in combined(proc).lower()
    # Restore a valid empty-ish state is not possible (the record is
    # intentionally unreadable); remove the tree with git directly.
    git_ok(repo, "worktree", "remove", "--force", str(wt))


def test_cleanup_keeps_the_branch_by_default(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "branch-task")
    assert wt is not None
    cleanup_worktree(repo, "branch-task", wt)  # clean tree, no flags
    assert extra_worktrees(repo) == []
    branches = git_ok(repo, "branch", "--list", "worktree/branch-task")
    assert "worktree/branch-task" in branches, (
        "cleanup deleted the branch without --delete-branch")


def test_freed_port_can_be_reused(tmp_path):
    repo = make_repo(tmp_path)
    proc1, wt1 = create_worktree(repo, "first-user")
    assert wt1 is not None
    from tests.helpers import worktree_port
    port = worktree_port(repo, wt1, proc1)
    if port is None:
        pytest.skip("core does not surface ports; see REPORT_B.md")
    cleanup_worktree(repo, "first-user", wt1)  # clean: frees the port
    proc2, wt2 = create_worktree(repo, "second-user", port=port)
    assert wt2 is not None, (
        f"port {port} was not reusable after cleanup:\n" + combined(proc2))
    cleanup_worktree(repo, "second-user", wt2, force=True)
