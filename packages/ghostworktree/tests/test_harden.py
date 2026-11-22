"""Harden lane regression tests (Oct 18, 2026).

Each test pins a defect demonstrated against the shipped v0.1
before the fix:

- a symlinked ``.env.example`` smuggled the real ``.env`` into the
  worktree, and seeding wrote through a broken symlink in the
  worktree to an arbitrary file outside it,
- the registry accepted JSON ``true``/``false`` and out-of-range
  values as ports, and duplicate worktree names,
- port allocation died with a bare ``TypeError`` on non-int ports,
- task names / branch names git itself forbids (``..``, trailing
  ``.``, ``.lock``, a leading ``-`` read as a git flag) passed
  validation and failed cryptically mid-create, or worse,
- ``create --path`` could plant a tree inside the main checkout or
  nested inside another registered tree,
- ``list`` died with a ``KeyError`` traceback on a registry record
  missing optional fields, and a registry root that is a plain file
  died with a ``FileExistsError`` traceback,
- safe branch deletion passed the branch name to git without a
  ``--`` separator, so a leading-dash value read as an option.
"""
import json
import sys

import pytest

sys.path.insert(0, str(__import__("tests.helpers", fromlist=["SRC"]).SRC))

from ghostworktree import core, envcopy, gitops, ports  # noqa: E402
from ghostworktree import registry as reg  # noqa: E402
from ghostworktree.errors import RegistryError, WorktreeError  # noqa: E402
from tests.helpers import (SRC, cleanup_worktree, cli_available, combined,  # noqa: E402
                           create_worktree, extra_worktrees, git_ok,
                           make_repo, registry_path, run_cli)

pytestmark = pytest.mark.skipif(
    not cli_available(),
    reason="ghostworktree core not landed yet (see REPORT_B.md)")

SECRET = "harden-planted-marker"


# ---------------------------------------------------------------- registry

def _write_registry(root, records):
    root.mkdir(parents=True, exist_ok=True)
    (root / "registry.json").write_text(
        json.dumps({"schema": 1, "worktrees": records}))


def test_registry_rejects_bool_and_out_of_range_ports(tmp_path):
    root = tmp_path / "reg"
    for bad in (True, False, 0, -1, 65536, 99999, "4100", 4100.5):
        _write_registry(root, [{"name": "x", "path": "/tmp/x",
                                "branch": "b", "port": bad}])
        with pytest.raises(RegistryError):
            reg.load(root)
    for good in (1, 4100, 65535, None):
        _write_registry(root, [{"name": "x", "path": "/tmp/x",
                                "branch": "b", "port": good}])
        assert reg.load(root)["worktrees"][0]["port"] == good


def test_registry_rejects_duplicate_names(tmp_path):
    root = tmp_path / "reg"
    rec = {"name": "dup", "path": "/tmp/x", "branch": "b", "port": 4100}
    _write_registry(root, [rec, {**rec, "path": "/tmp/y"}])
    with pytest.raises(RegistryError):
        reg.load(root)


# ---------------------------------------------------------------- ports

def test_allocate_rejects_non_int_ports_and_bad_ranges(monkeypatch):
    monkeypatch.setattr(ports, "is_bindable", lambda p: True)
    for bad in (True, False, "4100", 4100.5):
        with pytest.raises(WorktreeError):
            ports.allocate(set(), requested=bad)
    for bad_rng in (("a", "b"), (0, 10), (5000, 4100), (True, 10), None, 4100):
        with pytest.raises(WorktreeError):
            ports.allocate(set(), rng=bad_rng)
    # Valid inputs still allocate exactly as before.
    assert ports.allocate(set(), requested=4100) == 4100
    assert ports.allocate({4100}, rng=(4100, 4102)) == 4101


# ---------------------------------------------------------------- env

def test_symlinked_env_example_never_leaks_the_real_env(tmp_path):
    repo = tmp_path / "repo"
    dest = tmp_path / "dest"
    repo.mkdir()
    dest.mkdir()
    (repo / ".env").write_text(f"TOKEN={SECRET}\n")
    (repo / ".env.example").symlink_to(repo / ".env")
    # No usable example at all: nothing is seeded, nothing leaks.
    assert envcopy.seed_env(repo, dest) is None
    assert not (dest / ".env").exists()
    assert not (dest / ".env.example").exists()
    # With a regular fallback present, the fallback is used instead.
    (repo / ".env.sample").write_text("TOKEN=\n")
    dest2 = tmp_path / "dest2"
    dest2.mkdir()
    assert envcopy.seed_env(repo, dest2) == ".env.sample"
    assert SECRET not in (dest2 / ".env").read_text()


def test_seed_env_never_writes_through_a_symlink_in_the_worktree(tmp_path):
    repo = tmp_path / "repo"
    dest = tmp_path / "dest"
    repo.mkdir()
    dest.mkdir()
    (repo / ".env.example").write_text("APP_NAME=\n")
    victim = tmp_path / "victim.txt"        # target does not exist yet:
    victim2 = tmp_path / "victim2.txt"      # broken symlinks in the tree
    (dest / ".env").symlink_to(victim)
    (dest / ".env.example").symlink_to(victim2)
    envcopy.seed_env(repo, dest)
    assert not victim.exists(), "seeding wrote through the .env symlink"
    assert not victim2.exists(), "copying wrote through the example symlink"
    assert (dest / ".env").is_symlink() and (dest / ".env.example").is_symlink()


# ------------------------------------------------------- names and branches

def test_invalid_task_names_are_rejected(tmp_path):
    for bad in ("a..b", "trailing.", "task.lock", "a...b"):
        with pytest.raises(WorktreeError):
            core.validate_name(bad)
    repo = make_repo(tmp_path)
    with pytest.raises(WorktreeError):
        core.create(repo, "a..b")
    assert extra_worktrees(repo) == []


def test_invalid_branches_and_bases_are_rejected_and_create_nothing(tmp_path):
    repo = make_repo(tmp_path)
    bad_branches = ["--force", "-f", "foo..bar", "foo bar", "foo.lock",
                    "/absolute", "trailing/", "foo@{bar}", "foo/.hidden"]
    for i, bad in enumerate(bad_branches):
        with pytest.raises(WorktreeError):
            core.create(repo, f"btask{i}", branch=bad)
    for bad_base in ("--force", "", "a b"):
        with pytest.raises(WorktreeError):
            core.create(repo, "basetask", base=bad_base)
    assert extra_worktrees(repo) == []
    root = registry_path(repo).parent
    assert reg.load(root)["worktrees"] == []


# ---------------------------------------------------------------- paths

def test_create_rejects_path_inside_main_checkout_and_nested_trees(tmp_path):
    repo = make_repo(tmp_path)
    outer = core.create(repo, "outer-task")
    outer_path = outer["path"]
    with pytest.raises(WorktreeError):
        core.create(repo, "inside-task", path=repo / "inside")
    assert not (repo / "inside").exists()
    assert git_ok(repo, "status", "--porcelain") == ""
    with pytest.raises(WorktreeError):
        core.create(repo, "nested-task", path=outer_path + "/nested")
    with pytest.raises(WorktreeError):
        core.create(repo, "wrapper-task", path=outer_path.rsplit("/", 1)[0])
    assert len(extra_worktrees(repo)) == 1
    cleanup_worktree(repo, "outer-task", None, force=True)


# ------------------------------------------------------------- robustness

def test_list_tolerates_a_record_missing_optional_fields(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "sparse-task")
    assert wt is not None
    regfile = registry_path(repo)
    data = json.loads(regfile.read_text())
    del data["worktrees"][0]["created_at"]
    del data["worktrees"][0]["port"]
    regfile.write_text(json.dumps(data))
    proc = run_cli(["list", str(repo)])
    assert proc.returncode == 0, combined(proc)
    assert "Traceback" not in combined(proc)
    assert "sparse-task" in combined(proc)
    assert "unknown" in combined(proc)
    cleanup_worktree(repo, "sparse-task", wt, force=True)


def test_root_that_is_a_file_is_a_named_error_not_a_traceback(tmp_path):
    repo = make_repo(tmp_path)
    rootfile = tmp_path / "rootfile"
    rootfile.write_text("not a directory\n")
    proc = run_cli(["create", str(repo), "file-root-task",
                    "--root", str(rootfile)])
    assert proc.returncode != 0
    assert "Traceback" not in combined(proc)
    assert "registry" in combined(proc).lower()
    assert extra_worktrees(repo) == []


# ---------------------------------------------------------------- gitops

def test_branch_delete_safe_treats_a_dash_branch_as_a_name(tmp_path):
    repo = make_repo(tmp_path)
    git_ok(repo, "branch", "deletable")
    gitops.branch_delete_safe(repo, "deletable")
    assert git_ok(repo, "branch", "--list", "deletable") == ""
    # A leading-dash value (as a planted registry record could carry)
    # must be refused as a bogus name, never parsed as a git option
    # such as the force-delete implied by --force / -D.
    with pytest.raises(WorktreeError):
        gitops.branch_delete_safe(repo, "--force")
    assert git_ok(repo, "branch", "--list", "master") or \
        git_ok(repo, "branch", "--list", "main") or \
        git_ok(repo, "branch") != ""
