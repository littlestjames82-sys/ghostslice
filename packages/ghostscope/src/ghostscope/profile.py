"""Project profile: the `scope` section of .ghostslice.json.

GhostScope reads the same profile file GhostSlice uses. Only the
`scope` section is GhostScope's; unknown keys *inside* that section
fail loudly (a typo'd sensitive path must never silently do
nothing), while other sections belong to GhostSlice and are left
alone. Sensitive paths come from the profile only: GhostScope has
no built-in guesses about which paths are sensitive.
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

_SCOPE_KEYS = {"sensitive_paths", "entry_points"}


@dataclass
class ScopeProfile:
    sensitive_paths: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    path: str | None = None

    def is_sensitive(self, rel: str) -> bool:
        return any(_match(pat, rel) for pat in self.sensitive_paths)

    def is_entry_point_file(self, rel: str) -> bool:
        return rel in self.entry_points


def _match(pattern: str, rel: str) -> bool:
    pattern = pattern.replace("\\", "/")
    rel = rel.replace("\\", "/")
    if fnmatch.fnmatch(rel, pattern):
        return True
    if pattern.endswith("/**") and rel.startswith(pattern[:-3].rstrip("/") + "/"):
        return True
    if fnmatch.fnmatch(Path(rel).name, pattern):
        return True
    return False


def load_scope_profile(root: str | Path) -> ScopeProfile:
    """Load the ``scope`` section of ``<root>/.ghostslice.json``.

    A missing file means an empty profile. Unknown keys inside the
    ``scope`` section raise ValueError, so a typo cannot silently
    disable a sensitive path.
    """
    candidate = Path(root) / ".ghostslice.json"
    if not candidate.is_file():
        return ScopeProfile()
    try:
        raw = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{candidate}: cannot parse profile ({exc})") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{candidate}: profile top level is not an object")
    prof = ScopeProfile(path=str(candidate))
    # GhostSlice also allows a top-level entry_points list.
    top_entries = raw.get("entry_points")
    if isinstance(top_entries, list):
        prof.entry_points.extend(str(x) for x in top_entries)
    scope = raw.get("scope")
    if scope is None:
        return prof
    if not isinstance(scope, dict):
        raise ValueError(f"{candidate}: 'scope' section is not an object")
    unknown = sorted(set(scope) - _SCOPE_KEYS)
    if unknown:
        raise ValueError(
            f"{candidate}: unknown 'scope' keys {unknown}; "
            f"known keys are {sorted(_SCOPE_KEYS)}")
    for key in ("sensitive_paths", "entry_points"):
        val = scope.get(key, [])
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            raise ValueError(f"{candidate}: scope.{key} must be a list of strings")
        getattr(prof, key).extend(val)
    return prof
