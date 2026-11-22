"""Corpus profile: .ghostdocs.json in the corpus folder."""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

PROFILE_NAME = ".ghostdocs.json"


@dataclass
class Profile:
    """Settings from a corpus's optional ``.ghostdocs.json`` file.

    All fields are optional in the file; a corpus with no settings
    file uses the defaults shown here. Patterns are filename globs
    matched against paths relative to the corpus root. See
    :func:`load_profile` for validation, and the README's Settings
    section for a worked example.
    """

    include: list[str] = field(default_factory=list)          # globs, empty = all
    exclude: list[str] = field(default_factory=list)          # globs
    authoritative_sources: list[str] = field(default_factory=list)  # path prefixes/globs
    modes: dict[str, str] = field(default_factory=dict)       # glob -> full|headings|exclude
    superseded: str = "exclude"  # exclude (from exports, kept in reports) | include
    source_path: str | None = None

    def mode_for(self, rel: str) -> str:
        """Inclusion mode for *rel*: ``full`` (default), ``headings``, or ``exclude``."""
        for glob, mode in self.modes.items():
            if fnmatch.fnmatch(rel, glob):
                return mode
        return "full"

    def is_authoritative(self, rel: str) -> bool:
        """True when *rel* falls under an authoritative source.

        The authoritative version of a duplicate wins conflict picks
        and is protected when an export is fitted to a token budget.
        """
        for pat in self.authoritative_sources:
            if fnmatch.fnmatch(rel, pat):
                return True
            # a bare prefix names a folder (or one exact file): it must stop
            # at a path boundary, so "off" does not claim "office/guide.md"
            base = pat.rstrip("/")
            if rel == base or rel.startswith(base + "/"):
                return True
        return False

    def included(self, rel: str) -> bool:
        """True when *rel* passes the include/exclude globs and is not mode-excluded."""
        if self.include and not any(fnmatch.fnmatch(rel, g) for g in self.include):
            return False
        if any(fnmatch.fnmatch(rel, g) for g in self.exclude):
            return False
        return self.mode_for(rel) != "exclude"


def load_profile(corpus: Path) -> Profile:
    """Load and validate ``.ghostdocs.json`` from *corpus*, if present.

    Returns a default profile when the file is absent. Raises
    ``ValueError`` (shown to the user as an error, exit code 2) for
    unreadable JSON, unknown keys, or invalid mode/superseded values,
    rather than silently ignoring a mistyped settings file.
    """
    p = corpus / PROFILE_NAME
    if not p.exists():
        return Profile()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {PROFILE_NAME}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid {PROFILE_NAME}: top level must be an object")
    known = {"include", "exclude", "authoritative_sources", "modes", "superseded"}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"invalid {PROFILE_NAME}: unknown keys {sorted(unknown)}")
    modes = data.get("modes", {}) or {}
    if not isinstance(modes, dict):
        raise ValueError(f"invalid {PROFILE_NAME}: modes must be an object")
    for mode in modes.values():
        if mode not in ("full", "headings", "exclude"):
            raise ValueError(f"invalid {PROFILE_NAME}: mode must be full|headings|exclude, got {mode!r}")
    superseded = data.get("superseded", "exclude")
    if superseded not in ("exclude", "include"):
        raise ValueError(f"invalid {PROFILE_NAME}: superseded must be exclude|include")

    def _str_list(key: str) -> list[str]:
        # a bare string here used to be list()-split into single characters
        # (include="*.md" became ['*', '.', 'm', 'd']) and matched nothing
        # the user meant; a non-string item crashed fnmatch much later
        value = data.get(key, []) or []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"invalid {PROFILE_NAME}: {key} must be a list of strings")
        return list(value)

    return Profile(include=_str_list("include"),
                   exclude=_str_list("exclude"),
                   authoritative_sources=_str_list("authoritative_sources"),
                   modes=dict(modes), superseded=superseded,
                   source_path=str(p))
