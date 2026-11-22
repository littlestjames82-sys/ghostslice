"""Text helpers: DEPS.md section slicing and the wording scan."""
from __future__ import annotations

import re

# Section keys -> heading phrase variants. The plan names the sections
# declared-and-used / declared-not-imported / imported-not-declared /
# pins as recorded; the shipped core titles them "Declared and
# imported", "Declared, no import found in scanned code", "Imported,
# no declaration found", and "Version pins as recorded". Both namings
# are accepted here; a section must exist under one of them.
SECTION_PATTERNS = {
    "declared_and_used": r"declared\s+and\s+(?:used|imported)",
    "declared_not_imported": (
        r"declared,?\s+no import found|declared[\s-]+not[\s-]+imported"),
    "imported_not_declared": (
        r"imported,?\s+no declaration found"
        r"|imported[\s-]+not[\s-]+declared"),
    "pins": r"pins\b",
}

# Verdict wording that must never appear in a generated report
# (PLAN.md verification bar, extended with the task-level rule that no
# vulnerability or safety verdict wording appears at all).
BANNED_PHRASES = [
    "safe to remove",
    "vulnerable",
    "vulnerability",
    "vulnerabilities",
    "outdated",
    "latest version",
    "dead code",
    "security risk",
    "critical severity",
]


def section_bodies(markdown: str) -> dict[str, str]:
    """Slice a DEPS.md text into sections by its markdown headings.

    Only heading lines (starting with #) open a section, so summary
    lines that repeat the section names do not confuse the slicing.
    Returns only the sections found; callers assert presence.
    """
    lines = markdown.splitlines(keepends=True)
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)

    headings: list[tuple[int, str]] = []  # (char offset, line text)
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            headings.append((offsets[i], line.strip().lstrip("#").strip()))

    bodies: dict[str, str] = {}
    for idx, (start, title) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(markdown)
        lowered = title.lower()
        for key, pattern in SECTION_PATTERNS.items():
            if key not in bodies and re.search(pattern, lowered):
                bodies[key] = markdown[start:end]
                break
    return bodies


def banned_hits(*texts: str) -> list[str]:
    """Return any banned verdict phrases found in the given texts."""
    found = []
    for text in texts:
        lowered = (text or "").lower()
        for phrase in BANNED_PHRASES:
            if phrase in lowered:
                found.append(phrase)
    return sorted(set(found))
