"""Polish round regression tests (Oct 14, 2026).

Each test pins a defect that was demonstrated against the shipped
v0.1 before the fix (see POLISH.md):
- parallel creates racing on port allocation / registry records,
- status undercounting untracked files inside a new directory,
- cleanup --delete-branch misreporting a refused safe delete,
- malformed registry records crashing with a traceback,
- a failed registry save orphaning a created tree.
"""
import json
import sys
import threading

import pytest

from tests.helpers import (SRC, cli_available, combined, create_worktree,
                           extra_worktrees, git_ok, make_repo,
                           registry_path, run_cli)

pytestmark = pytest.mark.skipif(
    not cli_available(),
    reason="ghostworktree core not landed yet (see REPORT_B.md)")


def _parallel_create(repo, specs):
    results = {}

    def run(name, extra):
        results[name] = run_cli(["create", str(repo), name, *extra])

    threads = [threading.Thread(target=run, args=(n, e)) for n, e in specs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def _records(repo):
    data = json.loads(registry_path(repo).read_text())
    return data["worktrees"] if isinstance(data, dict) else data


def test_parallel_creates_get_distinct_ports_and_all_records_survive(tmp_path):
    repo = make_repo(tmp_path)
    names = ["par-a", "par-b", "par-c", "par-d"]
    results = _parallel_create(
        repo, [(n, ["--port-range", "18301-18304"]) for n in names])
    for n in names:
        assert results[n].returncode == 0, combined(results[n])
    records = _records(repo)
    assert sorted(r["name"] for r in records) == names
    assert sorted(r["port"] for r in records) == [18301, 18302, 18303, 18304]
    assert len(extra_worktrees(repo)) == 4


def test_parallel_creates_single_port_range_exactly_one_wins(tmp_path):
    repo = make_repo(tmp_path)
    results = _parallel_create(
        repo, [("race-a", ["--port-range", "18311-18311"]),
               ("race-b", ["--port-range", "18311-18311"])])
    codes = sorted(p.returncode for p in results.values())
    assert codes == [0, 1], {n: combined(p) for n, p in results.items()}
    assert len(_records(repo)) == 1
    assert len(extra_worktrees(repo)) == 1


def test_status_counts_every_untracked_file_in_a_new_directory(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "count-task")
    assert wt is not None
    newdir = wt / "newdir"
    newdir.mkdir()
    for fname in ("a.txt", "b.txt", "c.txt"):
        (newdir / fname).write_text("x\n")
    proc = run_cli(["status", str(repo), "count-task", "--json"])
    assert proc.returncode == 0, combined(proc)
    row = json.loads(proc.stdout)[0]
    assert row["untracked"] == 3 and row["changed"] == 3, row
    proc = run_cli(["cleanup", str(repo), "count-task"])
    assert proc.returncode == 1
    assert "3 uncommitted entries" in combined(proc)
    assert (newdir / "a.txt").exists()  # refusal left the work untouched


def test_cleanup_delete_branch_unmerged_is_a_warning_not_a_failure(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "unmerged-task")
    assert wt is not None
    git_ok(wt, "config", "user.email", "test@example.com")
    git_ok(wt, "config", "user.name", "GhostWorktree Tests")
    (wt / "new.py").write_text("x = 1\n")
    git_ok(wt, "add", "new.py")
    git_ok(wt, "commit", "-qm", "unmerged work")
    proc = run_cli(["cleanup", str(repo), "unmerged-task",
                    "--delete-branch", "--json"])
    assert proc.returncode == 0, combined(proc)
    res = json.loads(proc.stdout)
    assert res["removed_tree"] is True
    assert res["branch_deleted"] is False
    assert res["branch_delete_error"]  # the refusal is reported, not hidden
    assert "branch -D" not in combined(proc)  # the tool never suggests -D
    assert extra_worktrees(repo) == []
    assert all(r["name"] != "unmerged-task" for r in _records(repo))
    branches = git_ok(repo, "branch", "--list", "worktree/unmerged-task")
    assert "worktree/unmerged-task" in branches  # kept, the safe state


def test_malformed_registry_record_fails_named_without_traceback(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "guarded-task")
    assert wt is not None
    reg = registry_path(repo)
    data = json.loads(reg.read_text())
    records = data["worktrees"] if isinstance(data, dict) else data
    records.append({"name": "broken", "port": 18399})
    reg.write_text(json.dumps(data))
    proc = run_cli(["list", str(repo)])
    text = combined(proc)
    assert proc.returncode != 0
    assert "Traceback" not in text
    assert "registry" in text.lower() and "'path'" in text


def test_create_rolls_back_the_tree_when_registry_save_fails(tmp_path, monkeypatch):
    sys.path.insert(0, str(SRC))
    from ghostworktree import core

    repo = make_repo(tmp_path)

    def boom(root, data):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(core.reg, "save", boom)
    with pytest.raises(OSError):
        core.create(repo, "rollback-task", port=18321)
    assert extra_worktrees(repo) == [], (
        "a failed create must not orphan a tree git knows but the "
        "registry does not")
    root = registry_path(repo).parent
    assert not (root / "rollback-task").exists()
