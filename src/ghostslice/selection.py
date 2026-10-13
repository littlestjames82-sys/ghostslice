"""Task-focused context selection.

Two selection strategies, both producing a set of project paths plus their
resolved slice modes (profile modes win, then exporter defaults):

- Task keywords (TF-IDF since v0.5): score each file by TF-IDF of the
  task keywords over the project's files (term frequency capped at 20
  per keyword per file, inverse document frequency smoothed as
  ln((1 + N) / (1 + df)) + 1, N = files considered). Path hits keep
  their boost: they count 5x, weighted by the same idf. Content
  matching is whole-word (tokenised), unlike the pre-v0.5 substring
  counts, so a keyword buried in a common word no longer inflates a
  file. Scores are floats. Files are taken best-first until the token
  budget (of *sliced* tokens) would be exceeded; the single best file
  is always included even if it alone exceeds the budget, so a
  selection is never empty when there is any match. Deterministic:
  ties break by larger file, then scan order.
- Diff: files changed in the git working tree plus their direct
  dependencies (what they import, and what imports them).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from .exporter import SLICABLE, default_mode_for
from .graph import build_graph, changed_files, importers_of
from .scanner import scan
from .slicer import slice_text

_WORD_RE = re.compile(r"[a-z0-9_]+")
_TF_CAP = 20
_PATH_BOOST = 5


def idf(df: int, n_docs: int) -> float:
    """Smoothed inverse document frequency: ln((1 + N) / (1 + df)) + 1."""
    return math.log((1 + n_docs) / (1 + df)) + 1.0


def keywords_from_task(task: str) -> list[str]:
    words = [w for w in _WORD_RE.findall(task.lower()) if len(w) >= 3]
    # de-duplicate, keep order
    return list(dict.fromkeys(words))


def _sliced_tokens(entry, mode: str, cache: dict) -> int:
    key = (entry.path, mode)
    if key not in cache:
        if mode == "full":
            cache[key] = entry.tokens
        elif mode == "exclude":
            cache[key] = 0
        else:
            source = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
            cache[key] = slice_text(entry.path, source, mode).sliced_tokens
    return cache[key]


def resolve_mode(entry, profile=None, default_mode: str | None = None) -> str:
    if profile is not None:
        m = profile.mode_for(entry.path)
        if m:
            return m
    if default_mode and entry.language in SLICABLE:
        return "strip-tests" if entry.is_test else default_mode
    return default_mode_for(entry)


def select_for_task(root, task: str, budget: int | None = None, profile=None):
    """Return (scan_result, selections dict path->mode, chosen paths, scores).

    Scores are TF-IDF floats (see module docstring), keyed by path.
    """
    result = scan(root, ignore_matcher=profile.is_ignored if profile and profile.path else None)
    keywords = keywords_from_task(task)
    if not keywords:
        raise ValueError("task has no usable keywords (need words of 3+ characters)")
    entries = [e for e in result.files if not e.is_lockfile]
    counters: dict[str, Counter] = {}
    doc_freq: Counter = Counter()
    for entry in entries:
        try:
            content = Path(entry.abspath).read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            content = ""
        counts = Counter(_WORD_RE.findall(content))
        counters[entry.path] = counts
        for word in counts:
            doc_freq[word] += 1
    n_docs = len(entries)
    weights = {kw: idf(doc_freq.get(kw, 0), n_docs) for kw in keywords}
    cache: dict = {}
    scored: list[tuple[float, int, object, str]] = []  # score, -tokens, entry, mode
    for entry in entries:
        path_text = entry.path.lower()
        counts = counters[entry.path]
        score = 0.0
        for kw in keywords:
            w = weights[kw]
            score += _PATH_BOOST * path_text.count(kw) * w
            score += min(counts.get(kw, 0), _TF_CAP) * w
        if score <= 0:
            continue
        mode = resolve_mode(entry, profile)
        scored.append((score, -entry.tokens, entry, mode))
    scored.sort(key=lambda t: (-t[0], t[1]))
    chosen: list[str] = []
    selections: dict[str, str] = {}
    spent = 0
    effective_budget = budget if budget is not None else (profile.budget_tokens if profile else None)
    for score, _nt, entry, mode in scored:
        stoks = _sliced_tokens(entry, mode, cache)
        if effective_budget is not None and chosen and spent + stoks > effective_budget:
            continue
        chosen.append(entry.path)
        selections[entry.path] = mode
        spent += stoks
    scores = {e.path: round(s, 4) for s, _n, e, _m in scored}
    return result, selections, chosen, scores


def select_for_diff(root, profile=None):
    """Selection = changed files + direct deps (imports and importers)."""
    result = scan(root, ignore_matcher=profile.is_ignored if profile and profile.path else None)
    graph = build_graph(result)
    rev = importers_of(graph)
    paths = {f.path for f in result.files}
    changed = [c for c in changed_files(root) if c in paths]
    chosen_set: set[str] = set(changed)
    for rel in changed:
        chosen_set.update(graph.get(rel, {}).get("imports", []))
        chosen_set.update(rev.get(rel, []))
    by_path = {f.path: f for f in result.files}
    selections = {rel: resolve_mode(by_path[rel], profile) for rel in sorted(chosen_set)}
    return result, selections, sorted(chosen_set), changed
