"""Corpus scan: inventory, heat, duplicate clusters, stale heuristics, hold-outs."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .extract import COVERED_EXTS, NOT_COVERED_EXTS, Extraction, extract_file
from .profile import Profile
from .sections import Section, find_date, split_sections
from .sensitive import Finding, hold_findings, scan_text
from .tokens import estimate_tokens

NEAR_DUP_THRESHOLD = 0.85
_SKIP_DIRS = {".git", "__pycache__", ".ghostdocs-cache", "node_modules"}


@dataclass
class Doc:
    """One covered document: its extraction, sections, date, and findings."""

    path: str                       # relative to corpus
    extraction: Extraction
    sections: list[Section] = field(default_factory=list)
    date: str | None = None         # explicit date in text, else file mtime date
    date_source: str = "mtime"
    findings: list[Finding] = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.extraction.text

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.extraction.text)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.extraction.text.encode("utf-8")).hexdigest()

    @property
    def held_out(self) -> bool:
        return bool(hold_findings(self.findings))

    def to_dict(self, total_tokens: int) -> dict:
        ex = self.extraction
        return {
            "path": self.path, "format": ex.fmt, "tokens": self.tokens,
            "heat_pct": round(100 * self.tokens / total_tokens, 2) if total_tokens else 0.0,
            "chars": ex.chars, "pages": ex.pages, "chars_per_page": ex.chars_per_page,
            "extraction_flags": ex.flags, "date": self.date, "date_source": self.date_source,
            "sha256": self.sha256, "held_out": self.held_out,
            "findings": [f.to_dict() for f in self.findings],
            "sections": [{"title": s.title, "heading_trail": s.heading_trail,
                          "tokens": s.tokens, "sha256": s.sha256} for s in self.sections],
        }


@dataclass
class NotCovered:
    """A file GhostDocs cannot read in this version, with the reason why.

    Not-covered files are always named in scans, reports, and export
    manifests; they are never silently skipped and never exported.
    """

    path: str
    fmt: str
    reason: str
    extraction_flags: list[str] = field(default_factory=list)
    pages: int | None = None

    def to_dict(self):
        return {"path": self.path, "format": self.fmt, "reason": self.reason,
                "extraction_flags": self.extraction_flags, "pages": self.pages}


@dataclass
class Cluster:
    """A group of exact or near-duplicate documents.

    ``probable_current`` is the member treated as current (an
    authoritative source if the profile names one, otherwise the
    newest dated member, which is a heuristic, not a fact).
    ``wasted_tokens`` counts the estimated tokens in the other members.
    """

    members: list[str]
    kind: str                       # exact | near
    probable_current: str
    current_reason: str             # authoritative-source | newest-date (heuristic)
    stale: list[str] = field(default_factory=list)
    wasted_tokens: int = 0          # tokens in non-current members

    def to_dict(self):
        return {"members": self.members, "kind": self.kind,
                "probable_current": self.probable_current,
                "current_reason": self.current_reason,
                "probable_current_is_heuristic": self.current_reason.startswith("newest-date"),
                "stale": self.stale, "wasted_tokens": self.wasted_tokens}


@dataclass
class Corpus:
    """A scanned corpus: covered documents, not-covered files, and clusters."""

    root: Path
    profile: Profile
    docs: list[Doc] = field(default_factory=list)
    not_covered: list[NotCovered] = field(default_factory=list)
    clusters: list[Cluster] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(d.tokens for d in self.docs)

    @property
    def wasted_tokens(self) -> int:
        return sum(c.wasted_tokens for c in self.clusters)

    def probable_current_paths(self) -> set[str]:
        return {c.probable_current for c in self.clusters}

    def superseded_paths(self) -> set[str]:
        cur = self.probable_current_paths()
        out = set()
        for c in self.clusters:
            out.update(m for m in c.members if m != c.probable_current)
        return out - cur

    def summary(self) -> dict:
        total = self.total_tokens
        return {
            "documents": len(self.docs), "coverage_gaps": len(self.not_covered),
            "total_estimated_tokens": total,
            "duplicate_clusters": len(self.clusters),
            "wasted_estimated_tokens": self.wasted_tokens,
            "deduped_estimated_tokens": total - self.wasted_tokens,
            "held_out_documents": sum(1 for d in self.docs if d.held_out),
        }

    def to_dict(self) -> dict:
        total = self.total_tokens
        # clusters and coverage gaps come before the document list so a
        # reader (human or test) meeting a filename first meets it with its
        # cluster / coverage context attached, not in a bare heat list
        return {"summary": self.summary(),
                "clusters": [c.to_dict() for c in self.clusters],
                "coverage_gaps": [n.to_dict() for n in self.not_covered],
                "documents": [d.to_dict(total) for d in
                              sorted(self.docs, key=lambda d: -d.tokens)]}


def _line_shingles(text: str, n: int = 3) -> set[tuple]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < n:
        return {tuple(lines)} if lines else set()
    return {tuple(lines[i:i + n]) for i in range(len(lines) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _clusters(docs: list[Doc], profile: Profile) -> list[Cluster]:
    parent = {d.path: d.path for d in docs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    exact_kinds: dict[str, str] = {}
    by_hash: dict[str, list[Doc]] = {}
    for d in docs:
        by_hash.setdefault(d.sha256, []).append(d)
    for group in by_hash.values():
        if len(group) > 1:
            for d in group[1:]:
                union(group[0].path, d.path)
                exact_kinds[d.path] = "exact"
    shingles = {d.path: _line_shingles(d.text) for d in docs}
    from collections import Counter
    import math
    from .tokens import words as _words
    counts = {d.path: Counter(_words(d.text)) for d in docs}

    def _cosine(a: str, b: str) -> float:
        ca, cb = counts[a], counts[b]
        if not ca or not cb:
            return 0.0
        dot = sum(ca[t] * cb[t] for t in ca.keys() & cb.keys())
        na = math.sqrt(sum(v * v for v in ca.values()))
        nb = math.sqrt(sum(v * v for v in cb.values()))
        return dot / (na * nb) if na and nb else 0.0

    for i, a in enumerate(docs):
        for b in docs[i + 1:]:
            if a.sha256 == b.sha256:
                continue
            # near-duplicate: line-shingle Jaccard (GhostSlice method) OR
            # word-count cosine, which catches small edits in short documents
            # where a few changed lines break most line shingles.
            if (_jaccard(shingles[a.path], shingles[b.path]) >= NEAR_DUP_THRESHOLD
                    or _cosine(a.path, b.path) >= 0.90):
                union(a.path, b.path)
    groups: dict[str, list[Doc]] = {}
    for d in docs:
        groups.setdefault(find(d.path), []).append(d)
    clusters: list[Cluster] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        members = sorted(d.path for d in group)
        kind = "exact" if len({d.sha256 for d in group}) == 1 else "near"
        auth = [d for d in group if profile.is_authoritative(d.path)]
        if auth:
            current = sorted(auth, key=lambda d: (d.date or "", d.path))[-1]
            reason = "authoritative-source"
        else:
            current = sorted(group, key=lambda d: (d.date or "", d.path))[-1]
            reason = "newest-date (heuristic)"
        stale = [d.path for d in group
                 if d.path != current.path and (d.date or "") < (current.date or "")]
        wasted = sum(d.tokens for d in group if d.path != current.path)
        clusters.append(Cluster(members=members, kind=kind,
                                probable_current=current.path, current_reason=reason,
                                stale=sorted(stale), wasted_tokens=wasted))
    return sorted(clusters, key=lambda c: c.members)


def scan_corpus(root: Path, profile: Profile | None = None) -> Corpus:
    """Scan the corpus folder at *root* and return a :class:`Corpus`.

    Walks the folder recursively, extracts every covered file allowed
    by *profile* (a default profile is used when none is given),
    records every not-covered file with its reason, and then computes
    duplicate clusters. Original files are only read, never changed.
    """
    root = Path(root)
    profile = profile or Profile()
    corpus = Corpus(root=root, profile=profile)
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        # skip-dirs are judged on the path inside the corpus, not the whole
        # filesystem path: a corpus that itself lives under a folder called
        # e.g. "node_modules" used to scan as completely empty
        if any(part in _SKIP_DIRS for part in rel.split("/")[:-1]):
            continue
        if rel == ".ghostdocs.json":
            continue
        ext = path.suffix.lower()
        if ext in COVERED_EXTS:
            if not profile.included(rel):
                continue
            try:
                ex = extract_file(path)
            except OSError as exc:
                # a file that cannot be read is named, never a crash and
                # never silently skipped (broken symlink, permissions, ...)
                corpus.not_covered.append(NotCovered(
                    path=rel, fmt=ext.lstrip("."),
                    reason=f"file could not be read: {exc.strerror or exc}"))
                continue
            if not ex.covered:
                corpus.not_covered.append(NotCovered(
                    path=rel, fmt=ex.fmt, reason=ex.reason,
                    extraction_flags=ex.flags, pages=ex.pages))
                continue
            sections = split_sections(rel, ex.text)
            explicit = find_date(ex.text)
            if explicit:
                date, source = explicit, "document"
            else:
                try:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                except OSError as exc:
                    corpus.not_covered.append(NotCovered(
                        path=rel, fmt=ext.lstrip("."),
                        reason=f"file could not be read: {exc.strerror or exc}"))
                    continue
                date, source = mtime.date().isoformat(), "mtime"
            findings = scan_text(rel, ex.text)
            corpus.docs.append(Doc(path=rel, extraction=ex, sections=sections,
                                   date=date, date_source=source, findings=findings))
        elif ext in NOT_COVERED_EXTS:
            if profile.included(rel):
                corpus.not_covered.append(NotCovered(
                    path=rel, fmt=ext.lstrip("."), reason=NOT_COVERED_EXTS[ext]))
        else:
            # any other format (.csv, .png, no extension, ...) is named as
            # not covered too: the README promises nothing is silently
            # skipped, and the old code dropped these without a word
            if profile.included(rel):
                corpus.not_covered.append(NotCovered(
                    path=rel, fmt=ext.lstrip(".") or "none",
                    reason=f"format {ext or '(no extension)'} not covered in v0.1"))
    corpus.clusters = _clusters(corpus.docs, profile)
    return corpus
