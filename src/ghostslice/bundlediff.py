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
    return json.loads((Path(bundle) / "manifest.json").read_text(encoding="utf-8"))


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
    fa = {f["path"]: f for f in ma["files"]}
    fb = {f["path"]: f for f in mb["files"]}
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
            "original_from": ma["total_original_tokens"],
            "original_to": mb["total_original_tokens"],
            "original_delta": mb["total_original_tokens"] - ma["total_original_tokens"],
            "sliced_from": ma["total_sliced_tokens"],
            "sliced_to": mb["total_sliced_tokens"],
            "sliced_delta": mb["total_sliced_tokens"] - ma["total_sliced_tokens"],
        },
    }
