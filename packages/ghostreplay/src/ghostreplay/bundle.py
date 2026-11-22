"""GhostSlice bundle-manifest join.

The manifest is the ground truth for what was SENT (PLAN.md).
GhostReplay reads a GhostSlice bundle's manifest.json:

  {"tool": "ghostslice", "version": ..., "root": ...,
   "total_original_tokens": n, "total_sliced_tokens": n,
   "files": [{"path", "mode", "language", "original_tokens",
              "sliced_tokens", "sha256",
              "symbols_included": [...] (symbols mode only)}, ...]}

Join rules:
- An explicit bundle dir / manifest path always wins.
- Else <project>/.claude_context/manifest.json when it exists.
- Else no bundle: analysis still runs (re-reads / repetition from
  the transcript alone), and every bundle-dependent section is
  reported as unavailable, never guessed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class BundleError(ValueError):
    """The bundle path is missing, unreadable, or not a manifest."""


def _token_count(value, field: str, mpath) -> int:
    """Coerce a manifest token count, loudly. bool is an int
    subclass (True must not become 1 token), a non-numeric string
    must surface as BundleError naming the field rather than a
    bare ValueError from int(), and a fractional float is not a
    token count."""
    if value is None:
        return 0
    if isinstance(value, bool):
        raise BundleError(f"{mpath}: {field} must be a token count, "
                          f"got {value!r}")
    if isinstance(value, float):
        if not value.is_integer():
            raise BundleError(f"{mpath}: {field} must be a whole "
                              f"token count, got {value!r}")
        value = int(value)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BundleError(f"{mpath}: {field} must be a token count, "
                          f"got {value!r}") from exc


def _symbols(value, field: str, mpath) -> list:
    """symbols_included must be a list of strings. A bare string
    used to be list()-split into single characters, inventing
    one-letter symbols that then 'matched' friction text."""
    if value is None:
        return []
    if not isinstance(value, list) or any(
            not isinstance(v, str) for v in value):
        raise BundleError(f"{mpath}: {field} must be a list of "
                          f"strings, got {value!r}")
    return list(value)


def load_manifest(bundle: str | Path) -> dict:
    """Load and normalise a GhostSlice ``manifest.json``.

    ``bundle`` may be a bundle directory or a direct path to
    ``manifest.json``. Returns a dict with per-file entries plus a
    ``by_path`` index. Raises :class:`BundleError` on any problem:
    callers should surface it, never fall back to guessing.
    """
    bundle = Path(bundle)
    mpath = bundle / "manifest.json" if bundle.is_dir() else bundle
    try:
        raw = mpath.read_text(encoding="utf-8")
    except OSError as exc:
        raise BundleError(f"{mpath}: cannot read manifest: {exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise BundleError(f"{mpath}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise BundleError(
            f"{mpath}: not a GhostSlice manifest "
            "(needs an object with a 'files' list)")
    files = []
    for i, entry in enumerate(data["files"]):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise BundleError(f"{mpath}: files[{i}] has no string 'path'")
        files.append({
            "path": entry["path"],
            "mode": entry.get("mode") or "full",
            "language": entry.get("language"),
            "original_tokens": _token_count(
                entry.get("original_tokens"),
                f"files[{i}].original_tokens", mpath),
            "sliced_tokens": _token_count(
                entry.get("sliced_tokens"),
                f"files[{i}].sliced_tokens", mpath),
            "sha256": entry.get("sha256") or "",
            "symbols_included": _symbols(
                entry.get("symbols_included"),
                f"files[{i}].symbols_included", mpath),
        })
    return {
        "manifest_path": str(mpath),
        "manifest_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "root": data.get("root"),
        "tool_version": data.get("version"),
        "total_original_tokens": _token_count(
            data.get("total_original_tokens"), "total_original_tokens",
            mpath),
        "total_sliced_tokens": _token_count(
            data.get("total_sliced_tokens"), "total_sliced_tokens",
            mpath),
        "files": files,
        "by_path": {f["path"]: f for f in files},
    }


def find_bundle(project: str | Path,
                explicit: str | Path | None = None) -> dict | None:
    """Resolve which bundle to join against, or ``None``.

    An explicit bundle always wins; otherwise
    ``<project>/.claude_context/manifest.json`` is used when it
    exists. ``None`` is a valid result: analysis still runs, with
    bundle-dependent sections reported as unavailable.
    """
    if explicit is not None:
        return load_manifest(explicit)
    candidate = Path(project) / ".claude_context" / "manifest.json"
    if candidate.is_file():
        return load_manifest(candidate)
    return None


def match_path(candidate: str, bundle_files: list[str],
               project: str | Path | None = None) -> str | None:
    """Map an absolute or relative transcript path to a bundle
    relative path. Exact relative match wins, then project-relative
    resolution, then a unique suffix match (an absolute path ending
    in exactly one bundle path). Ambiguity returns None."""
    cand = candidate.replace("\\", "/")
    if cand in bundle_files:
        return cand
    if project is not None:
        try:
            rel = str(Path(candidate).resolve().relative_to(
                Path(project).resolve())).replace("\\", "/")
            if rel in bundle_files:
                return rel
        except (ValueError, OSError):
            pass
    suffix = [p for p in bundle_files if cand.endswith("/" + p)]
    if len(suffix) == 1:
        return suffix[0]
    return None
