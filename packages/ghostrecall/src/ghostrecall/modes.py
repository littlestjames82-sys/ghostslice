"""Memory slicer modes (extractive only, no LLM summarising).

full           whole item text / decision with reason
decision-only  decision line + date, reason stripped (notes: first line)
headings       headings plus the first paragraph under each
recent         handled at selection time (last N by date); slicing = full
exclude        empty; the item is still recorded in the manifest
"""
from __future__ import annotations
import re

def slice_item(item, mode: str) -> str:
    """Return *item*'s text sliced to *mode* (see the table in README.md).

    Extractive only: the result is built from the item's own lines
    (``decision-only`` keeps the decision line and prefixes its date),
    never newly written prose. ``recent`` slices like ``full`` here
    because the last-N cut happens at selection time. Raises
    ValueError for an unknown mode.
    """
    if mode == "exclude":
        return ""
    if mode in ("full", "recent"):
        return item.text
    if mode == "decision-only":
        if item.source_type == "decision":
            dec = getattr(item, "decision_text", "") or item.title
            date = item.provenance.date
            return (f"{date}: {dec}" if date else dec).strip()
        lines = [ln for ln in item.text.splitlines() if ln.strip()]
        return lines[0] if lines else ""
    if mode == "headings":
        out: list[str] = []
        lines = item.text.splitlines()
        i = 0
        while i < len(lines):
            ln = lines[i]
            if ln.startswith("#"):
                out.append(ln)
                # first non-empty paragraph line after the heading
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                para: list[str] = []
                while j < len(lines) and lines[j].strip() and not lines[j].startswith("#"):
                    para.append(lines[j]); j += 1
                if para:
                    out.append(para[0])
                i = j
            else:
                i += 1
        if not out:  # no headings: first line stands in for the heading level
            first = [ln for ln in lines if ln.strip()]
            return first[0] if first else ""
        return "\n".join(out)
    raise ValueError(f"unknown mode: {mode!r}")
