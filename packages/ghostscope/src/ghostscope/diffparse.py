"""Unified diff parsing.

Produces per-file changes: status (added/modified/deleted/renamed),
hunks with new/old line numbers for added and deleted lines, and the
raw added/deleted line texts. Pure text parsing, no git needed, so
a .diff file from any source can be consumed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[tuple[str, int | None, int | None, str]] = field(default_factory=list)
    # (kind, new_lineno, old_lineno, text) kind in context/added/deleted

    @property
    def added_lines(self) -> list[tuple[int, str]]:
        return [(n, t) for k, n, _o, t in self.lines if k == "added" and n]

    @property
    def deleted_lines(self) -> list[tuple[int, str]]:
        return [(o, t) for k, _n, o, t in self.lines if k == "deleted" and o]

    @property
    def new_lines_expected(self) -> list[str]:
        return [t for k, _n, _o, t in self.lines if k in ("context", "added")]

    @property
    def old_lines_expected(self) -> list[str]:
        return [t for k, _n, _o, t in self.lines if k in ("context", "deleted")]


@dataclass
class FileChange:
    old_path: str | None
    new_path: str | None
    status: str = "modified"  # added | modified | deleted | renamed
    hunks: list[Hunk] = field(default_factory=list)
    is_binary: bool = False

    @property
    def path(self) -> str | None:
        return self.new_path or self.old_path

    @property
    def added(self) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for h in self.hunks:
            out.extend(h.added_lines)
        return out

    @property
    def deleted(self) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for h in self.hunks:
            out.extend(h.deleted_lines)
        return out

    @property
    def added_count(self) -> int:
        return len(self.added)

    @property
    def deleted_count(self) -> int:
        return len(self.deleted)


def _clean_path(raw: str) -> str | None:
    raw = raw.strip()
    if raw == "/dev/null":
        return None
    # strip a/ b/ prefixes and trailing tab+timestamp
    raw = raw.split("\t")[0]
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    return raw


def _check_safe_path(path: str | None) -> None:
    """Reject absolute paths and `..` traversal in diff-supplied paths.

    A diff file is untrusted input: its paths are later joined onto
    the project root and the pack directory. A legitimate git path
    is always relative and never contains a `..` component, so
    anything else is refused loudly instead of followed silently.
    """
    if path is None:
        return
    if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", path) \
            or ".." in path.split("/"):
        raise ValueError(f"diff contains an unsafe path: {path!r}")


def parse_diff(text: str) -> list[FileChange]:
    """Parse unified-diff ``text`` into a list of FileChange objects."""
    changes: list[FileChange] = []
    cur: FileChange | None = None
    cur_hunk: Hunk | None = None
    new_no = old_no = 0
    for line in text.splitlines():
        # A hunk is incomplete while its declared line counts have
        # not been consumed. Inside an incomplete hunk a line such as
        # "--- x" or "+++ x" is hunk *content* (a deleted line whose
        # text starts "-- " / an added line whose text starts "++ "),
        # never a file header: headers only occur between hunks.
        in_hunk = cur_hunk is not None and (
            old_no < cur_hunk.old_start + cur_hunk.old_count
            or new_no < cur_hunk.new_start + cur_hunk.new_count)
        if line.startswith("--- ") and not in_hunk \
                and (cur is None or cur.hunks):
            # Header-less unified diff (plain `diff -u` output has no
            # "diff --git" separator): the --- line itself opens the
            # next file's change. In git diffs the --- line follows a
            # fresh "diff --git" whose change has no hunks yet, so
            # this never fires there.
            cur = FileChange(old_path=None, new_path=None)
            changes.append(cur)
            cur_hunk = None
        if line.startswith("diff --git "):
            cur = FileChange(old_path=None, new_path=None)
            changes.append(cur)
            cur_hunk = None
            m = re.match(r"diff --git a/(.*?) b/(.*)$", line)
            if m:
                cur.old_path, cur.new_path = m.group(1), m.group(2)
            continue
        if cur is None:
            continue
        if line.startswith("new file"):
            cur.status = "added"
            continue
        if line.startswith("deleted file"):
            cur.status = "deleted"
            continue
        if line.startswith("rename from "):
            cur.old_path = line[len("rename from "):].strip()
            cur.status = "renamed"
            continue
        if line.startswith("rename to "):
            cur.new_path = line[len("rename to "):].strip()
            cur.status = "renamed"
            continue
        if line.startswith("Binary files"):
            cur.is_binary = True
            continue
        if line.startswith("--- ") and not in_hunk:
            p = _clean_path(line[4:])
            if p is not None:
                cur.old_path = p
            elif cur.status != "deleted":
                cur.status = "added"
                cur.old_path = None
            if p is None and cur.old_path is None:
                cur.status = "added"
            continue
        if line.startswith("+++ ") and not in_hunk:
            p = _clean_path(line[4:])
            if p is None:
                cur.status = "deleted"
                cur.new_path = None
            else:
                cur.new_path = p
            continue
        m = _HUNK.match(line)
        if m:
            cur_hunk = Hunk(
                old_start=int(m.group(1)), old_count=int(m.group(2) or 1),
                new_start=int(m.group(3)), new_count=int(m.group(4) or 1))
            cur.hunks.append(cur_hunk)
            new_no = cur_hunk.new_start
            old_no = cur_hunk.old_start
            continue
        if cur_hunk is None:
            continue
        if line.startswith("\\"):
            continue
        prefix = line[:1]
        content = line[1:] if prefix in "+- " else line
        if prefix == "+":
            cur_hunk.lines.append(("added", new_no, None, content))
            new_no += 1
        elif prefix == "-":
            cur_hunk.lines.append(("deleted", None, old_no, content))
            old_no += 1
        else:
            cur_hunk.lines.append(("context", new_no, old_no, content))
            new_no += 1
            old_no += 1
    # a file added via --- /dev/null has new_path from +++
    for c in changes:
        if c.old_path is None and c.status == "modified":
            c.status = "added"
        if c.new_path is None and c.status == "modified":
            c.status = "deleted"
        _check_safe_path(c.old_path)
        _check_safe_path(c.new_path)
    return [c for c in changes if c.path]
