"""Change input from local git or a diff file. Local only: every
git invocation is a local read (diff / show), nothing fetches, and
there is no hosting API anywhere in this tool.

Verification discipline: a parsed diff must match the state it
claims.
- base..head input is checked against the blob at `head` for each
  changed file (hunk context+added lines must appear at the hunk's
  new line numbers in that blob).
- --staged input is checked against the index blob (`git show :p`).
- a bare --diff file is checked against the working tree files.
A mismatch raises ScopeInputError naming the file and hunk.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .diffparse import FileChange, parse_diff


class ScopeInputError(ValueError):
    """The change input is missing, ambiguous, or does not match reality."""


def _safe_rel(path: str | None) -> bool:
    """True only for a plain project-relative path (no absolute
    prefix, no `..` component). Diff-supplied paths failing this are
    never joined onto the filesystem or handed to git."""
    if not path:
        return False
    if path.startswith(("/", "\\")):
        return False
    return ".." not in path.split("/")


# errors="replace" everywhere below: a changed blob may be binary or
# non-UTF-8, and strict text decoding would crash the whole pack
# with a UnicodeDecodeError instead of treating it as content.
def _git(root: Path, args: list[str]) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise ScopeInputError(
            f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def is_git_repo(root: str | Path) -> bool:
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-dir"],
                          capture_output=True, text=True, errors="replace")
    return proc.returncode == 0


def git_show(root: str | Path, ref_path: str) -> str | None:
    proc = subprocess.run(["git", "-C", str(root), "show", ref_path],
                          capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        return None
    return proc.stdout


def ref_exists(root: str | Path, ref: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "--quiet",
         ref + "^{commit}"], capture_output=True, text=True,
        errors="replace")
    return proc.returncode == 0


class ChangeInput:
    def __init__(self, mode: str, diff_text: str, changes: list[FileChange],
                 base: str | None = None, head: str | None = None):
        self.mode = mode            # "range" | "staged" | "diff-file"
        self.diff_text = diff_text
        self.changes = changes
        self.base = base
        self.head = head

    def head_content(self, root: Path, change: FileChange) -> str | None:
        """Content of the file on the 'new' side of the change."""
        if change.status == "deleted":
            return None
        if not _safe_rel(change.new_path):
            return None
        if self.mode == "range" and self.head:
            return git_show(root, f"{self.head}:{change.new_path}")
        if self.mode == "staged":
            return git_show(root, f":{change.new_path}")
        p = root / (change.new_path or "")
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
        return None

    def base_content(self, root: Path, change: FileChange) -> str | None:
        """Content of the file on the 'old' side, where recoverable."""
        if change.status == "added":
            return None
        if not _safe_rel(change.old_path):
            return None
        if self.mode == "range" and self.base:
            return git_show(root, f"{self.base}:{change.old_path}")
        if self.mode in ("staged", "diff-file"):
            return git_show(root, f"HEAD:{change.old_path}")
        return None


def verify_diff(root: Path, inp: ChangeInput) -> None:
    """Raise ScopeInputError if any hunk does not match its source."""
    for change in inp.changes:
        if change.is_binary or not change.hunks:
            continue
        content = inp.head_content(root, change)
        if change.status == "deleted":
            continue
        if content is None:
            raise ScopeInputError(
                f"diff mismatch: {change.path} is named by the diff but "
                f"no content for it could be found on the new side")
        file_lines = content.splitlines()
        for idx, hunk in enumerate(change.hunks, 1):
            expected = hunk.new_lines_expected
            start = hunk.new_start - 1
            actual = file_lines[start:start + len(expected)]
            if actual != expected:
                raise ScopeInputError(
                    f"diff mismatch: {change.path} hunk {idx} "
                    f"(@@ -{hunk.old_start} +{hunk.new_start}) does not "
                    f"match the content it claims to describe; the diff "
                    f"may be stale or against a different base")


def load_change_input(project: str | Path, *, base: str | None = None,
                      head: str | None = None, staged: bool = False,
                      diff_file: str | Path | None = None,
                      verify: bool = True) -> ChangeInput:
    """Load exactly one change input for ``project`` and verify it.

    Choose a ``base``/``head`` range, ``staged``, or a ``diff_file``;
    giving none or more than one raises ScopeInputError, as does a
    diff that does not match the content it claims (unless
    ``verify`` is False).
    """
    root = Path(project).expanduser().resolve()
    given = sum(bool(x) for x in (bool(base or head), staged, bool(diff_file)))
    if given != 1:
        raise ScopeInputError(
            "choose exactly one change input: --base/--head, --staged, or --diff")
    if diff_file:
        text = Path(diff_file).read_text(encoding="utf-8", errors="replace")
        inp = ChangeInput("diff-file", text, parse_diff(text))
    elif staged:
        if not is_git_repo(root):
            raise ScopeInputError(f"{root} is not a git repository")
        text = _git(root, ["diff", "--cached"])
        inp = ChangeInput("staged", text, parse_diff(text))
    else:
        if not is_git_repo(root):
            raise ScopeInputError(f"{root} is not a git repository")
        base = base or "HEAD~1"
        head = head or "HEAD"
        for ref in (base, head):
            if not ref_exists(root, ref):
                raise ScopeInputError(f"git ref not found: {ref}")
        text = _git(root, ["diff", f"{base}...{head}"])
        if not text.strip():
            text = _git(root, ["diff", f"{base}..{head}"])
        inp = ChangeInput("range", text, parse_diff(text), base=base, head=head)
    if not inp.changes:
        raise ScopeInputError("the change input contains no file changes")
    if verify:
        verify_diff(root, inp)
    return inp
