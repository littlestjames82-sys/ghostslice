"""Export a .claude_context bundle.

Bundle layout:
  <bundle>/
    manifest.json   per-file path/mode/original_tokens/sliced_tokens/sha256 + totals
    PROMPT.md       every sliced file concatenated with a file header
    files/<rel>     the sliced files, relative paths preserved
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .scanner import ScanResult, scan
from .slicer import MODES, slice_text
from .tokens import METHOD, estimate_tokens

SLICABLE = {"python", "typescript", "javascript"}


def default_mode_for(entry) -> str:
    if entry.is_test:
        return "strip-tests"
    if entry.is_lockfile:
        return "exclude"
    if entry.language in SLICABLE:
        return "signatures"
    return "full"


def build_bundle(root: str | Path, out: str | Path,
                 selections: dict[str, str] | None = None,
                 default_mode: str | None = None) -> dict:
    """Slice `root` into bundle dir `out`. Returns the manifest dict."""
    selections = selections or {}
    result: ScanResult = scan(root)
    out = Path(out)
    files_dir = out / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    manifest_files = []
    prompt_parts: list[str] = []
    total_before = 0
    total_after = 0

    for entry in result.files:
        mode = selections.get(entry.path)
        if mode is None:
            if default_mode and entry.language in SLICABLE and not entry.is_test:
                mode = default_mode
            elif default_mode and entry.is_test:
                mode = "strip-tests"
            else:
                mode = default_mode_for(entry)
        if mode not in MODES:
            raise ValueError(f"unknown mode for {entry.path}: {mode}")
        source = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
        sliced = slice_text(entry.path, source, mode)
        total_before += sliced.original_tokens
        total_after += sliced.sliced_tokens
        digest = hashlib.sha256(sliced.text.encode("utf-8")).hexdigest()
        manifest_files.append({
            "path": entry.path,
            "mode": mode,
            "language": entry.language,
            "original_tokens": sliced.original_tokens,
            "sliced_tokens": sliced.sliced_tokens,
            "sha256": digest,
        })
        if mode == "exclude" or not sliced.text:
            continue
        dest = files_dir / entry.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(sliced.text, encoding="utf-8")
        prompt_parts.append(f"\n\n---\n\n# File: {entry.path} (mode: {mode})\n\n{sliced.text.rstrip()}\n")

    manifest = {
        "tool": "ghostslice",
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(Path(root).resolve()),
        "token_method": METHOD,
        "total_original_tokens": total_before,
        "total_sliced_tokens": total_after,
        "total_saved_tokens": total_before - total_after,
        "files": manifest_files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    prompt = (
        "# Optimized agent context bundle (GhostSlice)\n\n"
        f"Estimated tokens: {total_after} (was {total_before}, saved {total_before - total_after}). "
        "Token counts are estimates, see manifest.json for the method.\n"
        + "".join(prompt_parts)
    )
    (out / "PROMPT.md").write_text(prompt, encoding="utf-8")
    return manifest


def validate_bundle(bundle: str | Path) -> dict:
    """Re-check a bundle: hashes and sliced-token totals must match disk."""
    bundle = Path(bundle)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    checked = 0
    total_sliced = 0
    for entry in manifest["files"]:
        if entry["mode"] == "exclude":
            # Excluded files may not exist on disk; their sliced tokens are 0.
            if entry["sliced_tokens"] != 0:
                errors.append(f"{entry['path']}: excluded but sliced_tokens != 0")
            continue
        dest = bundle / "files" / entry["path"]
        if not dest.is_file():
            # Sliced-to-empty files are not written; treat as empty text.
            text = ""
            if entry["sliced_tokens"] != 0:
                errors.append(f"{entry['path']}: missing from bundle but sliced_tokens != 0")
                continue
        else:
            text = dest.read_text(encoding="utf-8", errors="replace")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest != entry["sha256"]:
            # An empty slice hashes as empty even when no file was written;
            # files written by build_bundle always match unless edited.
            if text:
                errors.append(f"{entry['path']}: sha256 mismatch")
        recomputed = estimate_tokens(text)
        if recomputed != entry["sliced_tokens"]:
            errors.append(
                f"{entry['path']}: sliced_tokens {entry['sliced_tokens']} != recomputed {recomputed}")
        total_sliced += recomputed
        checked += 1
    if total_sliced != manifest["total_sliced_tokens"]:
        errors.append(
            f"total_sliced_tokens {manifest['total_sliced_tokens']} != recomputed {total_sliced}")
    return {
        "ok": not errors,
        "errors": errors,
        "files_checked": checked,
        "total_sliced_tokens": total_sliced,
        "total_original_tokens": manifest["total_original_tokens"],
    }
