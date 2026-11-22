"""Task sources. Two honest modes, always labelled:

- user-split: the user pre-split the work in a task file:
      ## Subtask title
      Free text describing this subtask...
  Sections start at a '## ' heading. Text before the first heading is
  an error (it would be a subtask with no title).
- auto-clustered: one freeform --task string; GhostShard clusters the
  graph. Heuristic, and labelled heuristic in every artifact.
No LLM is used in either mode. Subtask text is never invented: in
auto mode the shard task text is a generated graph description (files
owned + why), labelled as generated, not a made-up prompt.
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Subtask:
    """One user-supplied subtask: a ``## `` heading plus its free text."""

    title: str
    text: str

def parse_task_file(text: str) -> list[Subtask]:
    """Parse a user-split task file into a list of :class:`Subtask`.

    Format: each subtask starts at a ``## Heading`` line; the lines
    below it are that subtask's text. ``#`` comment lines before the
    first heading are ignored.

    Raises:
        ValueError: if non-comment text appears before the first
            heading, if there are no ``## `` sections, or if a
            heading has an empty title.
    """
    subs: list[Subtask] = []
    cur_title, cur_lines = None, []
    def flush():
        if cur_title is not None:
            subs.append(Subtask(cur_title, "\n".join(cur_lines).strip()))
    for line in text.splitlines():
        if line.startswith("## "):
            flush(); cur_title = line[3:].strip(); cur_lines = []
        elif cur_title is None:
            if line.strip() and not line.lstrip().startswith("#"):
                raise ValueError("task file: content before first '## ' subtask heading")
        else:
            cur_lines.append(line)
    flush()
    if not subs:
        raise ValueError("task file: no '## ' subtask sections found")
    if any(not s.title for s in subs):
        raise ValueError("task file: empty subtask title")
    return subs

def slugify(title: str) -> str:
    """Slugify a shard title for use in a shard id.

    Lowercases, replaces each run of non-alphanumeric characters
    with ``-``, trims leading/trailing ``-``, and truncates to 40
    characters. Returns ``"shard"`` when nothing usable remains.
    Example: ``"cluster: alpha.py"`` becomes ``"cluster-alpha-py"``.
    """
    import re
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40] or "shard"
