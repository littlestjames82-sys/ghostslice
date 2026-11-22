"""Project-memory primer: extractive, project-local, provenance-carrying.

Two paths, recorded in the manifest:
- recall-bundle: consume a GhostRecall bundle's selected CURRENT memory
  items verbatim (Recall owns selection, supersession, conflicts).
- fallback: a shallow pass over a fixed list of project-local memory
  files: headings plus capped section extracts. Deliberately dumb,
  stated as such in the bundle.

Every item carries provenance {path, line}. Items with secret-shaped
literals are blocked: recorded with reason, never included. Sources
outside the project root, or inside the user's private memory
locations, are refused by path check in scan.assert_project_local.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import secrets as secrets_mod
from .scan import assert_project_local, is_private_memory

FALLBACK_FILES = [
    "AGENTS.md", "CLAUDE.md", "DECISIONS.md", "CHANGELOG.md",
    "CONTRIBUTING.md", "PLAN.md", "ROADMAP.md", "ROADMAP_20.md",
]
PER_FILE_LINE_CAP = 60
PER_SECTION_LINE_CAP = 8


def _sections(text: str):
    """Yield (heading, heading_line_no, [body lines with line numbers])."""
    lines = text.splitlines()
    current = ("(top)", 1, [])
    for idx, line in enumerate(lines, 1):
        if re.match(r"^#{1,3}\s+\S", line):
            yield current
            current = (line.lstrip("# ").strip(), idx, [])
        else:
            current[2].append((idx, line))
    yield current


def _extract_file(rel: str, text: str, changelog: bool = False) -> list[dict]:
    """Split one memory file into heading sections and extract items.

    Each item is a heading plus up to PER_SECTION_LINE_CAP non-blank
    body lines, capped at PER_FILE_LINE_CAP lines per file. With
    changelog=True only the preamble and the latest entry are kept.
    """
    items = []
    sections = list(_sections(text))
    if changelog:
        # Latest entry only: preamble (top + document title section)
        # plus the first release section; older entries are dropped.
        sections = sections[:3]
    budget_lines = PER_FILE_LINE_CAP
    for heading, line_no, body in sections:
        if budget_lines <= 0:
            break
        picked = []
        for ln, raw in body:
            if raw.strip():
                picked.append((ln, raw))
            if len(picked) >= PER_SECTION_LINE_CAP:
                break
        if not picked:
            # A heading with no extractable body lines adds nothing:
            # the heading itself already appears as structure.
            continue
        picked = picked[:budget_lines]
        budget_lines -= len(picked)
        block_lines = ([f"## {heading}"] if heading != "(top)" else []) + \
                      [raw for _ln, raw in picked]
        items.append({
            "id": f"memory-{rel}-{line_no}",
            "source_type": "memory",
            "title": heading if heading != "(top)" else rel,
            "text": "\n".join(block_lines),
            "provenance": {"path": rel, "line": line_no},
            "status": "current",
        })
    return items


def fallback_memory(root: Path) -> tuple[list[dict], list[dict]]:
    """Shallow fallback memory: (items, blocked) from a fixed file list.

    Reads only the well-known project-local files in FALLBACK_FILES
    plus ``docs/decisions/*.md``, when present. Each candidate is
    passed through the resolved-path check first; a refused path and
    a secret-flagged item both land in blocked (recorded, not read
    into the pack), never silently dropped.
    """
    items: list[dict] = []
    blocked: list[dict] = []
    candidates: list[Path] = []
    for name in FALLBACK_FILES:
        p = root / name
        if p.exists():
            candidates.append(p)
    decisions_dir = root / "docs" / "decisions"
    if decisions_dir.is_dir():
        candidates.extend(sorted(decisions_dir.glob("*.md")))
    for p in candidates:
        rel = p.relative_to(root).as_posix()
        try:
            resolved = assert_project_local(root, p)
        except ValueError as exc:
            blocked.append({"path": rel, "reason": str(exc)})
            continue
        try:
            if resolved.is_dir():
                raise IsADirectoryError(f"memory source is a directory: {p}")
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            blocked.append({"path": rel,
                            "reason": f"memory source unreadable; skipped: {exc}"})
            continue
        # Block at item granularity, per the plan: the item whose text
        # carries a secret-shaped literal is excluded and recorded
        # (path, item, shapes only - never the value); the file's other
        # items are unaffected. Only emitted text can leak, and every
        # item's text is scanned here before it can be included.
        for item in _extract_file(
                rel, text, changelog=(Path(rel).name == "CHANGELOG.md")):
            findings = secrets_mod.scan_text(item["text"])
            if findings:
                blocked.append({
                    "path": rel,
                    "title": item["title"],
                    "line": item["provenance"]["line"],
                    "reason": "secret-shaped literal found ("
                              + ", ".join(sorted({f['type']
                                                  for f in findings}))
                              + "); memory item blocked, "
                                "value not recorded",
                })
                continue
            items.append(item)
    return items, blocked


def recall_bundle_memory(root: Path, bundle_dir: Path) -> tuple[list[dict], list[dict]]:
    """Consume a GhostRecall bundle: current memory items only, verbatim.

    The recall bundle itself must live inside the project root or be a
    bundle directory the caller points at explicitly; its item files are
    read from the bundle, and provenance is taken from Recall's own
    manifest. Superseded, excluded and blocked items are never included.
    """
    blocked: list[dict] = []
    bundle_dir = Path(bundle_dir)
    if is_private_memory(bundle_dir):
        raise ValueError(
            f"refused: recall bundle is in a private memory location: {bundle_dir}")
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"recall bundle has no manifest.json: {bundle_dir}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(
            f"recall bundle manifest is not valid JSON: {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"recall bundle manifest is not an object: {manifest_path}")
    entries = data.get("items") or data.get("memory_items") or data.get("files") or []
    if not isinstance(entries, list):
        raise ValueError(f"recall bundle manifest items are not a list: {manifest_path}")
    try:
        bundle_resolved = bundle_dir.resolve()
    except Exception as exc:
        raise ValueError(f"recall bundle path cannot be resolved: {bundle_dir}") from exc
    items: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("source_type") == "code":
            continue
        status = str(entry.get("status", "current")).lower()
        mode = str(entry.get("mode", "")).lower()
        if status in ("superseded", "excluded", "blocked") or mode == "exclude":
            continue
        provenance = entry.get("provenance") or {}
        if not isinstance(provenance, dict):
            provenance = {}
        src_path = provenance.get("path") or entry.get("path") or ""
        text = None
        exported = entry.get("exported_file") or entry.get("file")
        if exported:
            # An exported item file must stay inside the recall bundle
            # itself. An absolute path or a ../ traversal (previously
            # joined unchecked, so it could name any file on disk -
            # including the user's private memory) is blocked, never
            # read; a bundle-internal symlink escaping the bundle is
            # refused the same way.
            candidates = [bundle_dir / "files" / Path(str(exported)).name,
                          bundle_dir / str(exported)]
            exported_blocked = False
            for candidate in candidates:
                try:
                    if not candidate.exists():
                        continue
                    resolved_c = candidate.resolve()
                except Exception:
                    exported_blocked = True
                    continue
                if is_private_memory(candidate) or (
                        resolved_c != bundle_resolved
                        and bundle_resolved not in resolved_c.parents):
                    exported_blocked = True
                    continue
                try:
                    if resolved_c.is_dir():
                        continue
                    text = resolved_c.read_text(
                        encoding="utf-8", errors="replace")
                except OSError:
                    exported_blocked = True
                    continue
                break
            if text is None and exported_blocked:
                blocked.append({
                    "path": src_path or str(exported),
                    "reason": "refused: recall exported file resolves "
                              "outside the recall bundle or is unreadable; "
                              "item blocked"})
                continue
        if text is None and src_path:
            candidate = root / src_path
            try:
                resolved = assert_project_local(root, candidate)
                if resolved.exists() and not resolved.is_dir():
                    text = resolved.read_text(encoding="utf-8", errors="replace")
            except ValueError as exc:
                blocked.append({"path": src_path, "reason": str(exc)})
                continue
            except OSError:
                blocked.append({"path": src_path,
                                "reason": "recall item source unreadable; skipped"})
                continue
        if text is None:
            blocked.append({"path": src_path or str(entry.get("id")),
                            "reason": "recall item content not found; skipped"})
            continue
        findings = secrets_mod.scan_text(text)
        if findings:
            blocked.append({"path": src_path,
                            "reason": "secret-shaped literal in recall item; blocked"})
            continue
        try:
            prov_line = int(provenance.get("line", 1) or 1)
        except (TypeError, ValueError):
            prov_line = 1
        items.append({
            "id": str(entry.get("id") or f"memory-{src_path}"),
            "source_type": "memory",
            "title": str(entry.get("title") or src_path),
            "text": text,
            "provenance": {"path": src_path,
                           "line": prov_line},
            "status": "current",
        })
    return items, blocked


def readme_extract(text: str, cap_lines: int = 80) -> str:
    """Title, headings, and the first paragraph under each heading.

    A paragraph is the first run of consecutive non-blank lines after a
    heading; blank lines between the heading and the paragraph (the
    normal Markdown layout) are skipped, and every line of the
    paragraph is kept, verbatim.
    """
    out: list[str] = []
    lines = text.splitlines()
    seeking = False   # heading seen, its first paragraph not yet started
    in_para = False   # collecting lines of that first paragraph
    for line in lines:
        if len(out) >= cap_lines:
            break
        if re.match(r"^#{1,3}\s+\S", line):
            out.append(line)
            seeking = True
            in_para = False
        elif not line.strip():
            if in_para:
                in_para = False
                seeking = False
        elif seeking or in_para:
            out.append(line)
            seeking = False
            in_para = True
    return "\n".join(out).strip() + "\n"
