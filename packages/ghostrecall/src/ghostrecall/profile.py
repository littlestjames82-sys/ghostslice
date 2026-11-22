"""Profile: the `recall` section of the project's .ghostslice.json.

Unknown recall keys fail loudly (ValueError naming the key), matching
GhostSlice profile discipline. No second config file is introduced.
"""
from __future__ import annotations
import json
from pathlib import Path

ALLOWED_RECALL_KEYS = {
    "recent_n", "default_mode", "memory_budget_fraction",
    "pinned_rules", "include_git", "git_limit", "max_items",
}
DEFAULTS = {
    "recent_n": 5,
    "default_mode": "full",
    "memory_budget_fraction": 0.2,   # default suggestion, labelled a default in PLAN.md
    "pinned_rules": [],
    "include_git": True,
    "git_limit": 200,
    "max_items": 50,
}
MODES = ("full", "decision-only", "headings", "recent", "exclude")

def load_profile(project: Path) -> dict:
    """Return the recall profile for *project*: DEFAULTS overlaid with
    the ``recall`` section of its ``.ghostslice.json`` (if that file
    exists). Raises ValueError naming the problem for a malformed file,
    an unknown recall key, a bad default_mode, or a
    memory_budget_fraction outside (0, 1].
    """
    cfg = dict(DEFAULTS)
    pf = Path(project) / ".ghostslice.json"
    if not pf.exists():
        return cfg
    try:
        data = json.loads(pf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"invalid profile {pf}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"invalid profile {pf}: top level must be an object")
    recall = data.get("recall", {})
    if not isinstance(recall, dict):
        raise ValueError("invalid profile: 'recall' must be an object")
    for key in recall:
        if key not in ALLOWED_RECALL_KEYS:
            raise ValueError(f"invalid profile: unknown recall key {key!r} "
                             f"(allowed: {sorted(ALLOWED_RECALL_KEYS)})")
    cfg.update(recall)
    if cfg["default_mode"] not in MODES:
        raise ValueError(f"invalid profile: recall.default_mode {cfg['default_mode']!r} not in {MODES}")
    frac = cfg["memory_budget_fraction"]
    if isinstance(frac, bool) or not isinstance(frac, (int, float)) or not (0 < float(frac) <= 1):
        raise ValueError("invalid profile: recall.memory_budget_fraction must be in (0, 1]")
    # Type/range checks for the remaining keys, same fail-loudly rule:
    # a wrong-typed value used to surface much later as a confusing
    # int() crash in selection, or worse, silently misbehave (a
    # negative recent_n slicing off the wrong end, a bare-string
    # pinned_rules being iterated character by character).
    for key, minimum in (("recent_n", 1), ("max_items", 1), ("git_limit", 0)):
        v = cfg[key]
        if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
            raise ValueError(f"invalid profile: recall.{key} must be an integer >= {minimum}, got {v!r}")
    if not isinstance(cfg["include_git"], bool):
        raise ValueError(f"invalid profile: recall.include_git must be true or false, got {cfg['include_git']!r}")
    pins = cfg["pinned_rules"]
    if not isinstance(pins, list) or not all(isinstance(x, str) for x in pins):
        raise ValueError("invalid profile: recall.pinned_rules must be a list of strings")
    return cfg
