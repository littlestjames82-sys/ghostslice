"""Exports: agent bundle (PROMPT.md + files + manifest.json) and JSONL chunk pack.

Chunk boundaries are document sections, never arbitrary splits (PLAN).
Deduped by default: only a cluster's probable-current member is exported
unless the profile sets superseded=include. Sensitive-held documents are
excluded by default. --fit downgrades non-authoritative docs to headings
mode before excluding lowest-priority sections; an unfittable export is
still written and reported with fitted=False (caller exits 1).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import ESTIMATOR_VERSION, __version__
from .profile import Profile
from .scan import Corpus
from .sections import Section, headings_render
from .selection import select_sections
from .tokens import estimate_tokens


@dataclass
class ExportResult:
    """Summary of one export run, including anything deliberately left out.

    ``held_out``, ``superseded_skipped``, and ``not_covered`` list the
    document paths in each category, so a caller can report exactly
    what did not go into the export. ``fitted`` is False only when a
    ``--fit`` budget was given and could not be met.
    """
    out: Path
    total_tokens: int = 0
    raw_tokens: int = 0
    fitted: bool = True
    fit_target: int | None = None
    held_out: list[str] = field(default_factory=list)
    not_covered: list[str] = field(default_factory=list)
    superseded_skipped: list[str] = field(default_factory=list)
    sections_exported: int = 0
    manifest: dict = field(default_factory=dict)


def _render(section: Section, mode: str) -> str:
    return headings_render(section) if mode == "headings" else section.text


def choose_docs(corpus: Corpus, allow_sensitive: bool = False):
    """Split corpus documents into (exportable, held out, superseded skipped).

    A document is held out when it has a holding sensitive finding
    and *allow_sensitive* is False, and skipped when the profile
    excludes superseded duplicates and the document is not its
    cluster's probable current version.
    """
    profile = corpus.profile
    superseded = corpus.superseded_paths()
    docs, held, skipped = [], [], []
    for d in corpus.docs:
        if d.held_out and not allow_sensitive:
            held.append(d.path)
            continue
        if profile.superseded == "exclude" and d.path in superseded:
            skipped.append(d.path)
            continue
        docs.append(d)
    return docs, held, skipped


def export_corpus(corpus: Corpus, out: Path, task: str | None = None,
                  fit: int | None = None, shape: str = "both",
                  allow_sensitive: bool = False) -> ExportResult:
    """Export *corpus* to the folder *out* and return an :class:`ExportResult`.

    ``task`` optionally narrows the export to relevant sections,
    ``fit`` is an estimated-token budget (see the module docstring for
    the downgrade order), and ``shape`` is ``bundle``, ``chunks``, or
    ``both``. The manifest is always written, whichever shape is used.
    """
    profile: Profile = corpus.profile
    docs, held, skipped = choose_docs(corpus, allow_sensitive)
    sections, scores = select_sections(corpus, task, docs)
    modes = {d.path: profile.mode_for(d.path) for d in docs}
    rendered: list[tuple[Section, str, str]] = []  # section, mode, text

    def rebuild():
        rendered.clear()
        for s in sections:
            mode = modes.get(s.doc_path, "full")
            if mode == "exclude":
                continue
            rendered.append((s, mode, _render(s, mode)))

    rebuild()
    total = sum(estimate_tokens(t) for _, _, t in rendered)
    fitted = True
    if fit is not None and total > fit:
        # 1) downgrade non-authoritative full docs to headings
        for p in list(modes):
            doc = next(d for d in docs if d.path == p)
            if modes[p] == "full" and not profile.is_authoritative(p):
                modes[p] = "headings"
        rebuild()
        total = sum(estimate_tokens(t) for _, _, t in rendered)
        # 2) drop lowest-priority sections (lowest TF-IDF, else largest last)
        while total > fit and rendered:
            def priority(item):
                s = item[0]
                doc = next(d for d in docs if d.path == s.doc_path)
                auth = 1 if profile.is_authoritative(s.doc_path) else 0
                return (auth, scores.get((s.doc_path, s.index), 0.0))
            # never drop the last authoritative section silently: drop lowest first
            victim = min(rendered, key=priority)
            if priority(victim)[0] == 1 and len(rendered) == 1:
                break
            sections.remove(victim[0])
            rebuild()
            total = sum(estimate_tokens(t) for _, _, t in rendered)
        # an empty bundle is not a fit: unfittable targets still write the
        # (partial) bundle and report fitted=False so the caller exits 1
        fitted = total <= fit and bool(rendered)

    out = Path(out)
    # Remember what a previous export into this same folder wrote, so files
    # this run does not write (a document since held out as sensitive, a
    # since-superseded version) do not linger on disk pretending to be part
    # of the new bundle: the manifest would say held out while the sensitive
    # text still sat in files/ from the earlier run.
    prev_paths: set[str] = set()
    prev_manifest = out / "manifest.json"
    if prev_manifest.is_file():
        try:
            prev = json.loads(prev_manifest.read_text(encoding="utf-8"))
            if isinstance(prev, dict) and isinstance(prev.get("files"), list):
                prev_paths = {f["path"] for f in prev["files"]
                              if isinstance(f, dict) and isinstance(f.get("path"), str)}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            prev_paths = set()
    out.mkdir(parents=True, exist_ok=True)
    by_doc: dict[str, list[tuple[Section, str, str]]] = {}
    for item in rendered:
        by_doc.setdefault(item[0].doc_path, []).append(item)

    manifest_files = []
    prompt_parts = [
        "# GhostDocs agent bundle",
        f"Task: {task}" if task else "Full corpus export (deduped).",
        "Token counts are estimates (estimator " + ESTIMATOR_VERSION + ").",
        "Chunk boundaries are document sections, not arbitrary splits.",
        "",
    ]
    chunks = []
    doc_dates = {d.path: d.date for d in docs}
    for rel in sorted(by_doc):
        body = "\n\n".join(t for _, _, t in by_doc[rel])
        if shape in ("both", "bundle"):
            target = out / "files" / (rel + ".txt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        orig = next(d.tokens for d in docs if d.path == rel)
        # token accounting is section-based so file totals, bundle total and
        # chunk-pack total always agree exactly (PLAN reproduction bar)
        file_tokens = sum(estimate_tokens(t) for _, _, t in by_doc[rel])
        manifest_files.append({
            "path": rel, "mode": modes.get(rel, "full"),
            "original_estimated_tokens": orig,
            "exported_estimated_tokens": file_tokens,
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "date": doc_dates.get(rel),
        })
        prompt_parts.append(f"\n===== {rel} =====\n")
        prompt_parts.append(body)
        for s, mode, text in by_doc[rel]:
            chunks.append({
                "source": rel, "heading_trail": s.heading_trail or [s.title],
                "date": doc_dates.get(rel), "mode": mode,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "estimated_tokens": estimate_tokens(text), "text": text,
            })
    total_exported = sum(f["exported_estimated_tokens"] for f in manifest_files)
    chunk_total = sum(c["estimated_tokens"] for c in chunks)
    manifest = {
        "tool": "ghostdocs", "version": __version__,
        "estimator_version": ESTIMATOR_VERSION,
        "task": task, "fit_target": fit, "fitted": fitted if fit is not None else True,
        "chunking": "document sections (heading boundaries), not arbitrary splits",
        "totals": {"exported_estimated_tokens": total_exported,
                   "chunk_estimated_tokens": chunk_total,
                   "corpus_raw_estimated_tokens": corpus.total_tokens},
        "files": manifest_files,
        "held_out": held,
        "superseded_skipped": skipped,
        "excluded_documents": sorted(set(held) | set(skipped)),
        "not_covered": [n.path for n in corpus.not_covered],
    }
    if shape in ("both", "bundle"):
        (out / "PROMPT.md").write_text("\n".join(prompt_parts), encoding="utf-8")
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if shape in ("both", "chunks"):
        with (out / "chunks.jsonl").open("w", encoding="utf-8") as fh:
            for c in chunks:
                fh.write(json.dumps(c, ensure_ascii=False) + "\n")
        if shape == "chunks":
            (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # remove stale tool-owned artifacts from a previous export into out:
    # exported files this run did not rewrite, plus PROMPT.md / chunks.jsonl
    # when the new shape does not include them (their old text is content
    # from the old export, e.g. a since-held-out document's sections)
    written = set(by_doc) if shape in ("both", "bundle") else set()
    files_root = out / "files"
    for stale in sorted(prev_paths - written):
        stale_rel = Path(stale)
        if stale_rel.is_absolute() or ".." in stale_rel.parts:
            continue  # never let a crafted old manifest point outside files/
        target = files_root / (stale + ".txt")
        try:
            target.unlink()
        except OSError:
            continue
        parent = target.parent
        while parent != files_root and files_root in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    if shape == "chunks":
        (out / "PROMPT.md").unlink(missing_ok=True)
    if shape == "bundle":
        (out / "chunks.jsonl").unlink(missing_ok=True)
    return ExportResult(out=out, total_tokens=total_exported,
                        raw_tokens=corpus.total_tokens,
                        fitted=manifest["fitted"], fit_target=fit,
                        held_out=held, superseded_skipped=skipped,
                        not_covered=[n.path for n in corpus.not_covered],
                        sections_exported=len(chunks), manifest=manifest)
