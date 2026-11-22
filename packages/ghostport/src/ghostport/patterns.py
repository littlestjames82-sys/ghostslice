"""Pattern pack format + loader.

A pack is a JSON data file. Every pattern MUST carry an id, a plain-words
description, a source reference and a reference_date. An undated or
unreferenced pattern is a bug and pack loading refuses it (PLAN: Risks).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

KINDS = {"import_module", "import_from", "attribute", "attribute_or_name"}


class PackError(ValueError):
    """Raised when a pattern pack is missing, malformed, or undated."""


@dataclass
class Pattern:
    """One migration pattern: id, plain-words description, dated source
    reference, and the matcher that finds it in a syntax tree.
    """
    id: str
    description: str
    reference: str
    reference_date: str
    reference_url: str
    matcher: dict

    def to_dict(self):
        """Return this pattern as a plain dict (the pack JSON shape)."""
        return {"id": self.id, "description": self.description,
                "reference": self.reference, "reference_date": self.reference_date,
                "reference_url": self.reference_url, "matcher": self.matcher}


@dataclass
class Pack:
    """A validated pattern pack: metadata plus its Pattern list."""
    id: str
    title: str
    version: str
    date: str
    language: str
    target: str
    patterns: list = field(default_factory=list)
    source_path: str = ""

    def to_dict(self):
        """Return this pack as a plain dict (the pack JSON shape)."""
        return {"id": self.id, "title": self.title, "version": self.version,
                "date": self.date, "language": self.language, "target": self.target,
                "patterns": [p.to_dict() for p in self.patterns]}


def _builtin_pack_path(pack_id: str) -> Path:
    """Return the path of the pack file bundled with the package."""
    return Path(__file__).parent / "packs" / f"{pack_id}.json"


def pack_search_paths(pack_id: str, project: Path | None = None):
    """Return the candidate paths for ``pack_id``, in search order.

    The project's own ``patterns/`` folder wins, so a project can pin or
    override a pack; the bundled pack is the last resort.
    """
    paths = []
    if project is not None:
        paths.append(Path(project) / "patterns" / f"{pack_id}.json")
        paths.append(Path(project) / f"{pack_id}.json")
    here = Path(__file__).resolve().parents[2]  # repo root (src layout checkout)
    paths.append(here / "patterns" / f"{pack_id}.json")
    paths.append(_builtin_pack_path(pack_id))
    return paths


def load_pack(pack_id: str, project: Path | None = None) -> Pack:
    """Load a pack by id from the first search path that has it.

    Raises PackError when no candidate file exists.
    """
    # A pack id is a slug, never a path: "../../something" used to walk the
    # search paths out of the pack directories and load an arbitrary
    # "<name>.json" file as a pack.
    if not isinstance(pack_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", pack_id) \
            or ".." in pack_id:
        raise PackError(f"pack: invalid pack id: {pack_id!r}")
    for candidate in pack_search_paths(pack_id, project):
        if candidate.is_file():
            return load_pack_file(candidate)
    raise PackError(f"pack not found: {pack_id} (searched: "
                    + ", ".join(str(p) for p in pack_search_paths(pack_id, project)) + ")")


def load_pack_file(path: Path) -> Pack:
    """Load and validate a pack from an explicit JSON file path."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackError(f"cannot load pack {path}: {exc}") from exc
    return validate_pack(data, str(path))


def validate_pack(data: dict, source: str = "") -> Pack:
    """Validate parsed pack JSON and return it as a :class:`Pack`.

    Every pattern must carry an id, a description, and a dated source
    reference; anything missing raises PackError.
    """
    if not isinstance(data, dict):
        raise PackError("pack: top level is not an object")
    for key in ("id", "title", "version", "date", "language", "target", "patterns"):
        if key not in data:
            raise PackError(f"pack: missing '{key}'")
        if key != "patterns" and (not isinstance(data[key], str) or not data[key].strip()):
            raise PackError(f"pack: '{key}' must be a non-empty string")
    raw = data["patterns"]
    if not isinstance(raw, list) or not raw:
        raise PackError("pack: 'patterns' must be a non-empty list")
    seen, patterns = set(), []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PackError(f"pack patterns[{i}]: not an object")
        pid = item.get("id")
        if not pid or not isinstance(pid, str):
            raise PackError(f"pack patterns[{i}]: missing id")
        if pid in seen:
            raise PackError(f"pack: duplicate pattern id {pid}")
        seen.add(pid)
        for key in ("description", "reference", "reference_date", "reference_url", "matcher"):
            if not item.get(key):
                raise PackError(f"pattern {pid}: missing '{key}' (every pattern must be dated and referenced)")
            if key != "matcher" and not isinstance(item[key], str):
                raise PackError(f"pattern {pid}: '{key}' must be a string")
        matcher = item["matcher"]
        if not isinstance(matcher, dict) or matcher.get("kind") not in KINDS:
            raise PackError(f"pattern {pid}: matcher.kind must be one of {sorted(KINDS)}")
        # Per-kind matcher fields must be present and rightly typed. A
        # string "names" used to load fine and then match by SUBSTRING in
        # the scanner, silently producing wrong hits.
        kind = matcher["kind"]
        def _str_list(field_name):
            value = matcher.get(field_name)
            if not isinstance(value, list) or not value \
                    or not all(isinstance(v, str) and v for v in value):
                raise PackError(f"pattern {pid}: matcher.{field_name} must be a non-empty list of strings")
        if kind == "import_module":
            _str_list("modules")
        elif kind == "import_from":
            if not isinstance(matcher.get("module"), str) or not matcher["module"]:
                raise PackError(f"pattern {pid}: matcher.module must be a non-empty string")
            _str_list("names")
        else:  # attribute / attribute_or_name
            _str_list("names")
        if "attr_only" in matcher and not isinstance(matcher["attr_only"], bool):
            raise PackError(f"pattern {pid}: matcher.attr_only must be a boolean")
        patterns.append(Pattern(pid, item["description"], item["reference"],
                                item["reference_date"], item["reference_url"], matcher))
    return Pack(data["id"], data["title"], data["version"], data["date"],
                data["language"], data["target"], patterns, source)
