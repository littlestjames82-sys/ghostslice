"""Pack validation, mirroring `ghostslice check` semantics:
hashes and sliced-token totals (GhostSlice token method) must
match what is on disk in files/."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .scanner import language_for
from .tokens import estimate_tokens

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _unsafe_path(path: object) -> bool:
    return not isinstance(path, str) or not path \
        or path.startswith(("/", "\\")) or ".." in path.split("/")


def validate_pack(bundle: str | Path) -> dict:
    """Validate the pack at ``bundle`` against its manifest.json.

    Returns a dict with ``ok``, ``errors``, ``files_checked``, and,
    when the manifest is readable, ``total_sliced_tokens``.
    """
    bundle = Path(bundle)
    errors: list[str] = []
    mpath = bundle / "manifest.json"
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "errors": [f"manifest.json unreadable: {exc}"],
                "files_checked": 0}
    if not isinstance(manifest, dict):
        return {"ok": False,
                "errors": ["manifest.json top level is not an object"],
                "files_checked": 0}
    files = manifest.get("files", [])
    if not isinstance(files, list):
        return {"ok": False, "errors": ["manifest files is not a list"],
                "files_checked": 0}
    checked = 0
    total_sliced = 0
    for entry in files:
        if not isinstance(entry, dict) or "path" not in entry:
            errors.append("manifest file entry is missing a path")
            continue
        path = entry["path"]
        if _unsafe_path(path):
            errors.append(f"{path}: unsafe path in manifest")
            continue
        if entry.get("mode") == "exclude":
            if entry.get("sliced_tokens") != 0:
                errors.append(f"{path}: excluded but sliced_tokens != 0")
            continue
        dest = bundle / "files" / path
        if not dest.is_file():
            # build_pack writes no file for a record whose sliced
            # text is empty, so a missing file is only consistent
            # with the manifest when it declares zero tokens and the
            # empty-content hash. Anything else means pack content
            # the manifest claims is simply not there.
            if entry.get("sliced_tokens") not in (0, None) \
                    or entry.get("sha256") not in (None, _EMPTY_SHA256):
                errors.append(f"{path}: file missing from pack")
            checked += 1
            continue
        text = dest.read_bytes().decode("utf-8", errors="replace")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest != entry.get("sha256"):
            errors.append(f"{path}: sha256 mismatch")
        recomputed = estimate_tokens(text, language_for(path))
        if recomputed != entry.get("sliced_tokens"):
            errors.append(f"{path}: sliced_tokens {entry.get('sliced_tokens')} "
                          f"!= recomputed {recomputed}")
        total_sliced += recomputed
        checked += 1
    if total_sliced != manifest.get("total_sliced_tokens"):
        errors.append(f"total_sliced_tokens {manifest.get('total_sliced_tokens')} "
                      f"!= recomputed {total_sliced}")
    return {"ok": not errors, "errors": errors, "files_checked": checked,
            "total_sliced_tokens": total_sliced,
            "total_original_tokens": manifest.get("total_original_tokens", 0)}
