"""Atlas profile handling.

Reads the project's ``.ghostslice.json`` (the GhostSlice profile) for
project-level settings and validates its optional ``atlas`` section.
Unknown keys in the ``atlas`` section fail loudly (a ValueError naming
the key), mirroring GhostSlice's lint/duplicates section discipline:
a typo must never silently drop a user's title or hidden path.
"""
from __future__ import annotations

import json
from pathlib import Path

PROFILE_NAME = ".ghostslice.json"

ATLAS_KEYS = ("title", "audience_notes", "hidden_paths")

DEFAULTS = {"title": None, "audience_notes": [], "hidden_paths": []}


def load_atlas_config(root: str | Path) -> dict:
    """Return the normalised atlas config for a project root.

    Missing profile / missing section -> defaults. Malformed JSON,
    a non-object section, wrong value types, and unknown atlas keys
    all raise ValueError with the file and key named.
    """
    root = Path(root)
    candidate = root / PROFILE_NAME
    cfg = {"title": None, "audience_notes": [], "hidden_paths": []}
    if not candidate.is_file():
        return cfg
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{candidate}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{candidate}: profile must be a JSON object")
    raw = data.get("atlas")
    if raw is None:
        return cfg
    if not isinstance(raw, dict):
        raise ValueError(
            f"{candidate}: 'atlas' must be an object with keys from: "
            f"{', '.join(ATLAS_KEYS)}")
    for key, val in raw.items():
        if key not in ATLAS_KEYS:
            raise ValueError(
                f"{candidate}: unknown atlas option {key!r} "
                f"(allowed: {', '.join(ATLAS_KEYS)})")
        if key == "title":
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"{candidate}: atlas 'title' must be a non-empty string")
            # One line only: a title/note is rendered into the brief
            # heading/body, so embedded newlines could inject fake
            # brief lines (e.g. a forged token total).
            cfg["title"] = " ".join(val.split())
        else:
            if not isinstance(val, list) or any(not isinstance(v, str) for v in val):
                raise ValueError(
                    f"{candidate}: atlas {key!r} must be a list of strings")
            if key == "audience_notes":
                cfg[key] = [" ".join(v.split()) for v in val]
            else:
                cfg[key] = list(val)
    return cfg


def is_hidden(rel: str, hidden_paths) -> bool:
    """A path is hidden when it matches a hidden_paths entry exactly,
    as a directory prefix, or as a simple ``*`` glob (fnmatch)."""
    import fnmatch

    for pat in hidden_paths or []:
        pat = pat.strip("/")
        if not pat:
            continue
        if rel == pat or rel.startswith(pat + "/"):
            return True
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat + "/*"):
            return True
    return False
