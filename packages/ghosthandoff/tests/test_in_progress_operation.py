"""In-progress git operation detection (deepen pass).

A repo left mid-merge or mid-rebase is the highest-stakes handoff
state: the next session must know the tree is in a mid-operation
state before it trusts any other fact in the pack. Detection is from
repo facts only: git-dir marker files (MERGE_HEAD, rebase-merge)
named as the source of each operation fact, and unmerged paths from
git status. A clean repo must report no operation and gain no loop.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

import helpers  # noqa: E402
from helpers import git  # noqa: E402

pytestmark = pytest.mark.skipif(
    not helpers.cli_available(),
    reason="ghosthandoff CLI not discoverable (see REPORT_B.md)")

CONFLICTED_FILE = "shared.txt"


def _write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).write_text(text, encoding="utf-8")


def _diverged_repo(dest: Path) -> Path:
    """Two branches that both rewrote the same line of shared.txt."""
    dest.mkdir(parents=True, exist_ok=True)
    git(dest, "init", "-q", "-b", "main")
    git(dest, "config", "commit.gpgsign", "false")
    _write(dest, CONFLICTED_FILE, "base version\n")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "Base")
    git(dest, "branch", "feature")
    _write(dest, CONFLICTED_FILE, "main version\n")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "Main change")
    git(dest, "checkout", "-q", "feature")
    _write(dest, CONFLICTED_FILE, "feature version\n")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "Feature change")
    git(dest, "checkout", "-q", "main")
    return dest


def make_merge_conflict_repo(dest: Path) -> Path:
    dest = _diverged_repo(dest)
    proc = git(dest, "merge", "feature", check=False)
    assert proc.returncode != 0, "merge of diverged branches should conflict"
    assert (dest / ".git" / "MERGE_HEAD").is_file()
    git(dest, "status", "--porcelain")  # settle the index
    return dest


def make_rebase_conflict_repo(dest: Path) -> Path:
    dest = _diverged_repo(dest)
    git(dest, "checkout", "-q", "feature")
    proc = git(dest, "rebase", "main", check=False)
    assert proc.returncode != 0, "rebase of diverged branches should conflict"
    assert (dest / ".git" / "rebase-merge").is_dir()
    git(dest, "status", "--porcelain")  # settle the index
    return dest


def build_pack(project: Path, tmp_path: Path, name: str = "pack-out"):
    outdir = tmp_path / name
    proc = helpers.run_cli(
        ["pack", str(project), "-o", str(outdir)], cwd=tmp_path)
    assert proc.returncode == 0, (
        f"pack exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return outdir


def operations_in(data) -> list[dict]:
    ops = []
    for value in helpers.values_for_key(data, "operation"):
        if isinstance(value, list):
            ops.extend(e for e in value if isinstance(e, dict))
    return ops


def loops_in(data) -> list[dict]:
    out = []
    for value in helpers.values_for_key(data, "open_loop"):
        if isinstance(value, list):
            out.extend(e for e in value if isinstance(e, dict))
    return out


def test_merge_in_progress_is_a_sourced_fact(tmp_path):
    repo = make_merge_conflict_repo(tmp_path / "merge-project")
    outdir = build_pack(repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    ops = operations_in(data)
    assert len(ops) == 1, f"expected exactly the merge operation, got {ops}"
    assert ops[0]["operation"] == "merge"
    assert "MERGE_HEAD" in ops[0]["source"]
    # The operation's head names the commit being merged in.
    head = git(repo, "rev-parse", "MERGE_HEAD").stdout.strip()
    assert ops[0].get("head") == head
    text = helpers.pack_text(outdir)
    assert "In-progress git operation: merge" in text
    assert "MERGE_HEAD" in text


def test_merge_conflict_paths_are_unmerged_not_double_counted(tmp_path):
    repo = make_merge_conflict_repo(tmp_path / "merge-project")
    outdir = build_pack(repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    status_lists = {}
    for value in helpers.values_for_key(data, "status"):
        if isinstance(value, dict):
            status_lists = value
    assert helpers.names_in([status_lists.get("unmerged", [])]) == {CONFLICTED_FILE}
    assert CONFLICTED_FILE not in helpers.names_in(
        [status_lists.get("staged", []), status_lists.get("unstaged", [])])
    assert "Unmerged (conflicted) files: shared.txt" in helpers.pack_text(outdir)


def test_merge_in_progress_drives_first_loop_and_first_step(tmp_path):
    repo = make_merge_conflict_repo(tmp_path / "merge-project")
    outdir = build_pack(repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    loops = loops_in(data)
    kinds = [lp["kind"] for lp in loops]
    assert "in-progress-operation" in kinds
    assert "unmerged-files" in kinds
    for lp in loops:
        if lp["kind"] in ("in-progress-operation", "unmerged-files"):
            assert lp.get("source"), f"loop names no source: {lp!r}"
    op_loop = next(lp for lp in loops if lp["kind"] == "in-progress-operation")
    assert "MERGE_HEAD" in op_loop["source"]
    steps = []
    for value in helpers.values_for_key(data, "next_step"):
        if isinstance(value, list):
            steps.extend(e for e in value if isinstance(e, dict))
    assert steps, "a mid-merge repo must produce next steps"
    assert "in-progress git operation" in steps[0]["text"]
    assert "merge" in steps[0]["text"]


def test_rebase_in_progress_is_detected(tmp_path):
    repo = make_rebase_conflict_repo(tmp_path / "rebase-project")
    outdir = build_pack(repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    ops = operations_in(data)
    assert [op["operation"] for op in ops] == ["rebase"]
    assert "rebase-merge" in ops[0]["source"]
    assert ops[0].get("branch") == "feature"
    assert "In-progress git operation: rebase" in helpers.pack_text(outdir)
    assert "in-progress-operation" in [lp["kind"] for lp in loops_in(data)]


def test_pack_on_mid_merge_repo_leaves_project_byte_identical(tmp_path):
    repo = make_merge_conflict_repo(tmp_path / "merge-project")
    before_status = helpers.porcelain(repo)
    before = helpers.tree_hashes(repo)
    build_pack(repo, tmp_path)
    assert helpers.tree_hashes(repo) == before
    assert helpers.porcelain(repo) == before_status


def test_clean_repo_reports_no_operation_and_no_new_loop(clean_repo, tmp_path):
    outdir = build_pack(clean_repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    assert operations_in(data) == []
    assert loops_in(data) == []
    assert "In-progress git operation: " not in helpers.pack_text(outdir)
