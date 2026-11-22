"""Section model: chunk boundaries are document sections, never arbitrary splits."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .tokens import estimate_tokens

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_DATE_PATTERNS = [
    re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])-([0-3]\d)\b"),
    re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+([0-3]?\d),\s+(20\d{2})\b"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def find_date(text: str) -> str | None:
    """First explicit ISO or 'Month D, YYYY' date in the text, normalised to ISO.

    "First" means first in the document, across both formats (the old code
    always preferred an ISO date, however late in the text it appeared),
    and the date must be a real calendar date: shapes like 2024-02-31 or
    2026-03-39 are skipped, not treated as a document's date.
    Returns ``None`` when the text carries no such date; callers then
    fall back to the file modification date.
    """
    from datetime import date as _date

    candidates: list[tuple[int, str]] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            try:
                if pat is _DATE_PATTERNS[0]:
                    parsed = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                else:
                    parsed = _date(int(m.group(3)), _MONTHS[m.group(1)],
                                   int(m.group(2)))
            except ValueError:
                continue
            candidates.append((m.start(), parsed.isoformat()))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


@dataclass
class Section:
    """One heading-delimited piece of a document.

    ``heading_trail`` is the chain of ancestor headings (outermost
    first), so a chunk can be identified without its whole document.
    ``index`` is the section's position within its document.
    """

    doc_path: str
    index: int
    title: str
    heading_trail: list[str] = field(default_factory=list)
    text: str = ""

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def split_sections(doc_path: str, text: str) -> list[Section]:
    """Split on Markdown-style headings; heading-less docs are one section."""
    sections: list[Section] = []
    trail: list[str] = []
    cur_title = Path_title(doc_path)
    cur_lines: list[str] = []

    def flush():
        body = "\n".join(cur_lines).strip()
        if body or not sections:
            sections.append(Section(doc_path=doc_path, index=len(sections),
                                    title=cur_title, heading_trail=list(trail),
                                    text=body))

    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            # a '#' line inside a fenced code block is code, not a heading
            in_fence = not in_fence
            cur_lines.append(line)
            continue
        m = None if in_fence else _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            cur_title = m.group(2).strip()
            trail = trail[:level - 1] + [cur_title]
            cur_lines = [line]
        else:
            cur_lines.append(line)
    flush()
    return [s for s in sections if s.text] or sections


def Path_title(doc_path: str) -> str:
    """Fallback title for a heading-less document, from its file name.

    For example ``returns-policy.md`` becomes ``returns policy``.
    (The capitalised name is kept for compatibility.)
    """
    name = doc_path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0].replace("-", " ").replace("_", " ")


def first_paragraph(text: str) -> str:
    """Return the first non-heading paragraph block in *text*, or ``""``."""
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if block and not block.startswith("#"):
            return block
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    return lines[0] if lines else ""


def headings_render(section: Section) -> str:
    """Headings mode: heading trail + first paragraph only."""
    parts = []
    for i, h in enumerate(section.heading_trail or [section.title]):
        parts.append(f"{'#' * (i + 1)} {h}")
    para = first_paragraph(section.text)
    if para:
        parts.append(para)
    return "\n\n".join(parts)
