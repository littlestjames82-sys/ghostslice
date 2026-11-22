"""Unified diff parsing.

Per-file changes: status (added/modified/deleted/renamed/copied),
hunks with new/old line numbers, raw added/deleted line texts, and
file mode changes. Pure text parsing, no git needed, so a .diff file
from any source can be consumed.

Polish (Oct 14, 2026) parsing rules, each pinned by a regression
test in tests/test_polish.py:
- Git quotes paths that contain spaces or non-ASCII characters
  (``diff --git "a/my file.py" "b/my file.py"`` and quoted ---/+++
  lines). Quoted paths are C-unquoted (octal escapes included) so
  the reported path is the real path, never the quoted spelling.
- A deleted/added line whose *content* starts with ``-- ``/``++ ``
  appears in the diff as ``--- ``/``+++ `` and must not be mistaken
  for a file header once a hunk has started. ---/+++ are headers
  only before the first hunk of a file, or when an exact ---/+++
  pair is immediately followed by a new hunk header (header-less
  multi-file diffs).
- ``old mode``/``new mode`` lines are recorded, so a mode-only
  change is reported as a mode change instead of a silent 0/0 edit.
- ``copy from``/``copy to`` produce status ``copied``, not
  ``renamed``: the source file still exists after a copy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Hunk:
    """One ``@@`` hunk: its starting line numbers and counted lines."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list = field(default_factory=list)
    # (kind, new_lineno, old_lineno, text) kind in context/added/deleted

    @property
    def added_lines(self):
        return [(n, t) for k, n, _o, t in self.lines if k == "added" and n]

    @property
    def deleted_lines(self):
        return [(o, t) for k, _n, o, t in self.lines if k == "deleted" and o]


@dataclass
class FileChange:
    """One file's change in a diff: paths, status, hunks, and modes."""

    old_path: str | None = None
    new_path: str | None = None
    status: str = "modified"  # added | modified | deleted | renamed | copied
    hunks: list = field(default_factory=list)
    is_binary: bool = False
    # True when the --- / +++ header for that side was /dev/null,
    # i.e. the file did not exist on that side of the change. Kept
    # separately from the paths because both are None then.
    saw_old_null: bool = False
    saw_new_null: bool = False
    old_mode: str | None = None
    new_mode: str | None = None

    @property
    def path(self):
        return self.new_path or self.old_path

    @property
    def mode_changed(self):
        return self.old_mode is not None and self.new_mode is not None \
            and self.old_mode != self.new_mode

    @property
    def added(self):
        out = []
        for h in self.hunks:
            out.extend(h.added_lines)
        return out

    @property
    def deleted(self):
        out = []
        for h in self.hunks:
            out.extend(h.deleted_lines)
        return out

    @property
    def added_count(self):
        return len(self.added)

    @property
    def deleted_count(self):
        return len(self.deleted)


def _c_unquote(raw: str) -> str:
    """Decode a git C-style quoted path body (without the quotes)."""
    out = bytearray()
    i = 0
    simple = {"n": 10, "t": 9, "\\": 92, '"': 34}
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt in "01234567":
                j = i + 1
                digits = ""
                while j < len(raw) and len(digits) < 3 \
                        and raw[j] in "01234567":
                    digits += raw[j]
                    j += 1
                # Git only emits byte values (\000-\377); a malformed
                # escape above that must not crash the parse.
                out.append(int(digits, 8) % 256)
                i = j
                continue
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
        out.extend(ch.encode("utf-8", errors="replace"))
        i += 1
    return out.decode("utf-8", errors="replace")


def _clean_path(raw: str):
    """Normalise a diff path: ``/dev/null`` to None, drop the ``a/``/``b/``
    prefix and any tab suffix, and C-unquote a quoted path."""
    # The tab split comes first: traditional diff -u headers carry a
    # timestamp after a tab, and "/dev/null\t<timestamp>" must still
    # be recognised as /dev/null, not as a path named "/dev/null".
    raw = raw.strip().split("\t")[0].strip()
    if raw == "/dev/null":
        return None
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        raw = _c_unquote(raw[1:-1])
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    return raw


def _maybe_quoted_path(raw: str):
    """Path from a rename/copy header line: C-unquote it when git
    quoted it, otherwise take it verbatim (these lines carry no
    a/ or b/ prefix)."""
    raw = raw.strip()
    return _clean_path(raw) if raw.startswith('"') else raw


def _git_header_paths(line: str):
    """(old, new) from a 'diff --git ...' line, quoted or not."""
    rest = line[len("diff --git "):].strip()
    tokens: list = []
    i = 0
    while i < len(rest):
        if rest[i] == " ":
            i += 1
            continue
        if rest[i] == '"':
            j = i + 1
            body = ""
            while j < len(rest):
                if rest[j] == "\\" and j + 1 < len(rest):
                    body += rest[j:j + 2]
                    j += 2
                    continue
                if rest[j] == '"':
                    break
                body += rest[j]
                j += 1
            tokens.append(_c_unquote(body))
            i = j + 1
        else:
            j = rest.find(" ", i)
            if j == -1:
                j = len(rest)
            tokens.append(rest[i:j])
            i = j
    if len(tokens) >= 3:
        # Unquoted paths may themselves contain spaces: the split
        # point is the LAST token starting with b/ that leaves an
        # a/ path before it. Fall back to a regex split.
        m = re.match(r"a/(.*) b/(.*)$", rest)
        if m:
            return m.group(1), m.group(2)
        return None, None
    if len(tokens) == 2:
        old, new = tokens
        if old.startswith("a/"):
            old = old[2:]
        if new.startswith("b/"):
            new = new[2:]
        return old, new
    return None, None


def parse_diff(text: str) -> list:
    """Parse unified *text* into a list of :class:`FileChange`.

    Accepts git diffs and header-less ``---``/``+++`` diffs. Text with
    no recognisable file changes returns an empty list; callers treat
    that as could-not-review, not as a clean change.
    """
    changes: list = []
    cur: FileChange | None = None
    cur_hunk: Hunk | None = None
    new_no = old_no = 0
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.startswith("diff --git "):
            cur = FileChange()
            changes.append(cur)
            cur_hunk = None
            old, new = _git_header_paths(line)
            if old is not None:
                cur.old_path, cur.new_path = old, new
            continue
        if cur is None:
            # Tolerate diffs without the git header (---/+++ only).
            if line.startswith("--- "):
                first = _clean_path(line[4:])
                cur = FileChange(old_path=first,
                                 saw_old_null=first is None)
                changes.append(cur)
            continue
        if line.startswith("new file"):
            cur.status = "added"
            m = re.search(r"mode (\d+)", line)
            if m:
                cur.new_mode = m.group(1)
            continue
        if line.startswith("deleted file"):
            cur.status = "deleted"
            m = re.search(r"mode (\d+)", line)
            if m:
                cur.old_mode = m.group(1)
            continue
        if line.startswith("old mode "):
            cur.old_mode = line[len("old mode "):].strip()
            continue
        if line.startswith("new mode "):
            cur.new_mode = line[len("new mode "):].strip()
            continue
        if line.startswith("rename from "):
            cur.old_path = _maybe_quoted_path(line[len("rename from "):])
            cur.status = "renamed"
            continue
        if line.startswith("rename to "):
            cur.new_path = _maybe_quoted_path(line[len("rename to "):])
            cur.status = "renamed"
            continue
        if line.startswith("copy from "):
            cur.old_path = _maybe_quoted_path(line[len("copy from "):])
            cur.status = "copied"
            continue
        if line.startswith("copy to "):
            cur.new_path = _maybe_quoted_path(line[len("copy to "):])
            cur.status = "copied"
            continue
        if line.startswith("Binary files") or line.startswith("GIT binary patch"):
            cur.is_binary = True
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            # File headers appear before the first hunk. Once a hunk
            # has started, a ---/+++ pair is content (a deleted line
            # whose text starts with "-- " plus an added line whose
            # text starts with "++ ") UNLESS the pair is immediately
            # followed by a new hunk header, which is the header-less
            # multi-file shape.
            is_header = cur_hunk is None
            if cur_hunk is not None and line.startswith("--- ") \
                    and i < len(lines) and lines[i].startswith("+++ "):
                after = lines[i + 1] if i + 1 < len(lines) else ""
                if after.startswith("@@ ") or after.startswith("diff --git ") \
                        or after.startswith("--- "):
                    is_header = True
                    cur = FileChange()
                    changes.append(cur)
                    cur_hunk = None
            if is_header:
                p = _clean_path(line[4:])
                if line.startswith("--- "):
                    if p is not None:
                        cur.old_path = p
                    else:
                        cur.saw_old_null = True
                elif p is not None:
                    cur.new_path = p
                else:
                    cur.saw_new_null = True
                continue
            # Not a header: fall through to hunk content handling.
        m = _HUNK.match(line)
        if m:
            cur_hunk = Hunk(
                old_start=int(m.group(1)), old_count=int(m.group(2) or 1),
                new_start=int(m.group(3)), new_count=int(m.group(4) or 1))
            cur.hunks.append(cur_hunk)
            old_no, new_no = cur_hunk.old_start, cur_hunk.new_start
            continue
        if cur_hunk is None:
            continue
        if line.startswith("\\"):
            # "\ No newline at end of file": a marker about the
            # previous line, never a line itself. Counts and line
            # numbers are unaffected by skipping it.
            continue
        if line.startswith("+"):
            cur_hunk.lines.append(("added", new_no, None, line[1:]))
            new_no += 1
        elif line.startswith("-"):
            cur_hunk.lines.append(("deleted", None, old_no, line[1:]))
            old_no += 1
        else:
            text_line = line[1:] if line.startswith(" ") else line
            cur_hunk.lines.append(("context", new_no, old_no, text_line))
            new_no += 1
            old_no += 1
    # Normalise status for header-less / minimal diffs.
    for c in changes:
        # A /dev/null header side is explicit evidence the file was
        # created or deleted, even when the diff carries no git
        # "new file"/"deleted file" line (plain diff -u output).
        if c.saw_new_null and c.old_path and c.status == "modified":
            c.status = "deleted"
        elif c.saw_old_null and c.new_path and c.status == "modified":
            c.status = "added"
        if c.status == "modified" and c.old_path and c.new_path \
                and c.old_path != c.new_path:
            # ---/+++ name change without an explicit rename header.
            c.status = "renamed"
    return [c for c in changes if c.path]
