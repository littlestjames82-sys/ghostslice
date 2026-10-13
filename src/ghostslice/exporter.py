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

from . import __version__
from .ledger import append_record
from .scanner import ScanResult, scan
from .slicer import MODES, slice_text
from .tokens import METHOD, estimate_tokens

SLICABLE = {"python", "typescript", "javascript", "go", "rust", "java", "csharp",
            "notebook", "php", "ruby", "kotlin", "swift",
            "c", "cpp", "scala"}


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
                 default_mode: str | None = None,
                 profile=None,
                 include: set[str] | None = None,
                 preset: str | None = None,
                 record_history: bool = True,
                 exclude_secrets: bool = False,
                 fit: int | None = None,
                 fit_protect_selections: bool = True,
                 task_scores: dict | None = None) -> dict:
    """Slice `root` into bundle dir `out`. Returns the manifest dict.

    Mode precedence: explicit `selections` > profile modes (`.ghostslice.json`)
    > `default_mode` > built-in defaults. Files outside `include` (when given)
    are recorded in the manifest with mode `exclude`.

    `fit` (v0.5): when set to a token budget and the resolved selection
    slices to more than that, modes are progressively downgraded (see
    fit.py for the ladder and the protection rules) and the manifest
    gains a `fit` report. `fit_protect_selections` marks caller-supplied
    `selections` as explicit/protected; the task CLI passes False
    because its selections are machine-resolved, not user-explicit.

    Presets only change the bundle's convenience artifacts, not its core
    layout (manifest.json + PROMPT.md + files/), so `ghostslice check`
    works for every preset:
      - claude-code: the bundle as-is, meant to be dropped in as a
        .claude_context directory / pasted PROMPT.md.
      - aider: also writes aider-files.txt, one sliced file per line as a
        path inside the bundle, suitable for `aider --read <file>` entries
        or pasting into an Aider session. Aider has no bundle format of its
        own that we rely on; this is a documented plain file list.
      - generic: also writes prompt.md (lowercase) as a copy of PROMPT.md
        for tools that expect a single prompt file.
      - cursor (v0.5): also writes prompt.md (a copy of PROMPT.md) and a
        README.txt explaining how to use the bundle with Cursor (paste
        prompt.md into chat / attach the files/ directory). Meant to be
        kept as a `.cursor-context` directory next to the project.
      - copilot (v0.5): also writes prompt.md shaped for GitHub Copilot
        Chat: an instruction header plus one `## File:` section per
        sliced file with the content in a fenced code block, ready to
        paste into a Copilot Chat session.

    `task_scores` (v0.7): optional {path: {"tfidf", "symbol", "graph",
    "total"}} breakdown from selection.select_for_task_breakdown. When
    given, manifest entries for those paths gain additive `score` and
    `score_components` fields; without it the manifest is unchanged.
    """
    selections = selections or {}
    preset = preset or (profile.preset if profile else None) or "claude-code"
    ignore_matcher = profile.is_ignored if (profile and profile.path) else None
    result: ScanResult = scan(root, ignore_matcher=ignore_matcher)
    secret_files: set[str] = set()
    if exclude_secrets:
        from .secrets_scan import scan_scan_result
        secret_files = {f["path"] for f in scan_scan_result(result)}
    out = Path(out)
    files_dir = out / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    # Resolve every file's starting mode first, so --fit can downgrade
    # from exactly the modes a plain export would have used.
    resolved: dict[str, str] = {}
    for entry in result.files:
        if include is not None and entry.path not in include:
            mode = "exclude"
        else:
            mode = selections.get(entry.path)
        if mode is None and profile is not None:
            mode = profile.mode_for(entry.path)
        if mode is None:
            if default_mode and entry.language in SLICABLE and not entry.is_test:
                mode = default_mode
            elif default_mode and entry.is_test:
                mode = "strip-tests"
            else:
                mode = default_mode_for(entry)
        if entry.path in secret_files:
            mode = "exclude"  # --exclude-secrets forces exclusion (v0.4)
        if mode not in MODES:
            raise ValueError(f"unknown mode for {entry.path}: {mode}")
        resolved[entry.path] = mode
    fit_report = None
    if fit is not None:
        from .fit import fit_modes
        protected = set(selections) if fit_protect_selections else set()
        resolved, fit_report = fit_modes(result, resolved, fit,
                                         profile=profile, protected=protected)

    manifest_files = []
    prompt_parts: list[str] = []
    copilot_parts: list[str] = []
    total_before = 0
    total_after = 0

    for entry in result.files:
        mode = resolved[entry.path]
        source = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
        sliced = slice_text(entry.path, source, mode)
        total_before += sliced.original_tokens
        total_after += sliced.sliced_tokens
        digest = hashlib.sha256(sliced.text.encode("utf-8")).hexdigest()
        manifest_entry = {
            "path": entry.path,
            "mode": mode,
            "language": entry.language,
            "original_tokens": sliced.original_tokens,
            "sliced_tokens": sliced.sliced_tokens,
            "sha256": digest,
        }
        if task_scores and entry.path in task_scores:
            bd = task_scores[entry.path]
            manifest_entry["score"] = bd["total"]
            manifest_entry["score_components"] = {
                "tfidf": bd["tfidf"], "symbol": bd["symbol"], "graph": bd["graph"],
            }
        manifest_files.append(manifest_entry)
        if mode == "exclude" or not sliced.text:
            continue
        dest = files_dir / entry.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(sliced.text, encoding="utf-8")
        prompt_parts.append(f"\n\n---\n\n# File: {entry.path} (mode: {mode})\n\n{sliced.text.rstrip()}\n")
        fence_lang = "" if entry.language in ("text", "notebook") else entry.language
        copilot_parts.append(
            f"\n\n## File: {entry.path} (mode: {mode})\n\n```{fence_lang}\n{sliced.text.rstrip()}\n```\n")

    manifest = {
        "tool": "ghostslice",
        "version": __version__,
        "preset": preset,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(Path(root).resolve()),
        "token_method": METHOD,
        "total_original_tokens": total_before,
        "total_sliced_tokens": total_after,
        "total_saved_tokens": total_before - total_after,
        "files": manifest_files,
    }
    if fit_report is not None:
        manifest["fit"] = fit_report
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    prompt = (
        "# Optimized agent context bundle (GhostSlice)\n\n"
        f"Estimated tokens: {total_after} (was {total_before}, saved {total_before - total_after}). "
        "Token counts are estimates, see manifest.json for the method.\n"
        + "".join(prompt_parts)
    )
    (out / "PROMPT.md").write_text(prompt, encoding="utf-8")
    if preset == "generic":
        (out / "prompt.md").write_text(prompt, encoding="utf-8")
    elif preset == "cursor":
        (out / "prompt.md").write_text(prompt, encoding="utf-8")
        (out / "README.txt").write_text(
            "GhostSlice bundle for Cursor (.cursor-context)\n"
            "================================================\n\n"
            "This bundle was sliced by GhostSlice: signatures instead of\n"
            "full bodies where that is enough, tests stripped, lockfiles\n"
            "excluded. Token counts in manifest.json are estimates.\n\n"
            "How to use it with Cursor:\n"
            "  1. Paste prompt.md into a Cursor chat (Composer or Chat) as\n"
            "     the opening context, or\n"
            "  2. attach the individual files under files/ with @-mentions\n"
            "     for the pieces your question touches, or\n"
            "  3. copy files/ into your project as reference material and\n"
            "     @-reference them there.\n\n"
            "PROMPT.md is the same content as prompt.md in the standard\n"
            "bundle layout; manifest.json records each file's slice mode\n"
            "and token estimate. Verify this bundle any time with:\n"
            "  ghostslice check <this directory>\n",
            encoding="utf-8")
    elif preset == "copilot":
        copilot_prompt = (
            "# Copilot context (GhostSlice bundle)\n\n"
            "Paste this whole file into a GitHub Copilot Chat session, or attach\n"
            "it as context. It contains a sliced view of the project: signatures\n"
            "instead of full bodies where that is enough, tests stripped,\n"
            "lockfiles excluded. Token counts are estimates (see manifest.json).\n"
            + "".join(copilot_parts))
        (out / "prompt.md").write_text(copilot_prompt, encoding="utf-8")
    elif preset == "aider":
        written = [f["path"] for f in manifest_files
                   if f["mode"] != "exclude" and f["sliced_tokens"] > 0]
        listing = "\n".join(f"files/{p}" for p in written)
        (out / "aider-files.txt").write_text(
            "# GhostSlice bundle for Aider: pass these sliced files as read-only\n"
            "# context, e.g. `aider --read files/<path>` for each line, or paste\n"
            "# PROMPT.md into the session instead. Plain file list, no magic format.\n"
            + listing + ("\n" if listing else ""), encoding="utf-8")
    if record_history:
        try:
            append_record(root, "export", total_before, total_after, bundle=str(out))
        except OSError:
            pass
    return manifest


def estimate_context_tokens(root: str | Path, profile=None,
                            default_mode: str | None = None) -> tuple[int, int]:
    """(total original, total sliced) tokens for the default/profile selection."""
    ignore_matcher = profile.is_ignored if (profile and profile.path) else None
    result: ScanResult = scan(root, ignore_matcher=ignore_matcher)
    before = after = 0
    for entry in result.files:
        mode = profile.mode_for(entry.path) if profile is not None else None
        if mode is None:
            if default_mode and entry.language in SLICABLE and not entry.is_test:
                mode = default_mode
            elif default_mode and entry.is_test:
                mode = "strip-tests"
            else:
                mode = default_mode_for(entry)
        if mode == "full":
            before += entry.tokens
            after += entry.tokens
        elif mode == "exclude":
            before += entry.tokens
        else:
            source = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
            r = slice_text(entry.path, source, mode)
            before += r.original_tokens
            after += r.sliced_tokens
    return before, after


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
