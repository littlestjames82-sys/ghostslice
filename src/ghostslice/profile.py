"""Project profile: `.ghostslice.json` in the scanned project root.

Example:
{
  "ignore": ["vendor/**", "*.snap"],
  "modes": {"src/**": "signatures", "docs/**": "full", "**/*.py": "signatures"},
  "model": "claude-sonnet",
  "budget_tokens": 50000,
  "entry_points": ["src/main.py", "src/cli.py"],
  "preset": "claude-code"
}

All fields are optional. The CLI loads the profile automatically when a
command targets a project directory that contains the file.
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

PROFILE_NAME = ".ghostslice.json"
PRESETS = ("claude-code", "aider", "generic")


def match_glob(pattern: str, rel: str) -> bool:
    """Match a glob against a posix relative path.

    Supports fnmatch globs on the full path and on the basename (when the
    pattern has no slash), `dir/**` as "everything under dir", and a
    leading `**/` as "at any depth".
    """
    pat = pattern.replace("\\", "/").strip()
    rel = rel.replace("\\", "/")
    if not pat:
        return False
    if pat.endswith("/**"):
        prefix = pat[:-3].rstrip("/")
        return rel == prefix or rel.startswith(prefix + "/")
    if fnmatch.fnmatch(rel, pat):
        return True
    if pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:]):
        return True
    if "/" not in pat and fnmatch.fnmatch(Path(rel).name, pat):
        return True
    # "src/*.py" should also match deeper via fnmatch's * crossing / on posix
    return False


@dataclass
class Profile:
    ignore: list[str] = field(default_factory=list)
    modes: dict[str, str] = field(default_factory=dict)
    model: str | None = None
    budget_tokens: int | None = None
    entry_points: list[str] = field(default_factory=list)
    preset: str | None = None
    path: str | None = None  # where it was loaded from, if any

    def is_ignored(self, rel: str) -> bool:
        return any(match_glob(p, rel) for p in self.ignore)

    def mode_for(self, rel: str) -> str | None:
        """Last matching glob wins, mirroring .gitignore precedence."""
        mode = None
        for pat, m in self.modes.items():
            if match_glob(pat, rel):
                mode = m
        return mode

    def to_dict(self) -> dict:
        return {
            "ignore": self.ignore, "modes": self.modes, "model": self.model,
            "budget_tokens": self.budget_tokens,
            "entry_points": self.entry_points, "preset": self.preset,
            "path": self.path,
        }


def load_profile(root: str | Path) -> Profile:
    root = Path(root)
    candidate = root / PROFILE_NAME if root.is_dir() else root.parent / PROFILE_NAME
    if not candidate.is_file():
        return Profile()
    data = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{candidate}: profile must be a JSON object")
    preset = data.get("preset")
    if preset is not None and preset not in PRESETS:
        raise ValueError(f"{candidate}: unknown preset {preset!r} (choose from {', '.join(PRESETS)})")
    budget = data.get("budget_tokens")
    return Profile(
        ignore=list(data.get("ignore") or []),
        modes=dict(data.get("modes") or {}),
        model=data.get("model"),
        budget_tokens=int(budget) if budget is not None else None,
        entry_points=list(data.get("entry_points") or []),
        preset=preset,
        path=str(candidate),
    )
