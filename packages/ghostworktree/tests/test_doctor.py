"""Doctor: the read-only reconciliation audit (DEEPEN lane).

Doctor reconciles the registry against git, disk, and the managed
root -- the direction list/status never look in. It must report
unregistered git worktrees, orphan directories in the root,
duplicate names/ports in a hand-edited registry, recorded branches
that drifted or vanished, and missing trees, while changing
nothing at all: no prune, no removal, no registry rewrite, and a
dirty tree is a note (work in progress), never a problem and never
discarded.
"""
import json

import pytest

from tests.helpers import (cleanup_worktree, cli_available, combined,
                           create_worktree, git_ok, make_repo,
                           registry_path, run_cli)

pytestmark = pytest.mark.skipif(
    not cli_available(),
    reason="ghostworktree core not landed yet (see REPORT_B.md)")


def _doctor(repo, *extra):
    proc = run_cli(["doctor", str(repo), *extra, "--json"])
    report = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc, report


def _kinds(report, key="problems"):
    return {p["kind"] for p in report[key]}


def test_doctor_healthy_repo_is_ok(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "healthy-task")
    assert wt is not None
    proc, report = _doctor(repo)
    assert proc.returncode == 0, combined(proc)
    assert report["ok"] is True
    assert report["problems"] == []
    assert report["summary"]["registered"] == 1
    assert report["summary"]["present"] == 1
    entry = report["worktrees"][0]
    assert entry["name"] == "healthy-task"
    assert entry["actual_branch"] == entry["branch"]
    assert entry["dirty"] is False
    cleanup_worktree(repo, "healthy-task", wt)


def test_doctor_empty_registry_is_ok(tmp_path):
    repo = make_repo(tmp_path)
    proc, report = _doctor(repo)
    assert proc.returncode == 0, combined(proc)
    assert report["ok"] is True
    assert report["summary"]["registered"] == 0


def test_doctor_reports_missing_tree_and_reads_only(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "gone-task")
    assert wt is not None
    git_ok(repo, "worktree", "remove", "--force", str(wt))
    before = registry_path(repo).read_bytes()
    proc, report = _doctor(repo)
    assert proc.returncode == 1, combined(proc)
    assert report["ok"] is False
    assert "missing" in _kinds(report)
    # Read-only: the registry is byte-identical and the record remains,
    # so cleanup can still unregister the missing tree afterwards.
    assert registry_path(repo).read_bytes() == before
    cleanup_worktree(repo, "gone-task", wt)


def test_doctor_reports_prunable_entry_without_pruning(tmp_path):
    import shutil
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "stale-task")
    assert wt is not None
    shutil.rmtree(wt)  # directory gone, git entry not yet pruned
    proc, report = _doctor(repo)
    assert proc.returncode == 1, combined(proc)
    assert {"missing", "prunable"} <= _kinds(report)
    # Still unpruned afterwards: doctor reported it, it did not act.
    proc2, report2 = _doctor(repo)
    assert "prunable" in _kinds(report2)
    cleanup_worktree(repo, "stale-task", wt)


def test_doctor_reports_unregistered_git_worktree(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "managed-task")
    assert wt is not None
    rogue = tmp_path / "rogue-tree"
    git_ok(repo, "worktree", "add", "-b", "rogue-branch", str(rogue))
    proc, report = _doctor(repo)
    assert proc.returncode == 1, combined(proc)
    assert "unregistered_worktree" in _kinds(report)
    assert [u["path"] for u in report["unregistered"]] == [str(rogue)]
    # Doctor must not adopt, remove, or unregister anything.
    assert rogue.is_dir()
    assert wt.is_dir()
    git_ok(repo, "worktree", "remove", "--force", str(rogue))
    cleanup_worktree(repo, "managed-task", wt)


def test_doctor_reports_orphan_directory_in_root(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "real-task")
    assert wt is not None
    root = registry_path(repo).parent
    orphan = root / "leftover-task"
    orphan.mkdir()
    (orphan / "stale.txt").write_text("leftover\n")
    proc, report = _doctor(repo)
    assert proc.returncode == 1, combined(proc)
    assert "orphan_directory" in _kinds(report)
    assert report["orphan_directories"] == [str(orphan)]
    # The leftover is reported, never deleted.
    assert (orphan / "stale.txt").exists()
    cleanup_worktree(repo, "real-task", wt)


def test_doctor_reports_duplicate_port_and_name(tmp_path):
    repo = make_repo(tmp_path)
    _, wt1 = create_worktree(repo, "one-task")
    _, wt2 = create_worktree(repo, "two-task")
    assert wt1 is not None and wt2 is not None
    reg = registry_path(repo)
    data = json.loads(reg.read_text())
    data["worktrees"][1]["port"] = data["worktrees"][0]["port"]
    data["worktrees"][1]["name"] = data["worktrees"][0]["name"]
    reg.write_text(json.dumps(data))
    proc, report = _doctor(repo)
    assert proc.returncode == 1, combined(proc)
    assert {"duplicate_port", "duplicate_name"} <= _kinds(report)


def test_doctor_reports_branch_drift_and_vanished_branch(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "drift-task")
    assert wt is not None
    # Drift: the tree now has another existing branch checked out.
    git_ok(wt, "checkout", "-qb", "other-branch")
    proc, report = _doctor(repo)
    assert proc.returncode == 1, combined(proc)
    assert "branch_mismatch" in _kinds(report)
    # Vanished: point the record at a branch that does not exist.
    reg = registry_path(repo)
    data = json.loads(reg.read_text())
    data["worktrees"][0]["branch"] = "no-such-branch"
    reg.write_text(json.dumps(data))
    proc, report = _doctor(repo)
    assert proc.returncode == 1, combined(proc)
    assert "branch_missing" in _kinds(report)
    cleanup_worktree(repo, "drift-task", wt, force=True)


def test_doctor_dirty_tree_is_a_note_not_a_problem(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "busy-task")
    assert wt is not None
    (wt / "app.py").write_text('"""Work in progress."""\n')
    (wt / "notes.txt").write_text("uncommitted\n")
    proc, report = _doctor(repo)
    assert proc.returncode == 0, combined(proc)
    assert report["ok"] is True
    assert "dirty" in _kinds(report, key="notes")
    entry = report["worktrees"][0]
    assert entry["dirty"] is True and entry["changed"] == 2
    # Nothing was cleaned up: the uncommitted work is intact and the
    # dirty-cleanup refusal still protects it afterwards.
    assert (wt / "notes.txt").exists()
    refused = run_cli(["cleanup", str(repo), "busy-task"])
    assert refused.returncode != 0
    assert (wt / "notes.txt").exists()
    cleanup_worktree(repo, "busy-task", wt, force=True)


def test_doctor_human_output_names_problems_and_read_only(tmp_path):
    repo = make_repo(tmp_path)
    rogue = tmp_path / "human-rogue"
    git_ok(repo, "worktree", "add", "-b", "human-rogue-branch", str(rogue))
    proc = run_cli(["doctor", str(repo)])
    text = combined(proc).lower()
    assert proc.returncode == 1
    assert "unregistered_worktree" in text
    assert "read-only" in text
    git_ok(repo, "worktree", "remove", "--force", str(rogue))


def test_doctor_corrupt_registry_still_fails_named(tmp_path):
    repo = make_repo(tmp_path)
    reg_dir = registry_path(repo).parent
    reg_dir.mkdir(parents=True, exist_ok=True)
    registry_path(repo).write_text("{ not json")
    proc = run_cli(["doctor", str(repo)])
    assert proc.returncode != 0
    assert "registr" in combined(proc).lower()
    assert "traceback" not in combined(proc).lower()
