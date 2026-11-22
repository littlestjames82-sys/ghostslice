"""Core create / list / status / cleanup logic for GhostWorktree."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from pathlib import Path
from . import envcopy, gitops, ports as portmod, registry as reg
from .errors import WorktreeError

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_BRANCH_BAD_CHARS = re.compile(r"[\s~^:?*\[\\]")

def validate_name(name: str) -> str:
    """Return ``name`` if it is a safe single path component, else raise.

    Letters, digits, ``-``, ``_`` and ``.`` only, starting with a letter
    or digit. Slashes and ``..`` are rejected so a name can never place
    a worktree outside the managed root; ``..`` anywhere, a trailing
    ``.``, and a ``.lock`` suffix are also rejected because the name
    becomes the last component of the branch ``worktree/<name>``,
    where git forbids all three.
    """
    if not name or name in (".", "..") or "/" in name or "\\" in name or not _NAME_RE.match(name):
        raise WorktreeError(
            f"invalid worktree name {name!r}: use letters, digits, '-', '_', '.' as a single path component")
    # The name becomes the last component of branch `worktree/<name>`,
    # where git forbids '..', a trailing '.', and a '.lock' suffix.
    # The character whitelist alone lets all three through, and the
    # failure then surfaces as a cryptic git error mid-create.
    if ".." in name or name.endswith(".") or name.endswith(".lock"):
        raise WorktreeError(
            f"invalid worktree name {name!r}: must not contain '..' or end with '.' or '.lock'")
    return name

def validate_branch(branch: str) -> str:
    """Reject branch names git itself would refuse, and any name that
    could be read as a git option (a leading '-') when it is passed to
    `git worktree add -b <branch>` - e.g. --branch=--force, which git
    parses as the add --force flag and then misreads HEAD as the
    branch name."""
    bad = (
        not branch
        or branch.startswith("-") or branch.startswith("/")
        or branch.endswith("/") or branch.endswith(".")
        or branch.endswith(".lock")
        or ".." in branch or "//" in branch or "@{" in branch
        or branch == "@"
        or _BRANCH_BAD_CHARS.search(branch) is not None
        or any(ord(c) < 32 or ord(c) == 127 for c in branch)
        or any(part.startswith(".") or part.endswith(".lock")
               for part in branch.split("/")))
    if bad:
        raise WorktreeError(f"invalid branch name {branch!r}")
    return branch

def validate_base(base: str) -> str:
    # A base is resolved with rev-parse before use, but a leading '-'
    # is never a ref: name it clearly instead of letting it anywhere
    # near a git command line as a possible option.
    if not base or base.startswith("-") or any(c.isspace() for c in base):
        raise WorktreeError(f"invalid base ref {base!r}")
    return base

def _resolve_repo(repo) -> Path:
    return gitops.repo_root(Path(repo))

def _root_for(repo: Path, root=None) -> Path:
    return Path(root).resolve() if root else reg.default_root(repo)

def _reconcile(repo: Path, data: dict) -> list[dict]:
    """Annotate registry records with exists/missing from git's own list."""
    known = {str(Path(w["path"]).resolve()) for w in gitops.worktree_list(repo) if w.get("path")}
    out = []
    for w in data["worktrees"]:
        rec = dict(w)
        rec["exists"] = Path(w["path"]).is_dir() and str(Path(w["path"]).resolve()) in known
        rec["state"] = "present" if rec["exists"] else "missing"
        out.append(rec)
    return out

def create(repo, name, branch=None, base="HEAD", port=None, port_range=None,
           path=None, no_env=False, root=None) -> dict:
    """Create and register one worktree; return its registry record.

    ``branch`` defaults to ``worktree/<name>`` (created from ``base``
    if new), ``port`` to the lowest free port in ``port_range``, and
    ``path`` to ``<root>/<name>``. The env is seeded from the example
    file only unless ``no_env`` is set. On any refusal nothing is
    created or registered; if registering fails after the tree was
    created on disk, the new tree is rolled back. The whole cycle
    runs under the registry lock.
    """
    validate_name(name)
    repo = _resolve_repo(repo)
    root = _root_for(repo, root)
    with reg.locked(root):
        return _create_locked(repo, name, branch=branch, base=base, port=port,
                              port_range=port_range, path=path, no_env=no_env, root=root)

def _create_locked(repo, name, branch=None, base="HEAD", port=None, port_range=None,
                   path=None, no_env=False, root=None) -> dict:
    data = reg.load(root)
    if reg.find(data, name):
        raise WorktreeError(f"worktree name {name!r} is already registered for this repo")
    branch = validate_branch(branch or f"worktree/{name}")
    validate_base(base)
    dest = Path(path).resolve() if path else (root / name)
    # Containment, checked before the exists check so the refusal names
    # the real problem. The old equality test had a dead second clause
    # and let two damaging shapes through: a tree inside the main
    # checkout (its files appear as untracked changes in the main
    # tree, so create *does* modify what the main checkout reports)
    # and a tree nested inside another registered tree (removing the
    # outer tree would swallow the inner one's uncommitted work
    # without the inner tree ever getting its own dirty check).
    if dest == repo or repo in dest.parents:
        raise WorktreeError("destination must not be the main checkout or inside it")
    if dest in repo.parents:
        raise WorktreeError("destination must not contain the main checkout")
    known = gitops.worktree_list(repo)
    others = [Path(w["path"]).resolve() for w in data["worktrees"]]
    others += [Path(w["path"]).resolve() for w in known if w.get("path")]
    for other in others:
        if other == repo:
            continue  # the main checkout is covered by the checks above
        if dest == other or other in dest.parents or dest in other.parents:
            raise WorktreeError(
                f"destination {dest} overlaps the worktree at {other}")
    if dest.exists():
        raise WorktreeError(f"destination already exists: {dest}")
    exists_branch = gitops.branch_exists(repo, branch)
    if not exists_branch and not gitops.ref_exists(repo, base):
        raise WorktreeError(f"base ref not found: {base}")
    # Check branch not already checked out elsewhere
    for w in known:
        if w.get("branch") == branch:
            raise WorktreeError(f"branch {branch!r} is already checked out at {w.get('path')}")
    rng = portmod.parse_range(port_range) if port_range else portmod.DEFAULT_RANGE
    allocated = portmod.allocate(reg.used_ports(data), requested=port, rng=rng)
    dest.parent.mkdir(parents=True, exist_ok=True)
    gitops.worktree_add(repo, dest, branch, base, create_branch=not exists_branch)
    try:
        try:
            env_source = envcopy.seed_env(repo, dest, seed_dotenv=not no_env)
        except Exception:
            env_source = None  # env seeding must not orphan a created tree silently; record null
        rec = {
            "name": name,
            "repo": str(repo),
            "path": str(dest),
            "branch": branch,
            "base": base,
            "port": allocated,
            "env_source": env_source,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        data["worktrees"].append(rec)
        reg.save(root, data)
    except Exception:
        # Roll back the just-created tree: it is brand new (only env-example
        # seeding has touched it), so a forced remove discards nothing of the
        # user's. Leaving it would orphan a tree no registry record names.
        try: gitops.worktree_remove(repo, dest, force=True)
        except Exception: pass
        raise
    return {**rec, "exists": True, "state": "present"}

def list_worktrees(repo, root=None) -> list[dict]:
    """Return registry records annotated with ``exists``/``state``.

    ``state`` is ``"present"`` when git still knows the tree and it is
    on disk, otherwise ``"missing"``; missing records are reported,
    never silently dropped.
    """
    repo = _resolve_repo(repo)
    root = _root_for(repo, root)
    return _reconcile(repo, reg.load(root))

def status_one(repo: Path, rec: dict) -> dict:
    """Build the status row for one reconciled record (see :func:`status`).

    Missing trees get ``status="missing"`` with ``None`` counts, so a
    missing tree can never be mistaken for a clean one.
    """
    out = {k: rec.get(k) for k in ("name", "path", "branch", "port", "base", "created_at", "env_source")}
    out["state"] = rec.get("state", "present")
    if not rec.get("exists", True) or not Path(rec["path"]).is_dir():
        out.update({"state": "missing", "dirty": None, "status": "missing",
                    "staged": None, "unstaged": None, "untracked": None, "changed": None})
        return out
    entries = gitops.status_porcelain(Path(rec["path"]))
    c = gitops.classify(entries)
    out.update({"dirty": c["dirty"], "status": "dirty" if c["dirty"] else "clean",
                "staged": c["staged"], "unstaged": c["unstaged"],
                "untracked": c["untracked"], "changed": c["total"],
                "current_branch": gitops.current_branch(Path(rec["path"]))})
    return out

def doctor(repo, root=None) -> dict:
    """Read-only audit reconciling registry, git, disk, and ports.

    Status/list only ever look *from* the registry outward, so several
    real inconsistencies stay invisible: a worktree git knows about
    that was never registered (or whose record was lost), a directory
    sitting in the managed root that is neither registered nor a git
    worktree, duplicate names/ports introduced by a hand-edited
    registry, a recorded branch that has drifted from (or lost) the
    branch actually checked out, and git entries git itself marks
    prunable. Doctor reports all of those and changes nothing: it
    never prunes, removes, unregisters, or rewrites the registry, and
    it never reads a real .env. A dirty tree is reported as a note,
    not a problem: uncommitted work in progress is normal, and --
    exactly as with cleanup -- it is never discarded here.
    """
    repo = _resolve_repo(repo)
    root = _root_for(repo, root)
    # Tolerant load: doctor must report duplicate names (a problem
    # it exists to surface), not die on them as other commands do.
    data = reg.load(root, allow_duplicate_names=True)
    recs = _reconcile(repo, data)
    git_entries = gitops.worktree_list(repo)
    git_by_path = {}
    for w in git_entries:
        if w.get("path"):
            git_by_path[str(Path(w["path"]).resolve())] = w
    main = str(repo.resolve())

    problems: list[dict] = []
    notes: list[dict] = []

    def problem(kind, detail, name=None, path=None):
        problems.append({"kind": kind, "name": name, "path": path, "detail": detail})

    def note(kind, detail, name=None, path=None):
        notes.append({"kind": kind, "name": name, "path": path, "detail": detail})

    # Duplicates a hand-edited (but shape-valid) registry can carry:
    # find()/cleanup address trees by name and ports must be unique,
    # so either duplicate makes the registry's promises ambiguous.
    for field, kind in (("name", "duplicate_name"), ("port", "duplicate_port")):
        seen: dict = {}
        for w in data["worktrees"]:
            value = w.get(field)
            if value is None:
                continue
            seen.setdefault(value, []).append(w.get("name"))
        for value, names in sorted(seen.items(), key=lambda kv: str(kv[0])):
            if len(names) > 1:
                problem(kind,
                        f"{field} {value!r} is recorded for {len(names)} worktrees: "
                        + ", ".join(str(n) for n in names))

    trees = []
    registered_paths = set()
    for rec in recs:
        name, path = rec.get("name"), rec.get("path")
        rpath = str(Path(path).resolve()) if path else path
        registered_paths.add(rpath)
        entry = {k: rec.get(k) for k in
                 ("name", "path", "branch", "port", "base", "created_at", "env_source")}
        entry["state"] = rec.get("state", "present")
        entry["exists"] = bool(rec.get("exists"))
        git_entry = git_by_path.get(rpath)
        entry["actual_branch"] = git_entry.get("branch") if git_entry else None
        entry["issues"] = []
        entry_problems = entry["issues"]

        def eproblem(kind, detail):
            entry_problems.append(kind)
            problem(kind, detail, name=name, path=path)

        if not entry["exists"]:
            eproblem("missing",
                     "registered worktree is missing from disk or unknown to git; "
                     "it can be unregistered with cleanup (no --force needed)")
        if rec.get("repo") and str(Path(rec["repo"]).resolve()) != main:
            eproblem("repo_mismatch",
                     f"record names repo {rec['repo']!r}, not this repo")
        branch = rec.get("branch")
        if branch and not gitops.branch_exists(repo, branch):
            eproblem("branch_missing", f"recorded branch {branch!r} no longer exists")
        elif entry["exists"] and git_entry is not None and git_entry.get("branch") != branch:
            actual = git_entry.get("branch")
            eproblem("branch_mismatch",
                     f"recorded branch is {branch!r} but the tree has "
                     + (f"{actual!r} checked out" if actual else "a detached HEAD"))
        if git_entry is not None and git_entry.get("prunable"):
            eproblem("prunable",
                     "git marks this worktree entry prunable (its directory is gone); "
                     "doctor reports it only and never prunes")
        if git_entry is not None and git_entry.get("locked"):
            note("locked", "git marks this worktree locked; cleanup by git would "
                           "refuse until it is unlocked", name=name, path=path)
        if entry["exists"]:
            try:
                counts = gitops.classify(gitops.status_porcelain(Path(path)))
            except WorktreeError as e:
                eproblem("status_unreadable", f"git status failed for this tree: {e}")
            else:
                entry.update({"dirty": counts["dirty"], "changed": counts["total"],
                              "staged": counts["staged"], "unstaged": counts["unstaged"],
                              "untracked": counts["untracked"]})
                if counts["dirty"]:
                    note("dirty",
                         f"{counts['total']} uncommitted "
                         f"entr{'y' if counts['total'] == 1 else 'ies'} in progress; "
                         "cleanup still refuses this tree without --force",
                         name=name, path=path)
        trees.append(entry)

    # Worktrees git knows about that the registry does not: invisible
    # to list/status/cleanup, and a port/branch collision risk.
    unregistered = []
    for w in git_entries:
        if not w.get("path"):
            continue
        rpath = str(Path(w["path"]).resolve())
        if rpath == main or rpath in registered_paths:
            continue
        unregistered.append({"path": w["path"], "branch": w.get("branch")})
        problem("unregistered_worktree",
                "git knows this worktree but the registry does not; GhostWorktree "
                "does not manage it and cleanup will not touch it",
                path=w["path"])

    # Directories inside the managed root that are neither registered
    # nor git worktrees: leftovers a failed or manual operation can
    # leave behind, squatting on a name create would refuse.
    orphan_dirs = []
    if root.is_dir():
        git_paths = set(git_by_path)
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            rpath = str(child.resolve())
            if rpath not in registered_paths and rpath not in git_paths:
                orphan_dirs.append(str(child))
                problem("orphan_directory",
                        "directory in the managed root is neither a registered "
                        "worktree nor a git worktree; create would refuse this name",
                        path=str(child))

    summary = {"registered": len(trees),
               "present": sum(1 for t in trees if t["exists"]),
               "missing": sum(1 for t in trees if not t["exists"]),
               "unregistered": len(unregistered),
               "orphan_directories": len(orphan_dirs),
               "problems": len(problems), "notes": len(notes)}
    return {"repo": str(repo), "root": str(root),
            "registry": str(reg.registry_path(root)),
            "ok": not problems, "summary": summary,
            "worktrees": trees, "unregistered": unregistered,
            "orphan_directories": orphan_dirs,
            "problems": problems, "notes": notes}

def status(repo, name=None, root=None) -> list[dict]:
    """Return status rows for one named tree, or all registered trees.

    Each row carries ``status`` (``clean``/``dirty``/``missing``) and,
    for present trees, staged/unstaged/untracked counts. An unknown
    ``name`` raises :class:`WorktreeError`.
    """
    repo = _resolve_repo(repo)
    root = _root_for(repo, root)
    recs = _reconcile(repo, reg.load(root))
    if name is not None:
        recs = [r for r in recs if r["name"] == name]
        if not recs:
            raise WorktreeError(f"no registered worktree named {name!r}")
    return [status_one(repo, r) for r in recs]

def cleanup(repo, name, force=False, delete_branch=False, root=None) -> dict:
    """Remove one registered worktree, unregister it, and free its port.

    HARD RULE: a dirty tree is refused unless ``force`` is true, and
    the refusal names how many entries would be lost; the tree is
    left untouched. A missing tree is unregistered without ``force``.
    The branch is kept unless ``delete_branch`` is true, and then
    only via a safe ``git branch -d``; a refused safe delete is
    reported in ``branch_delete_error`` and does not fail the cleanup.
    """
    validate_name(name)
    repo = _resolve_repo(repo)
    root = _root_for(repo, root)
    with reg.locked(root):
        return _cleanup_locked(repo, name, force=force, delete_branch=delete_branch, root=root)

def _cleanup_locked(repo, name, force=False, delete_branch=False, root=None) -> dict:
    data = reg.load(root)
    rec = reg.find(data, name)
    if rec is None:
        raise WorktreeError(f"no registered worktree named {name!r}")
    dest = Path(rec["path"])
    present = dest.is_dir() and any(
        str(Path(w["path"]).resolve()) == str(dest.resolve())
        for w in gitops.worktree_list(repo) if w.get("path"))
    removed_tree, branch_deleted = False, False
    if present:
        entries = gitops.status_porcelain(dest)
        c = gitops.classify(entries)
        if c["dirty"] and not force:
            raise WorktreeError(
                f"refusing to clean up dirty worktree {name!r}: {c['total']} uncommitted "
                f"entr{'y' if c['total']==1 else 'ies'} ({c['staged']} staged, {c['unstaged']} unstaged, "
                f"{c['untracked']} untracked). Re-run with --force to discard uncommitted work.")
        gitops.worktree_remove(repo, dest, force=force)
        removed_tree = True
    else:
        gitops.worktree_prune(repo)
    data["worktrees"] = [w for w in data["worktrees"] if w["name"] != name]
    reg.save(root, data)
    branch_delete_error = None
    if delete_branch and rec.get("branch"):
        try:
            gitops.branch_delete_safe(repo, rec["branch"])
            branch_deleted = True
        except WorktreeError as e:
            # The tree cleanup itself succeeded; only the optional branch
            # deletion was refused (safe -d). That is a warning, not a
            # failed cleanup: the branch is kept, which is the safe state.
            branch_delete_error = str(e)
    return {"name": name, "path": rec["path"], "branch": rec.get("branch"),
            "port": rec.get("port"), "removed_tree": removed_tree,
            "was_missing": not present, "branch_deleted": branch_deleted,
            "branch_delete_error": branch_delete_error,
            "freed_port": rec.get("port")}
