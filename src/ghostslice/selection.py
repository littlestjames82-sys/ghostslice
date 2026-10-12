"""Task-focused context selection.

Two selection strategies, both producing a set of project paths plus their
resolved slice modes (profile modes win, then exporter defaults):

- Task keywords: score each file by keyword hits (path hits weigh more
  than content hits), take files best-first until the token budget (of
  *sliced* tokens) would be exceeded. The single best file is always
  included even if it alone exceeds the budget, so a selection is never
  empty when there is any match.
- Diff: files changed in the git working tree plus their direct
  dependencies (what they import, and what imports them).
"""
from __future__ import annotations

import re
from pathlib import Path

from .exporter import default_mode_for
from .graph import build_graph, changed_files, importers_of
from .scanner import scan
from .slicer import slice_text

_WORD_RE = re.compile(r"[a-z0-9_]+")


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
    if default_mode and entry.language in ("python", "typescript", "javascript", "go", "rust", "java", "csharp"):
        return "strip-tests" if entry.is_test else default_mode
    return default_mode_for(entry)


def select_for_task(root, task: str, budget: int | None = None, profile=None):
    """Return (scan_result, selections dict path->mode, chosen paths, scores)."""
    result = scan(root, ignore_matcher=profile.is_ignored if profile and profile.path else None)
    keywords = keywords_from_task(task)
    if not keywords:
        raise ValueError("task has no usable keywords (need words of 3+ characters)")
    cache: dict = {}
    scored: list[tuple[int, int, object, str]] = []  # score, -tokens, entry, mode
    for entry in result.files:
        if entry.is_lockfile:
            continue
        path_text = entry.path.lower()
        try:
            content = Path(entry.abspath).read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            content = ""
        score = 0
        for kw in keywords:
            score += 5 * path_text.count(kw)
            score += min(content.count(kw), 20)
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
    scores = {e.path: s for s, _n, e, _m in scored}
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
