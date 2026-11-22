"""Git facts for the handoff pack.

Read-only by construction: the only subcommands used are rev-parse,
status, log, diff (stat/name-only), ls-files, and stash list, and every
invocation passes ``--no-optional-locks`` (plus GIT_OPTIONAL_LOCKS=0)
so git itself does not write back to the index while reporting.

Main entry points:

- :func:`resolve_window` turns a ``--since`` value into a session
  window (default: last 12 hours).
- :func:`collect_git` gathers branch, status, window commits, diff
  stats, ahead/behind, and stash facts into one dict.
- :func:`list_project_files` defines the file universe the marker
  scan runs over.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta

GIT_TIMEOUT = 30

_READ_ONLY = ("rev-parse", "status", "log", "diff", "ls-files", "stash")


def run_git(project: str, args: list[str]) -> tuple[int, str]:
    """Run one read-only git command in ``project``. Returns (rc, stdout)."""
    if not args or args[0] not in _READ_ONLY:
        raise ValueError(f"git subcommand not on the read-only list: {args[:1]}")
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        proc = subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, NotADirectoryError):
        return 127, ""
    return proc.returncode, proc.stdout or ""


_DURATION_RE = re.compile(r"^(\d+)\s*([mhd])$")


def resolve_window(project: str, since: str | None, now: datetime) -> dict:
    """Resolve the session window.

    Returns a dict with ``kind`` ("since" or "ref"), ``description`` and
    either ``git_since`` (a git --since argument) or ``ref``.
    The default is the last 12 hours; uncommitted changes are always in
    the session regardless of the window.
    """
    if since is None:
        start = now - timedelta(hours=12)
        return {
            "kind": "since",
            "description": "last 12 hours (default) plus all uncommitted changes",
            "git_since": start.strftime("%Y-%m-%d %H:%M:%S"),
            "ref": None,
        }
    m = _DURATION_RE.match(since.strip())
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
        start = now - delta
        return {
            "kind": "since",
            "description": f"last {n}{unit} (from --since {since}) plus all uncommitted changes",
            "git_since": start.strftime("%Y-%m-%d %H:%M:%S"),
            "ref": None,
        }
    parsed = None
    try:
        parsed = datetime.fromisoformat(since.strip())
    except ValueError:
        parsed = None
    if parsed is not None:
        return {
            "kind": "since",
            "description": f"since {since} (from --since) plus all uncommitted changes",
            "git_since": since.strip(),
            "ref": None,
        }
    # A value starting with "-" is never probed as a ref: handed to git
    # it would be parsed as an option, not a revision.
    if not since.strip().startswith("-"):
        rc, _ = run_git(project, ["rev-parse", "--verify", "--quiet", f"{since}^{{commit}}"])
        if rc == 0:
            return {
                "kind": "ref",
                "description": f"commits in {since}..HEAD (from --since) plus all uncommitted changes",
                "git_since": None,
                "ref": since,
            }
    # Unrecognised value: hand it to git as a --since argument and let the
    # log call report emptiness; description stays honest about the source.
    return {
        "kind": "since",
        "description": f"since {since} (from --since, unparsed) plus all uncommitted changes",
        "git_since": since,
        "ref": None,
    }


_HEX_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _read_marker_file(path: str) -> str:
    """First line of a git-dir marker file, or "" when unreadable."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.readline().strip()
    except OSError:
        return ""


def _git_dir(project: str) -> str:
    """Absolute path of the repo's git dir (per-worktree dir included).

    Resolved with the read-only ``rev-parse --git-dir`` so linked
    worktrees report the directory that actually holds their operation
    markers. Falls back to ``<project>/.git`` when it is a directory.
    """
    rc, out = run_git(project, ["rev-parse", "--git-dir"])
    if rc == 0 and out.strip():
        gd = out.strip()
        if not os.path.isabs(gd):
            gd = os.path.normpath(os.path.join(project, gd))
        return gd
    fallback = os.path.join(project, ".git")
    return fallback if os.path.isdir(fallback) else ""


def detect_operations(project: str) -> list[dict]:
    """In-progress git operations, from git-dir marker files only.

    Git records an unfinished operation as marker state inside the git
    dir: ``MERGE_HEAD`` for a merge, a ``rebase-merge`` / ``rebase-apply``
    directory for a rebase, ``CHERRY_PICK_HEAD``, ``REVERT_HEAD``, and
    ``BISECT_LOG``. Their presence is a repo fact, read here as plain
    files (no git command runs, nothing is written). Each entry names
    the marker as its source. A marker left behind by a crashed git
    process reads as in-progress; the pack states the detection method
    in its limits so a reader can judge.
    """
    gd = _git_dir(project)
    if not gd:
        return []
    ops: list[dict] = []

    for dirname in ("rebase-merge", "rebase-apply"):
        full = os.path.join(gd, dirname)
        if os.path.isdir(full):
            entry = {"operation": "rebase", "source": f".git/{dirname}"}
            head_name = _read_marker_file(os.path.join(full, "head-name"))
            if head_name:
                from .redact import clean_line
                entry["branch"] = clean_line(
                    head_name.removeprefix("refs/heads/"), 120)
            onto = _read_marker_file(os.path.join(full, "onto"))
            if _HEX_RE.match(onto):
                entry["onto"] = onto
            ops.append(entry)
            break

    for filename, operation in (("MERGE_HEAD", "merge"),
                                ("CHERRY_PICK_HEAD", "cherry-pick"),
                                ("REVERT_HEAD", "revert")):
        full = os.path.join(gd, filename)
        if os.path.isfile(full):
            entry = {"operation": operation, "source": f".git/{filename}"}
            head = _read_marker_file(full)
            if _HEX_RE.match(head):
                entry["head"] = head
            ops.append(entry)

    if os.path.isfile(os.path.join(gd, "BISECT_LOG")):
        ops.append({"operation": "bisect", "source": ".git/BISECT_LOG"})
    return ops


def _parse_shortstat(text: str) -> dict:
    """Parse ``git diff --shortstat`` output into counts.

    Returns ``{"files_changed", "insertions", "deletions"}``, all
    zero when the text is empty or unrecognised (a clean diff).
    """
    out = {"files_changed": 0, "insertions": 0, "deletions": 0}
    m = re.search(r"(\d+) files? changed", text)
    if m:
        out["files_changed"] = int(m.group(1))
    m = re.search(r"(\d+) insertions?\(\+\)", text)
    if m:
        out["insertions"] = int(m.group(1))
    m = re.search(r"(\d+) deletions?\(-\)", text)
    if m:
        out["deletions"] = int(m.group(1))
    return out


def _log_args(window: dict, extra: list[str]) -> list[str]:
    """Build a ``git log`` argument list scoped to ``window``.

    A ref window becomes a ``ref..HEAD`` range; a time window becomes
    a ``--since=...`` argument appended after ``extra``.
    """
    args = ["log"]
    if window["kind"] == "ref":
        args.append(f"{window['ref']}..HEAD")
    args.extend(extra)
    if window["kind"] == "since":
        args.append(f"--since={window['git_since']}")
    return args


def collect_git(project: str, window: dict, base: str | None,
                max_commits: int = 100, max_files: int = 200) -> dict:
    """Collect every git fact the pack uses. Never writes to the project.

    Returns ``{"available": False, "reason": ...}`` when ``project``
    is not a git work tree (or git is missing); the pack still builds
    with the git section marked unavailable. Otherwise returns a dict
    with ``branch`` / ``detached`` / ``upstream``, ``status`` (staged,
    unstaged, and untracked lists plus counts), ``ahead`` / ``behind``
    (``None`` when there is no upstream), window ``commits`` with a
    truncation flag, staged / unstaged ``diff_*`` stats, an optional
    ``diff_base``, the union of session-touched files, and ``stash``.
    Commit and file lists are capped at ``max_commits`` /
    ``max_files``; the caps are flagged in the result, never silent.
    """
    rc, _ = run_git(project, ["rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        return {"available": False, "reason": "not a git work tree (or git not on PATH)"}

    facts: dict = {"available": True}

    rc, out = run_git(project, ["rev-parse", "HEAD"])
    facts["head"] = out.strip() if rc == 0 else ""
    rc, out = run_git(project, ["rev-parse", "--short", "HEAD"])
    facts["head_short"] = out.strip() if rc == 0 else ""

    # --- status (porcelain v1, -z) -------------------------------------
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    unmerged: list[str] = []
    branch = ""
    upstream = None
    detached = False
    rc, out = run_git(project, ["status", "--porcelain=v1", "-z", "--branch"])
    if rc == 0 and out:
        records = out.split("\0")
        i = 0
        while i < len(records):
            rec = records[i]
            i += 1
            if not rec:
                continue
            if rec.startswith("## "):
                head_line = rec[3:]
                if head_line.startswith("HEAD"):
                    detached = True
                    branch = "HEAD (detached)"
                elif head_line.startswith("No commits yet on "):
                    # Fresh repo: the header is a sentence, the branch
                    # name is only its tail.
                    branch = head_line[len("No commits yet on "):].strip()
                elif head_line.startswith("Initial commit on "):
                    branch = head_line[len("Initial commit on "):].strip()
                else:
                    branch = head_line.split("...")[0].strip()
                    if "..." in head_line:
                        upstream = head_line.split("...")[1].split(" ")[0].strip()
                continue
            if len(rec) < 4:
                continue
            x, y = rec[0], rec[1]
            path = rec[3:]
            if x in "RC" or y in "RC":
                # -z mode: the source path follows as its own record.
                if i < len(records):
                    i += 1
            if x == "?" and y == "?":
                untracked.append(path)
                continue
            if x == "U" or y == "U" or (x, y) in (("A", "A"), ("D", "D")):
                # Unmerged (conflicted) path: it is neither cleanly
                # staged nor cleanly unstaged, so it is reported in
                # its own list instead of being double-counted.
                unmerged.append(path)
                continue
            if x not in " !":
                staged.append(path)
            if y not in " !":
                unstaged.append(path)
    facts["branch"] = branch
    facts["detached"] = detached
    facts["upstream"] = upstream
    facts["status"] = {
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "unmerged": unmerged,
        "staged_count": len(staged),
        "unstaged_count": len(unstaged),
        "untracked_count": len(untracked),
        "unmerged_count": len(unmerged),
    }

    # --- in-progress operations (git-dir marker files) ------------------
    facts["operations"] = detect_operations(project)
    facts["operation_count"] = len(facts["operations"])

    # --- ahead / behind -------------------------------------------------
    facts["ahead"] = None
    facts["behind"] = None
    if upstream:
        # Counted with log ranges so every git call stays on the small
        # read-only subcommand allowlist in run_git.
        rc, out = run_git(project, ["log", "--format=%H", "@{upstream}..HEAD"])
        if rc == 0:
            facts["ahead"] = len([ln for ln in out.splitlines() if ln.strip()])
        rc, out = run_git(project, ["log", "--format=%H", "HEAD..@{upstream}"])
        if rc == 0:
            facts["behind"] = len([ln for ln in out.splitlines() if ln.strip()])

    # --- commits in the session window ---------------------------------
    fmt = "%H%x1f%h%x1f%s%x1f%an%x1f%aI%x1e"
    rc, out = run_git(project, _log_args(window, [f"--format={fmt}", f"-n{max_commits + 1}"]))
    commits = []
    if rc == 0 and out:
        for rec in out.split("\x1e"):
            rec = rec.strip("\n")
            if not rec.strip():
                continue
            parts = rec.split("\x1f")
            if len(parts) != 5:
                continue
            from .redact import clean_line
            commits.append({
                "hash": parts[0],
                "short": parts[1],
                "subject": clean_line(parts[2], 200),
                "author": clean_line(parts[3], 80),
                "time": parts[4],
            })
    facts["commits_truncated"] = len(commits) > max_commits
    facts["commits"] = commits[:max_commits]
    facts["commit_count"] = len(facts["commits"])

    # files touched by those commits
    commit_files: list[str] = []
    if facts["commit_count"]:
        rc, out = run_git(project, _log_args(window, ["--name-only", "--format=%x1e%H"]))
        if rc == 0 and out:
            seen: set[str] = set()
            for block in out.split("\x1e"):
                lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
                # first line of each block is the commit hash from the format
                for ln in lines[1:]:
                    if ln not in seen:
                        seen.add(ln)
                        commit_files.append(ln)
    facts["commit_files"] = commit_files

    # --- diff stats ------------------------------------------------------
    rc, out = run_git(project, ["diff", "--shortstat"])
    facts["diff_unstaged"] = _parse_shortstat(out if rc == 0 else "")
    rc, out = run_git(project, ["diff", "--cached", "--shortstat"])
    facts["diff_staged"] = _parse_shortstat(out if rc == 0 else "")

    facts["diff_base"] = None
    if base and not base.startswith("-"):
        # The base is caller-supplied and lands inside a git argv slot.
        # A value shaped like an option (e.g. --output=<path>) would be
        # parsed by git as an option and can make diff WRITE a file, so
        # the value only reaches the diff call once it verifies as a
        # real commit; anything else simply yields no base diff, the
        # same outcome an unresolvable base already produced.
        rc, _ = run_git(project, ["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"])
        if rc == 0:
            rc, out = run_git(project, ["diff", "--shortstat", f"{base}...HEAD"])
            if rc == 0:
                facts["diff_base"] = {"base": base, **_parse_shortstat(out)}

    # union of session-touched files
    union: list[str] = []
    seen = set()
    for src in (commit_files, staged, unstaged, untracked, unmerged):
        for p in src:
            if p not in seen:
                seen.add(p)
                union.append(p)
    facts["files_changed"] = union[:max_files]
    facts["files_changed_total"] = len(union)
    facts["files_changed_truncated"] = len(union) > max_files

    # --- stash ------------------------------------------------------------
    rc, out = run_git(project, ["stash", "list", "--format=%gd%x1f%gs%x1f%cI"])
    stash = []
    if rc == 0 and out:
        from .redact import clean_line
        for ln in out.splitlines():
            if not ln.strip():
                continue
            parts = ln.split("\x1f")
            if len(parts) == 3:
                stash.append({"ref": parts[0], "message": clean_line(parts[1], 160), "time": parts[2]})
    facts["stash"] = stash
    facts["stash_count"] = len(stash)
    return facts


def list_project_files(project: str, git_facts: dict) -> tuple[list[str], str]:
    """File universe for the marker scan.

    Git projects: tracked plus untracked-but-not-ignored (ls-files).
    Other folders: a bounded walk skipping obvious junk directories.
    Returns (relative paths, source description).
    """
    if git_facts.get("available"):
        rc, out = run_git(project, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
        if rc == 0:
            files = [p for p in out.split("\0") if p]
            return files, "git ls-files (tracked + untracked, not ignored)"
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
            "build", ".tox", ".mypy_cache", ".pytest_cache", "target"}
    files: list[str] = []
    for root, dirs, names in os.walk(project):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for name in names:
            full = os.path.join(root, name)
            files.append(os.path.relpath(full, project))
        if len(files) > 50000:
            break
    return files, "directory walk (junk directories skipped)"
