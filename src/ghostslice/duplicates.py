"""Duplicate detection: exact and near-duplicate files.

Exact: sha256 of normalized content (per-line trailing whitespace
stripped, trailing blank lines dropped). Files whose normalized content
is empty or shorter than 20 characters are ignored (noise floor).

Near: Jaccard similarity over the set of distinct non-empty stripped
lines ("line shingles"). Only files with at least 8 distinct lines and
at least 200 normalized characters are compared (size floor, to avoid
flagging every tiny boilerplate file), and pairs at similarity
>= 0.85 (documented threshold) are reported. Exact-duplicate pairs
are not repeated in the near list.
"""
from __future__ import annotations
from .textio import read_text as _gs_read_text

import hashlib
from pathlib import Path

NEAR_THRESHOLD = 0.85
NEAR_MIN_LINES = 8
NEAR_MIN_CHARS = 200
EXACT_MIN_CHARS = 20


def normalize(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def line_shingles(text: str) -> set[str]:
    return {ln.strip() for ln in normalize(text).splitlines() if ln.strip()}


def find_duplicates(scan_result) -> dict:
    """Return {"exact": [...], "near": [...]} for a ScanResult."""
    by_path = {f.path: f for f in scan_result.files}
    texts: dict[str, str] = {}
    for entry in scan_result.files:
        try:
            raw = _gs_read_text(entry.abspath)
        except OSError:
            continue
        texts[entry.path] = normalize(raw)

    # Exact
    by_hash: dict[str, list[str]] = {}
    for path, norm in texts.items():
        if len(norm) < EXACT_MIN_CHARS:
            continue
        digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()
        by_hash.setdefault(digest, []).append(path)
    exact: list[dict] = []
    exact_pairs: set[frozenset] = set()
    for digest, paths in sorted(by_hash.items()):
        if len(paths) < 2:
            continue
        paths = sorted(paths)
        for a in paths:
            for b in paths:
                if a < b:
                    exact_pairs.add(frozenset((a, b)))
        tokens_each = by_path[paths[0]].tokens
        exact.append({
            "hash": digest,
            "files": paths,
            "tokens_each": tokens_each,
            "potential_savings": sum(by_path[p].tokens for p in paths) - tokens_each,
        })
    exact.sort(key=lambda g: g["potential_savings"], reverse=True)

    # Near (pairwise over files above the size floor)
    candidates = [p for p, norm in texts.items()
                  if len(norm) >= NEAR_MIN_CHARS and len(line_shingles(norm)) >= NEAR_MIN_LINES]
    shingles = {p: line_shingles(texts[p]) for p in candidates}
    near: list[dict] = []
    for i, a in enumerate(sorted(candidates)):
        for b in sorted(candidates)[i + 1:]:
            if frozenset((a, b)) in exact_pairs:
                continue
            sa, sb = shingles[a], shingles[b]
            union = sa | sb
            if not union:
                continue
            sim = len(sa & sb) / len(union)
            if sim >= NEAR_THRESHOLD:
                near.append({
                    "files": [a, b],
                    "similarity": round(sim, 4),
                    "tokens": min(by_path[a].tokens, by_path[b].tokens),
                    "potential_savings": min(by_path[a].tokens, by_path[b].tokens),
                })
    near.sort(key=lambda r: r["similarity"], reverse=True)
    return {"exact": exact, "near": near}
