"""Staleness: does a built bundle still match its project?

`check` verifies a bundle against its own manifest. `stale` answers
the question a returning session asks next: the project kept moving
after the bundle was built, so does the pack still describe it?

The manifest is never trusted on its own. The bundle must first pass
check_bundle; staleness is only reported for a verified bundle. Only
then is each recorded source re-read, and every source path is
re-verified project-local (resolved, symlink-aware) before it is
opened, exactly as at build time. A source that now resolves outside
the project root, or into a private memory location, is refused and
never read.

What counts as stale: a bundled file whose re-sliced text no longer
hashes to the recorded sha256, a bundled source that is gone, a
refused source, a changed project fact (name / version / description),
a new entry point the pack does not know, or a memory source that is
gone or refused. What does not: a new non-entry code file (the pack is
a starter subset by design; new files are listed for information) and
a memory source that merely has a newer mtime (listed, never a
verdict: mtime is a hint, not evidence of changed content). A source
edit that leaves the recorded slice unchanged (a comment under
signatures mode, say) is likewise not detected; staleness is stated
about the pack, and the pack is the slices.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import scan, secrets as secrets_mod
from .bundle import check_bundle, sha256_text
from .slicer import slice_source


def _generated_epoch(manifest: dict) -> float | None:
    raw = manifest.get("generated_at")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).timestamp()


def staleness_report(bundle_dir, project=None) -> tuple[int, dict]:
    """Return (exit_code, report). 0 fresh, 1 stale, 2 could not check."""
    code, check = check_bundle(bundle_dir)
    if code != 0:
        return 2, {"ok": False, "stale": None,
                   "errors": ["bundle does not pass check; staleness is "
                              "only reported for a verified bundle: "
                              + "; ".join(check.get("errors", []))]}
    bundle = Path(bundle_dir)
    manifest = json.loads(
        (bundle / "manifest.json").read_text(encoding="utf-8"))
    if project is not None:
        root = Path(project)
        root_source = "argument"
    else:
        root = Path(str(manifest.get("root", "")))
        root_source = "manifest"
    if not root.is_dir():
        return 2, {"ok": False, "stale": None,
                   "errors": [f"project root not found: {root}"]}
    if scan.is_private_memory(root):
        return 2, {"ok": False, "stale": None,
                   "errors": ["refused: project root is a private "
                              "memory location"]}
    root = root.resolve()

    changed: list[dict] = []
    missing: list[str] = []
    refused: list[dict] = []
    unchanged: list[str] = []
    recorded: set[str] = set()
    for entry in manifest.get("files", []):
        rel = entry.get("path", "")
        if not rel:
            continue
        recorded.add(rel)
        try:
            resolved = scan.assert_project_local(root, root / rel)
        except ValueError as exc:
            refused.append({"path": rel, "reason": str(exc)})
            continue
        if not resolved.is_file():
            missing.append(rel)
            continue
        source = resolved.read_text(encoding="utf-8", errors="replace")
        if secrets_mod.scan_text(source):
            changed.append({
                "path": rel,
                "reason": "source now contains a secret-shaped literal; "
                          "a rebuild would exclude this file"})
            continue
        mode = entry.get("mode") or "signatures"
        text, _confidence = slice_source(rel, source, mode)
        if sha256_text(text) != entry.get("sha256"):
            changed.append({
                "path": rel,
                "reason": "re-sliced source no longer matches the "
                          "recorded sha256"})
        else:
            unchanged.append(rel)

    facts_changed: list[dict] = []
    current_facts = scan.project_facts(root)
    recorded_facts = manifest.get("facts") or {}
    for field in ("name", "version", "description"):
        if recorded_facts.get(field) != current_facts.get(field):
            facts_changed.append({"field": field,
                                  "bundle": recorded_facts.get(field),
                                  "current": current_facts.get(field)})

    known = recorded | {n.get("path", "")
                        for n in manifest.get("not_included", [])}
    current_entries = set(scan.find_entry_points(root, current_facts))
    new_entry_points = sorted(
        current_entries - set(manifest.get("entry_points", [])))
    new_files: list[str] = []
    for rel, _p in scan.iter_project_files(root):
        if Path(rel).suffix.lower() in scan.CODE_EXTS \
                and not rel.startswith(("tests/", "test/")) \
                and rel not in known:
            new_files.append(rel)
    new_files.sort()

    memory_missing: list[str] = []
    memory_refused: list[dict] = []
    memory_newer: list[str] = []
    epoch = _generated_epoch(manifest)
    for item in manifest.get("memory_items", []):
        prov = item.get("provenance") or {}
        prov_path = prov.get("path", "")
        if item.get("source_type") == "handoff":
            # A handoff item's source is the pack file recorded at
            # build time (an explicitly supplied input outside the
            # project), not a project-local file.
            pack = prov.get("pack")
            if not pack or not Path(pack).exists():
                memory_missing.append(prov_path or "handoff.json")
            continue
        if not prov_path:
            continue
        try:
            resolved = scan.assert_project_local(root, root / prov_path)
        except ValueError as exc:
            memory_refused.append({"path": prov_path, "reason": str(exc)})
            continue
        if not resolved.is_file():
            memory_missing.append(prov_path)
            continue
        if epoch is not None:
            try:
                # generated_at is recorded at one-second resolution;
                # allow a small grace so a source written in the same
                # moment as the build is not reported as newer.
                if resolved.stat().st_mtime > epoch + 2:
                    memory_newer.append(prov_path)
            except OSError:
                pass
    memory_missing = sorted(set(memory_missing))
    memory_newer = sorted(set(memory_newer))

    stale = bool(changed or missing or refused or facts_changed
                 or new_entry_points or memory_missing or memory_refused)
    report = {
        "ok": not stale,
        "stale": stale,
        "bundle": str(bundle),
        "project": str(root),
        "project_root_source": root_source,
        "generated_at": manifest.get("generated_at"),
        "files_checked": (len(unchanged) + len(changed)
                          + len(missing) + len(refused)),
        "unchanged": unchanged,
        "changed": changed,
        "missing": missing,
        "refused": refused,
        "facts_changed": facts_changed,
        "new_entry_points": new_entry_points,
        "new_files": new_files,
        "memory_missing": memory_missing,
        "memory_refused": memory_refused,
        "memory_sources_newer": memory_newer,
    }
    return (1 if stale else 0), report
