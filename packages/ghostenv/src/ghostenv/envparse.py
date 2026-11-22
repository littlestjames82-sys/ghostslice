"""Names-only parsing of .env-style files and .ghostenv.json config.

The parser splits each line at the first ``=`` and discards the
right-hand side immediately. The discarded text is never assigned to
a variable that outlives the line, never logged, and never returned.
Callers receive :class:`EnvEntry` records: a name, a line number,
and present/absent booleans only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# KEY, export KEY, KEY=..., export KEY=... ; capture group 1 is the name.
_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|$)")

EXAMPLE_CANDIDATES = (".env.example", ".env.sample", ".env.template")


@dataclass
class EnvFileResult:
    """Result of parsing one env-style file. Names only, by design."""

    path: str | None          # path as given by caller, or None if absent
    present: bool             # whether the file existed and was read
    entries: list = field(default_factory=list)  # list[EnvEntry]
    # Line numbers of non-blank, non-comment lines that are not
    # NAME-shaped. Numbers only: a malformed line's content may BE a
    # bare value, so it is never captured or returned.
    malformed: list = field(default_factory=list)  # list[int]

    @property
    def names(self) -> list[str]:
        """Sorted unique variable names found in the file."""
        return sorted({e.name for e in self.entries})

    def duplicates(self) -> list[dict]:
        """Names defined more than once, as ``{"name", "lines"}``
        dicts sorted by name. Names and line numbers only."""
        by_name: dict[str, list[int]] = {}
        for e in self.entries:
            by_name.setdefault(e.name, []).append(e.line)
        return [
            {"name": n, "lines": ls}
            for n, ls in sorted(by_name.items()) if len(ls) > 1
        ]


@dataclass
class EnvEntry:
    name: str
    line: int


def _bomless(text: str) -> str:
    """Drop one leading UTF-8 BOM (U+FEFF).

    Windows editors commonly save .env files with a BOM; without
    this the first line's name is anchored after the BOM, fails the
    name pattern, and is misreported as malformed while its (never
    shown) value sits on a line classified as content-free."""
    return text[1:] if text.startswith("\ufeff") else text


def is_valid_name(name: str) -> bool:
    """True when *name* matches ``[A-Za-z_][A-Za-z0-9_]*``."""
    return bool(_NAME_RE.match(name or ""))


def parse_env_text(text: str) -> list[EnvEntry]:
    """Parse env-style text, returning names + line numbers only.

    The right-hand side of an assignment is sliced off by regex
    construction: the pattern is anchored and captures only the name;
    the rest of the line is never captured or stored.
    """
    entries: list[EnvEntry] = []
    for lineno, raw in enumerate(_bomless(text).splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _LINE_RE.match(raw)
        if not m:
            continue
        name = m.group(1)
        if is_valid_name(name):
            entries.append(EnvEntry(name=name, line=lineno))
    return entries


def malformed_lines(text: str) -> list[int]:
    """Line numbers of lines that are neither blank, comment, nor
    NAME-shaped. Numbers only, by the same names-only construction:
    the line's content is examined for shape and never stored."""
    out: list[int] = []
    for lineno, raw in enumerate(_bomless(text).splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not _LINE_RE.match(raw):
            out.append(lineno)
    return out


def parse_env_file(path) -> EnvFileResult:
    """Parse the env-style file at *path* into an
    :class:`EnvFileResult`. A missing file is not an error: the
    result has ``present=False`` and no entries, and callers
    report the absence as a finding."""
    p = Path(path)
    if not p.is_file():
        return EnvFileResult(path=str(p), present=False, entries=[])
    # errors="replace": a corrupt byte in a *value* must not crash a
    # names-only scan; the value is discarded line by line anyway.
    text = p.read_text(encoding="utf-8", errors="replace")
    return EnvFileResult(path=str(p), present=True,
                         entries=parse_env_text(text),
                         malformed=malformed_lines(text))


def find_example_file(project: Path) -> Path | None:
    """First existing example file in *project*, trying
    ``.env.example``, ``.env.sample``, then ``.env.template``;
    ``None`` when none of them exists."""
    for cand in EXAMPLE_CANDIDATES:
        p = project / cand
        if p.is_file():
            return p
    return None


def load_config(project: Path) -> dict:
    """Load optional .ghostenv.json: {"external": [...], "ignore": [...]}.

    Only name lists and glob strings are honoured. Any other keys are
    ignored. Invalid names in ``external`` are dropped.
    """
    cfg_path = project / ".ghostenv.json"
    config = {"external": [], "ignore": []}
    if not cfg_path.is_file():
        return config
    try:
        data = json.loads(_bomless(cfg_path.read_text(
            encoding="utf-8", errors="replace")))
    except (OSError, ValueError):
        return config
    if isinstance(data, dict):
        ext = data.get("external") or []
        if isinstance(ext, list):
            config["external"] = sorted(
                {str(x) for x in ext if is_valid_name(str(x))})
        ign = data.get("ignore") or []
        if isinstance(ign, list):
            config["ignore"] = [str(x) for x in ign]
    return config
