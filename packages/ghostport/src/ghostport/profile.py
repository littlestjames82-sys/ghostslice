"""Read the `port` section of a project's .ghostslice.json, if present.

Supported keys (all optional): pack, budget_tokens (per-unit), merge
(list of lists of unit ids/files to combine), pin_first (unit ids that a
human orders first, breaking ties only - never dependency order),
order (explicit unit order override applied as a tie-breaker),
test_command (recorded in UNIT.md, never run by GhostPort).
Unknown keys fail loudly.
"""
from __future__ import annotations

import json
from pathlib import Path

KNOWN = {"pack", "budget_tokens", "merge", "pin_first", "order", "test_command", "pattern_overrides"}


class ProfileError(ValueError):
    """Raised when a project's .ghostslice.json port section is invalid."""


def load_port_profile(project: Path) -> dict:
    """Return the project's port profile, with defaults filled in.

    Reads the ``port`` section of ``<project>/.ghostslice.json``. A
    missing file or missing section returns all defaults; an unparseable
    file, a non-object section, or an unknown key raises ProfileError.
    """
    path = Path(project) / ".ghostslice.json"
    out = {"pack": None, "budget_tokens": None, "merge": [], "pin_first": [],
           "order": [], "test_command": None, "pattern_overrides": {}}
    if not path.is_file():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProfileError(f".ghostslice.json: cannot parse ({exc})") from exc
    section = data.get("port") if isinstance(data, dict) else None
    if section is None:
        return out
    if not isinstance(section, dict):
        raise ProfileError(".ghostslice.json: 'port' section is not an object")
    unknown = sorted(set(section) - KNOWN)
    if unknown:
        raise ProfileError(f".ghostslice.json port section: unknown keys {unknown}")
    for key in out:
        if key in section:
            out[key] = section[key]
    # Type-check known keys: a wrongly typed value used to be accepted here
    # and then crash opaquely (or silently misbehave) in unit formation -
    # e.g. "merge": "unit-a" iterated character by character.
    def _bad(key, want):
        raise ProfileError(f".ghostslice.json port section: '{key}' must be {want}")
    if out["pack"] is not None and not isinstance(out["pack"], str):
        _bad("pack", "a string or null")
    if out["budget_tokens"] is not None and (
            not isinstance(out["budget_tokens"], int)
            or isinstance(out["budget_tokens"], bool) or out["budget_tokens"] <= 0):
        _bad("budget_tokens", "a positive integer or null")
    if out["test_command"] is not None and not isinstance(out["test_command"], str):
        _bad("test_command", "a string or null")
    if not isinstance(out["merge"], list) or not all(
            isinstance(g, list) and all(isinstance(m, str) for m in g) for g in out["merge"]):
        _bad("merge", "a list of lists of strings")
    for key in ("pin_first", "order"):
        if not isinstance(out[key], list) or not all(isinstance(v, str) for v in out[key]):
            _bad(key, "a list of strings")
    if not isinstance(out["pattern_overrides"], dict):
        _bad("pattern_overrides", "an object")
    return out
