"""Diff two GhostSlice bundles by their manifests.

`ghostslice diff <bundleA> <bundleB>` answers "what changed between
these two exports": files added or removed, per-file mode changes and
original/sliced token deltas, and totals. Validation comes first: if
either bundle fails `ghostslice check` semantics, the diff refuses
and reports which bundle is broken (CLI exit 1). Two valid bundles
always diff successfully (CLI exit 0), however much they differ.
"""
from __future__ import annotations

import json
from pathlib import Path

from .exporter import validate_bundle


def load_manifest(bundle: str | Path) -> dict:
    """Load a bundle manifest, raising ValueError (never a raw
    OSError/JSON error) with a clear message — the CLI turns
    ValueError into exit 1 (v0.21)."""
    path = Path(bundle) / "manifest.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{path}: cannot read manifest ({exc})") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: manifest is not valid UTF-8 ({exc})") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"{path}: invalid manifest JSON ({exc})") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise ValueError(f"{path}: manifest is not an object with a 'files' list")
    return data


def diff_bundles(bundle_a: str | Path, bundle_b: str | Path) -> dict:
    """Return the diff dict (see module docstring). Raises ValueError
    with a `which` bundle label when either bundle fails validation."""
    for label, bundle in (("A", bundle_a), ("B", bundle_b)):
        try:
            check = validate_bundle(bundle)
        except Exception as exc:
            raise ValueError(f"bundle {label} ({bundle}): cannot validate: {exc}") from exc
        if not check["ok"]:
            raise ValueError(
                f"bundle {label} ({bundle}) failed validation: " + "; ".join(check["errors"]))
    ma = load_manifest(bundle_a)
    mb = load_manifest(bundle_b)
    # v0.21: normalize entries before indexing — validation has
    # already judged these bundles, but fields it does not check
    # (original_tokens, mode on every entry) must not KeyError here.
    def _entries(manifest: dict) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for f in manifest["files"]:
            if not isinstance(f, dict) or not isinstance(f.get("path"), str):
                continue
            out[f["path"]] = {
                "path": f["path"],
                "mode": f.get("mode") if isinstance(f.get("mode"), str) else "",
                "original_tokens": f.get("original_tokens")
                    if isinstance(f.get("original_tokens"), int) else 0,
                "sliced_tokens": f.get("sliced_tokens")
                    if isinstance(f.get("sliced_tokens"), int) else 0,
            }
        return out

    def _total(manifest: dict, key: str) -> int:
        val = manifest.get(key)
        return val if isinstance(val, int) and not isinstance(val, bool) else 0

    fa = _entries(ma)
    fb = _entries(mb)
    added = sorted(set(fb) - set(fa))
    removed = sorted(set(fa) - set(fb))
    changed: list[dict] = []
    unchanged = 0
    for path in sorted(set(fa) & set(fb)):
        a, b = fa[path], fb[path]
        if a["mode"] == b["mode"] and a["original_tokens"] == b["original_tokens"] \
                and a["sliced_tokens"] == b["sliced_tokens"]:
            unchanged += 1
            continue
        changed.append({
            "path": path,
            "mode_from": a["mode"],
            "mode_to": b["mode"],
            "original_from": a["original_tokens"],
            "original_to": b["original_tokens"],
            "original_delta": b["original_tokens"] - a["original_tokens"],
            "sliced_from": a["sliced_tokens"],
            "sliced_to": b["sliced_tokens"],
            "sliced_delta": b["sliced_tokens"] - a["sliced_tokens"],
        })
    return {
        "bundle_a": str(bundle_a),
        "bundle_b": str(bundle_b),
        "added": [{"path": p, "mode": fb[p]["mode"],
                   "original_tokens": fb[p]["original_tokens"],
                   "sliced_tokens": fb[p]["sliced_tokens"]} for p in added],
        "removed": [{"path": p, "mode": fa[p]["mode"],
                     "original_tokens": fa[p]["original_tokens"],
                     "sliced_tokens": fa[p]["sliced_tokens"]} for p in removed],
        "changed": changed,
        "unchanged_count": unchanged,
        "totals": {
            "original_from": _total(ma, "total_original_tokens"),
            "original_to": _total(mb, "total_original_tokens"),
            "original_delta": _total(mb, "total_original_tokens") - _total(ma, "total_original_tokens"),
            "sliced_from": _total(ma, "total_sliced_tokens"),
            "sliced_to": _total(mb, "total_sliced_tokens"),
            "sliced_delta": _total(mb, "total_sliced_tokens") - _total(ma, "total_sliced_tokens"),
        },
    }
