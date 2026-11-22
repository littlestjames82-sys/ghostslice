"""GhostSlice profile handling for GhostReplay.

Two jobs:

1. The `replay` section of a project's .ghostslice.json tunes
   GhostReplay: {"replay": {"min_sessions": 3,
   "min_unreferenced_sessions": 2, "friction_threshold": 2}}.
   Unknown keys, wrong types, and non-positive values are a loud
   ValueError, mirroring GhostSlice's profile discipline (a typo
   must never silently leave a default in place). Absent section
   means the documented defaults.

2. Applying and restoring profile proposals (used by the CLI,
   which owns the explicit-terminal-yes prompt; nothing in this
   module ever prompts or applies on its own):
   - apply_changes(project, changes) validates every change,
     validates the RESULTING profile (own validator, plus
     GhostSlice's own loader when importable), backs the old
     profile up to .ghostslice.json.bak (or records that none
     existed), then writes.
   - restore_profile(project) puts the backup back, or removes a
     profile GhostReplay created.
"""
from __future__ import annotations

import json
from pathlib import Path

PROFILE_NAME = ".ghostslice.json"
BACKUP_NAME = ".ghostslice.json.bak"
CREATED_MARKER = ".ghostslice.json.ghostreplay-created"

MODES = ("full", "signatures", "interfaces", "strip-tests",
         "exclude", "headings", "structure", "symbols")

REPLAY_DEFAULTS = {
    "min_sessions": 3,
    "min_unreferenced_sessions": 2,
    "friction_threshold": 2,
    "min_reread_turns": 2,
}


def load_replay_config(project: str | Path) -> dict:
    """Return the effective replay thresholds for ``project``.

    Starts from :data:`REPLAY_DEFAULTS` and overlays the profile's
    ``replay`` section when present. Unknown keys or invalid values
    raise ``ValueError`` loudly rather than being ignored.
    """
    cfg = dict(REPLAY_DEFAULTS)
    path = Path(project) / PROFILE_NAME
    if not path.is_file():
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: cannot load profile: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: profile must be a JSON object")
    section = data.get("replay")
    if section is None:
        return cfg
    if not isinstance(section, dict):
        raise ValueError(f"{path}: 'replay' must be an object")
    for key, val in section.items():
        if key not in REPLAY_DEFAULTS:
            raise ValueError(
                f"{path}: unknown replay option {key!r} "
                f"(allowed: {', '.join(sorted(REPLAY_DEFAULTS))})")
        if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
            raise ValueError(
                f"{path}: replay option {key!r} must be a positive "
                f"whole number, got {val!r}")
        cfg[key] = val
    return cfg


def read_profile_data(project: str | Path) -> tuple[dict, Path]:
    """Read ``.ghostslice.json``; return ``(data, path)`` (``{}`` if absent)."""
    path = Path(project) / PROFILE_NAME
    if not path.is_file():
        return {}, path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: cannot load profile: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: profile must be a JSON object")
    return data, path


def validate_profile_data(data: dict, source: str = "profile") -> None:
    """Structural validation of the parts GhostReplay touches,
    mirroring GhostSlice's loader checks for those fields."""
    if not isinstance(data, dict):
        raise ValueError(f"{source}: profile must be a JSON object")
    modes = data.get("modes") or {}
    if not isinstance(modes, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in modes.items()):
        raise ValueError(
            f"{source}: 'modes' must be an object mapping glob "
            "patterns to mode names")
    for pat, mode in modes.items():
        if mode not in MODES:
            raise ValueError(
                f"{source}: unknown mode for {pat!r}: {mode!r} "
                f"(choose from {', '.join(MODES)})")
    for key in ("ignore", "entry_points", "plugins"):
        val = data.get(key) or []
        if not isinstance(val, list) or any(
                not isinstance(v, str) for v in val):
            raise ValueError(f"{source}: {key!r} must be a list of strings")
    budget = data.get("budget_tokens")
    if budget is not None and (isinstance(budget, bool)
                               or not isinstance(budget, (int, float))):
        raise ValueError(f"{source}: 'budget_tokens' must be a number")


def _ghostslice_validate(project: Path) -> None:
    """Run GhostSlice's own loader when importable (installed, or a
    sibling checkout at ../ghostslice/src). A ValueError from it is
    a hard failure; its absence is not (own validator already ran).
    """
    try:
        from ghostslice.profile import load_profile_file
        load_profile_file(project / PROFILE_NAME)
        return
    except ImportError:
        pass
    except ValueError:
        raise
    import sys
    sibling = Path(__file__).resolve().parents[3] / "ghostslice" / "src"
    if (sibling / "ghostslice" / "profile.py").is_file():
        sys.path.insert(0, str(sibling))
        try:
            from ghostslice.profile import load_profile_file
            load_profile_file(project / PROFILE_NAME)
        except ImportError:
            pass
        finally:
            sys.path.remove(str(sibling))


def apply_changes(project: str | Path, changes: list[dict]) -> dict:
    """Validate + apply proposal changes to .ghostslice.json.
    The CLI must have already obtained the explicit terminal yes.
    Returns {"backup": str|None, "created": bool, "applied": n}."""
    project = Path(project)
    data, path = read_profile_data(project)
    profile_changes = [c for c in changes
                       if c.get("kind") in ("mode", "entry_point")]
    if not profile_changes:
        raise ValueError("proposal has no profile changes to apply")
    modes = dict(data.get("modes") or {})
    entry_points = list(data.get("entry_points") or [])
    for change in profile_changes:
        target = change.get("target")
        proposed = change.get("proposed")
        if not isinstance(target, str) or not target:
            raise ValueError(f"change has no target: {change!r}")
        if change["kind"] == "mode":
            if proposed not in MODES:
                raise ValueError(
                    f"change for {target!r}: unknown mode {proposed!r}")
            modes[target] = proposed
        else:  # entry_point
            if proposed != "pin":
                raise ValueError(
                    f"entry_point change for {target!r}: proposed "
                    f"must be 'pin', got {proposed!r}")
            if target not in entry_points:
                entry_points.append(target)
    new_data = dict(data)
    new_data["modes"] = modes
    if entry_points:
        new_data["entry_points"] = entry_points
    validate_profile_data(new_data, str(path))

    existed = path.is_file()
    backup = None
    if existed:
        backup_path = project / BACKUP_NAME
        backup_path.write_bytes(path.read_bytes())
        backup = str(backup_path)
    else:
        (project / CREATED_MARKER).write_text(
            "profile created by ghostreplay apply; restore removes it\n",
            encoding="utf-8")
    path.write_text(json.dumps(new_data, indent=2) + "\n", encoding="utf-8")
    try:
        _ghostslice_validate(project)
    except ValueError as exc:
        # Roll back: a profile GhostSlice rejects must never stand.
        if existed:
            path.write_bytes((project / BACKUP_NAME).read_bytes())
        else:
            path.unlink(missing_ok=True)
            (project / CREATED_MARKER).unlink(missing_ok=True)
        raise ValueError(
            f"resulting profile failed GhostSlice validation, "
            f"rolled back: {exc}") from exc
    return {"backup": backup, "created": not existed,
            "applied": len(profile_changes)}


def restore_profile(project: str | Path) -> str:
    """Undo an apply; return a human-readable description of what happened."""
    project = Path(project)
    path = project / PROFILE_NAME
    backup_path = project / BACKUP_NAME
    marker = project / CREATED_MARKER
    if backup_path.is_file():
        path.write_bytes(backup_path.read_bytes())
        backup_path.unlink()
        marker.unlink(missing_ok=True)
        return f"restored {path} from {backup_path}"
    if marker.is_file():
        path.unlink(missing_ok=True)
        marker.unlink()
        return f"removed {path} (created by ghostreplay apply)"
    raise ValueError(
        f"no GhostReplay backup ({BACKUP_NAME}) or created-marker "
        f"in {project}; nothing to restore")
