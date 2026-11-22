"""Local pack manager: merge and remove with preview, an explicit
yes, a lockfile, and a kept backup.

Merge semantics are deterministic and previewable:
- list sections (ignore, entry_points, plugins) union, existing order
  first, pack additions appended;
- modes union per glob; a glob set to a *different* mode by both sides
  is a conflict;
- scalar keys (model, budget_tokens, preset, auto_shrink, redact) that
  differ between project and pack are conflicts;
- nested sections (lint, duplicates, ci) merge per key; a key set to
  a different value by both sides is a conflict.
Conflicts abort a merge unless --force is given (pack wins), and the
full unified diff of the profile is always shown (or returned) before
any write. A declined confirmation writes nothing.

Provenance lives in ``.ghostslice-packs.json`` next to the profile:
per merge, the pack id/version, the source folder, the date, the
profile sha256 before and after, and the backup path (a copy of the
pre-merge profile under ``.ghostslice-packs-backup/``). ``remove``
restores that backup only when the current profile still hashes to
the recorded after-merge hash; otherwise it reports exactly why it
cannot reverse cleanly instead of guessing.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

from .pack import GhostPacksError, lint_pack, load_pack, validate_profile_fragment

PROFILE_NAME = ".ghostslice.json"
LOCKFILE_NAME = ".ghostslice-packs.json"
BACKUP_DIR_NAME = ".ghostslice-packs-backup"
# Housekeeping ignores added by every merge: GhostPacks' own project
# artifacts (the lockfile and the backup folder) are bookkeeping, not
# project context, and must never inflate a GhostSlice scan or export
# of the project. They are part of the previewed diff, and removing
# the last pack deletes those artifacts, so the restored pre-merge
# profile needs no such entries.
ARTIFACT_IGNORES = (LOCKFILE_NAME, BACKUP_DIR_NAME + "/**")
LIST_KEYS = ("ignore", "entry_points", "plugins")
SCALAR_KEYS = ("model", "budget_tokens", "preset", "auto_shrink", "redact")
NESTED_KEYS = ("lint", "duplicates", "ci")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump_profile(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _load_json_file(path: Path, what: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GhostPacksError(f"{path}: cannot read {what}: {exc}") from exc
    except ValueError as exc:
        raise GhostPacksError(f"{path}: invalid JSON in {what}: {exc}") from exc
    if not isinstance(data, dict):
        raise GhostPacksError(f"{path}: {what} must be a JSON object")
    return data


def load_project_profile(project: Path) -> tuple:
    """(profile dict, raw bytes or None) for a project's profile.

    A project with no .ghostslice.json yet yields ({}, None)."""
    profile_path = Path(project) / PROFILE_NAME
    if not profile_path.is_file():
        return {}, None
    raw = profile_path.read_bytes()
    data = _load_json_file(profile_path, "project profile")
    # The user's own profile is validated non-strictly: GhostSlice
    # tolerates extra keys there, and merge preserves them. Strict
    # validation applies to the pack fragment being merged in.
    validate_profile_fragment(data, where=str(profile_path), strict=False)
    return data, raw


def load_lockfile(project: Path) -> dict:
    """The project's packs lockfile dict ({"packs": []} when none exists)."""
    path = Path(project) / LOCKFILE_NAME
    if not path.is_file():
        return {"packs": []}
    data = _load_json_file(path, "packs lockfile")
    if not isinstance(data.get("packs", []), list):
        raise GhostPacksError(f"{path}: lockfile 'packs' must be a list")
    data.setdefault("packs", [])
    if any(not isinstance(e, dict) for e in data["packs"]):
        raise GhostPacksError(
            f"{path}: every lockfile 'packs' entry must be an object")
    return data


def _ask(input_fn, prompt: str) -> str:
    """One confirmation prompt. A closed stdin (EOF) or Ctrl-C counts
    as a no, never as a traceback: a non-interactive caller that did
    not pass --yes has not consented to anything."""
    try:
        return input_fn(prompt)
    except (EOFError, KeyboardInterrupt):
        return ""


def _validated_backup_path(project: Path, entry: dict) -> Path | None:
    """The entry's backup as a Path, guaranteed inside the project's
    backup folder, or None when the entry records no backup.

    The lockfile is data on disk and can be edited or corrupted, so a
    recorded backup path is never trusted blindly: an absolute or
    ``..`` path (or a symlink) pointing outside ``BACKUP_DIR_NAME``
    would otherwise let `remove` copy an arbitrary file over the
    project profile and then delete that file. Refuse loudly."""
    rel = entry.get("backup")
    if rel is None:
        return None
    if not isinstance(rel, str) or not rel:
        raise GhostPacksError(
            f"lockfile entry for pack {entry.get('pack_id')!r} has an "
            f"invalid backup path {rel!r}; refusing to remove")
    candidate = Path(project) / rel
    backup_root = (Path(project) / BACKUP_DIR_NAME).resolve()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise GhostPacksError(
            f"recorded backup {rel!r} cannot be resolved: {exc}") from exc
    if backup_root not in resolved.parents:
        raise GhostPacksError(
            f"recorded backup {rel!r} for pack "
            f"{entry.get('pack_id')!r} is not inside "
            f"{BACKUP_DIR_NAME}/; refusing to restore or delete a path "
            "outside the project's backup folder")
    return candidate


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def plan_merge(existing: dict, fragment: dict) -> tuple:
    """Compute (merged, conflicts) without touching disk.

    Merge rules are the ones in this module's docstring: lists union,
    modes union per glob, and any key both sides set differently is a
    conflict (the existing value is kept in `merged` until --force).
    """
    merged: dict = {}
    conflicts: list = []
    for key in LIST_KEYS:
        out = list(existing.get(key) or [])
        for item in fragment.get(key) or []:
            if item not in out:
                out.append(item)
        if key == "ignore":
            for item in ARTIFACT_IGNORES:
                if item not in out:
                    out.append(item)
        if out:
            merged[key] = out
    modes = dict(existing.get("modes") or {})
    for pat, mode in (fragment.get("modes") or {}).items():
        if pat in modes and modes[pat] != mode:
            conflicts.append(
                f"modes[{pat!r}]: project has {modes[pat]!r}, pack has {mode!r}")
        else:
            modes[pat] = mode
    if modes:
        merged["modes"] = modes
    for key in SCALAR_KEYS:
        cur, new = existing.get(key), fragment.get(key)
        if new is None:
            if cur is not None:
                merged[key] = cur
        elif cur is None or cur == new:
            merged[key] = new
        else:
            conflicts.append(f"{key}: project has {cur!r}, pack has {new!r}")
            merged[key] = cur
    for key in NESTED_KEYS:
        cur = dict(existing.get(key) or {})
        out = dict(cur)
        for sub, val in (fragment.get(key) or {}).items():
            if sub in cur and cur[sub] != val:
                conflicts.append(
                    f"{key}[{sub!r}]: project has {cur[sub]!r}, pack has {val!r}")
            else:
                out[sub] = val
        if out:
            merged[key] = out
    # Preserve any other validated keys the existing profile carries.
    for key, val in existing.items():
        if key not in merged and key not in (
                LIST_KEYS + ("modes",) + SCALAR_KEYS + NESTED_KEYS):
            merged[key] = val
    return merged, conflicts


def apply_force(merged: dict, existing: dict, fragment: dict, conflicts: list) -> dict:
    """Resolve conflicts in the pack's favour (only under --force)."""
    if not conflicts:
        return merged
    out = json.loads(_dump_profile(merged))
    for pat, mode in (fragment.get("modes") or {}).items():
        if pat in (existing.get("modes") or {}):
            out.setdefault("modes", {})[pat] = mode
    for key in SCALAR_KEYS:
        if fragment.get(key) is not None:
            out[key] = fragment[key]
    for key in NESTED_KEYS:
        for sub, val in (fragment.get(key) or {}).items():
            out.setdefault(key, {})[sub] = val
    return out


def profile_diff(before: dict, after: dict, existed: bool) -> str:
    """Unified diff of the profile JSON, as shown in the merge preview."""
    before_lines = _dump_profile(before).splitlines(keepends=True) if existed else []
    after_lines = _dump_profile(after).splitlines(keepends=True)
    return "".join(difflib.unified_diff(
        before_lines, after_lines,
        fromfile=PROFILE_NAME + " (before)", tofile=PROFILE_NAME + " (after)"))


def merge_pack(project, pack_dir, assume_yes=False, force=False,
               input_fn=input, out=print) -> dict:
    """Merge a pack into a project's .ghostslice.json.

    Returns a result dict: {status: merged|declined|unchanged, pack,
    diff, conflicts, profile_hash_after, ...}. Writes nothing when the
    confirmation is declined or the merge changes nothing."""
    project = Path(project)
    if not project.is_dir():
        raise GhostPacksError(f"{project}: not a project folder")
    errors, _warnings = lint_pack(pack_dir)
    if errors:
        raise GhostPacksError("pack fails lint: " + "; ".join(errors))
    pack = load_pack(pack_dir)
    if pack.profile.get("plugins"):
        out(f"note: pack {pack.id} references plugins "
            f"{pack.profile['plugins']}; GhostPacks does not install or run "
            "them. They merge as profile entries only, and GhostSlice loads "
            "a plugin only when the project names it.")
    existing, raw = load_project_profile(project)
    lock = load_lockfile(project)
    if any(e.get("pack_id") == pack.id and e.get("version") == pack.version
           for e in lock["packs"]):
        out(f"pack {pack.id} {pack.version} is already recorded in "
            f"{LOCKFILE_NAME} for this project; nothing to merge.")
        return {"status": "unchanged", "pack": pack.id,
                "version": pack.version, "diff": "", "conflicts": []}
    merged, conflicts = plan_merge(existing, pack.profile)
    if conflicts and force:
        merged = apply_force(merged, existing, pack.profile, conflicts)
    diff = profile_diff(existing, merged, existed=raw is not None)
    out(f"Merge preview: pack {pack.summary_line()} into {project}")
    out(diff if diff else "(no profile changes)")
    if conflicts:
        out("Conflicts (pack and project set the same key differently):")
        for c in conflicts:
            out(f"  - {c}")
        if not force:
            out("Merge aborted on conflicts. Re-run with --force to let "
                "the pack win on the conflicting keys.")
            return {"status": "conflict", "pack": pack.id,
                    "version": pack.version, "diff": diff,
                    "conflicts": conflicts}
    if not diff:
        out("Merged profile is identical to the current one; nothing written.")
        return {"status": "unchanged", "pack": pack.id,
                "version": pack.version, "diff": "", "conflicts": conflicts}
    if not assume_yes:
        answer = _ask(input_fn, f"Merge pack {pack.id} {pack.version} into "
                                f"{project}/{PROFILE_NAME}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            out("Declined; nothing written.")
            return {"status": "declined", "pack": pack.id,
                    "version": pack.version, "diff": diff,
                    "conflicts": conflicts}
    backup_rel = None
    if raw is not None:
        stamp = date.today().isoformat()
        backup_dir = project / BACKUP_DIR_NAME
        backup_dir.mkdir(exist_ok=True)
        backup_name = f"{stamp}-{pack.id}-{pack.version}.ghostslice.json.bak"
        backup_path = backup_dir / backup_name
        n = 2
        while backup_path.exists():
            backup_path = backup_dir / f"{backup_name}.{n}"
            n += 1
        backup_path.write_bytes(raw)
        backup_rel = backup_path.relative_to(project).as_posix()
    merged_text = _dump_profile(merged)
    (project / PROFILE_NAME).write_text(merged_text, encoding="utf-8")
    entry = {
        "pack_id": pack.id,
        "version": pack.version,
        "kind": "context",
        "source": str(pack.path),
        "date_merged": date.today().isoformat(),
        "profile_hash_before": _sha256_bytes(raw) if raw is not None else None,
        "profile_hash_after": _sha256_bytes(merged_text.encode("utf-8")),
        "backup": backup_rel,
        "score_status": pack.score_status,
    }
    lock["packs"].append(entry)
    _write_json(project / LOCKFILE_NAME, lock)
    out(f"Merged {pack.id} {pack.version}; profile hash "
        f"{entry['profile_hash_after'][:12]}... recorded in {LOCKFILE_NAME}"
        + (f"; backup at {backup_rel}" if backup_rel else
           "; no prior profile existed"))
    return {"status": "merged", "pack": pack.id, "version": pack.version,
            "diff": diff, "conflicts": conflicts, **entry}


def remove_pack(project, pack_id, assume_yes=False, force=False,
                input_fn=input, out=print) -> dict:
    """Reverse the recorded merge of one pack in a project.

    Clean reversal requires: the pack's lockfile entry is the latest
    merge (or --force, which also drops later entries) and the current
    profile still hashes to the entry's profile_hash_after (or
    --force). Anything else is reported exactly, with nothing written."""
    project = Path(project)
    lock = load_lockfile(project)
    entries = lock["packs"]
    idx = None
    for i in range(len(entries) - 1, -1, -1):
        if entries[i].get("pack_id") == pack_id:
            idx = i
            break
    if idx is None:
        raise GhostPacksError(
            f"pack {pack_id!r} is not recorded in {project}/{LOCKFILE_NAME}; "
            "nothing to remove")
    entry = entries[idx]
    later = entries[idx + 1:]
    if later and not force:
        raise GhostPacksError(
            f"cannot cleanly remove {pack_id}: later packs were merged after "
            f"it ({', '.join(e.get('pack_id', '?') for e in later)}). Remove "
            "those first, or re-run with --force to restore the profile to "
            "the state before this pack and drop the later lockfile entries.")
    # Validate every backup this removal could restore or delete
    # before anything is prompted, written, or unlinked.
    removed_backups = [_validated_backup_path(project, e)
                       for e in entries[idx:]]
    backup_path = removed_backups[0]
    profile_path = project / PROFILE_NAME
    raw = profile_path.read_bytes() if profile_path.is_file() else None
    current_hash = _sha256_bytes(raw) if raw is not None else None
    if current_hash != entry.get("profile_hash_after") and not force:
        raise GhostPacksError(
            f"cannot cleanly remove {pack_id}: the project profile has been "
            f"edited since the merge (current hash "
            f"{(current_hash or 'none')[:12]}... != recorded "
            f"{(entry.get('profile_hash_after') or 'none')[:12]}...). "
            "Restore by hand from the recorded backup "
            f"({entry.get('backup') or 'no backup; profile did not exist before'})"
            ", or re-run with --force to restore that backup anyway.")
    backup_rel = entry.get("backup")
    if backup_path is not None and not backup_path.is_file():
        raise GhostPacksError(
            f"recorded backup {backup_rel} is missing; cannot reverse the "
            "merge without it")
    if not assume_yes:
        answer = _ask(input_fn, f"Remove pack {pack_id} from {project} and restore "
                                "the pre-merge profile? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            out("Declined; nothing written.")
            return {"status": "declined", "pack": pack_id}
    if backup_path is not None:
        shutil.copyfile(backup_path, profile_path)
        restored = "restored backup " + backup_rel
    else:
        if profile_path.is_file():
            profile_path.unlink()
        restored = "deleted the profile the merge created"
    removed_entries = entries[idx:]
    del entries[idx:]
    # The merge's bookkeeping is consumed by the reversal: delete the
    # backups of every entry being removed, and when no packs remain
    # recorded, delete the lockfile itself, so a fully-removed project
    # carries no GhostPacks artifacts for a scanner to pick up.
    for gone_path in removed_backups:
        if gone_path is not None and gone_path.is_file():
            gone_path.unlink()
    backup_dir = project / BACKUP_DIR_NAME
    if backup_dir.is_dir() and not any(backup_dir.iterdir()):
        backup_dir.rmdir()
    if entries:
        _write_json(project / LOCKFILE_NAME, lock)
    elif (project / LOCKFILE_NAME).is_file():
        (project / LOCKFILE_NAME).unlink()
    out(f"Removed {pack_id}; {restored}.")
    return {"status": "removed", "pack": pack_id, "restored": restored,
            "dropped_later": [e.get("pack_id") for e in later]}
