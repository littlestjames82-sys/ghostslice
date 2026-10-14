"""Task-focused context selection.

Two selection strategies, both producing a set of project paths plus their
resolved slice modes (profile modes win, then exporter defaults):

- Task keywords (TF-IDF since v0.5, symbol + graph layers since
  v0.7): score each file by TF-IDF of the task keywords over the
  project's files (term frequency capped at 20 per keyword per file,
  inverse document frequency smoothed as ln((1 + N) / (1 + df)) + 1,
  N = files considered). Path hits keep their boost: they count 5x,
  weighted by the same idf. Content matching is whole-word
  (tokenised), unlike the pre-v0.5 substring counts, so a keyword
  buried in a common word no longer inflates a file. Scores are
  floats. Files are taken best-first until the token budget (of
  *sliced* tokens) would be exceeded; the single best file is always
  included even if it alone exceeds the budget, so a selection is
  never empty when there is any match. Deterministic: ties break by
  larger file, then scan order.
- Symbol matching (v0.7): a task keyword that names a symbol defined
  in a file earns a bonus on top of TF-IDF, because a definition is a
  stronger relevance signal than a body mention (and the body counter
  never sees it: `render_invoice` tokenises as one word, not as
  "invoice"). Symbols come from the file itself: Python via `ast`
  (functions, classes, methods, and module/class-level assignment
  targets — constants are definitions too; the slicer's fallback def
  lines when the file does not parse), other slicable languages via the slicer's
  own parser-lite signatures output (no second parser). A keyword
  equal to a whole symbol name earns SYMBOL_EXACT_BONUS; a keyword
  equal to one camelCase/snake_case part of a symbol (or whose own
  parts are all parts of the symbol) earns SYMBOL_PART_BONUS. Each
  keyword scores once per file, at its best tier, and the per-file
  symbol component is capped at SYMBOL_CAP so symbol stuffing cannot
  swamp the text signal.
- Graph boosting (v0.7): after the TF-IDF+symbol ranking is selected
  within the budget (the seeds), each remaining file one import hop
  from a seed (it imports a seed, or a seed imports it) earns a
  proximity boost of GRAPH_BOOST_FRACTION x the *strongest* adjacent
  seed's base score, capped at GRAPH_BOOST_CAP. Max, not sum: a hub
  imported by everything gets no more boost than a file imported by
  one seed, so popularity alone never drags a file in. Boosted files
  are then selected with whatever budget remains, best first; they
  never displace a seed and the budget is never exceeded by a boost
  (the best-file rule belongs to the seed stage only).
  `select_for_task_breakdown` exposes the per-file components
  (tfidf / symbol / graph / total); `select_for_task` keeps the
  legacy shape and reports the totals.
- Diff: files changed in the git working tree plus their direct
  dependencies (what they import, and what imports them).
"""
from __future__ import annotations

import ast
import math
import re
from collections import Counter
from pathlib import Path

from . import plugins as _plugins
from .exporter import SLICABLE, default_mode_for, is_slicable
from .graph import build_graph, changed_files, importers_of
from .scanner import scan
from .slicer import _py_fallback_defs, slice_source, slice_text
from .textio import read_text as _gs_read_text

_WORD_RE = re.compile(r"[a-z0-9_]+")
_TF_CAP = 20
_PATH_BOOST = 5

# Symbol-matching weights (v0.7). A definition is a stronger signal
# than a body mention: one part match (10.0) outweighs ~6 capped body
# mentions of a rare word (idf ~1.7), and an exact name match (15.0)
# outweighs ~9. The per-file cap keeps many-symbol files honest.
SYMBOL_EXACT_BONUS = 15.0
SYMBOL_PART_BONUS = 10.0
SYMBOL_CAP = 25.0

# Graph-boost weights (v0.7): a one-hop neighbour of a chosen seed
# earns a quarter of the strongest adjacent seed's base score, capped
# so association alone stays a weak signal next to text and symbols.
GRAPH_BOOST_FRACTION = 0.25
GRAPH_BOOST_CAP = 6.0

_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")
_DECL_KW_RE = re.compile(
    r"\b(?:function|func|fun|fn|def|class|interface|type|enum|struct|"
    r"protocol|trait|module|object|extension)\s+([A-Za-z_$][\w$]*)")
_GO_FUNC_RE = re.compile(r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*(?:\[(?:[^\[\]]|\[[^\[\]]*\])*\]\s*)?\(")
_METHOD_RE = re.compile(
    r"^\s*(?:@[\w.]+\s+)?(?:(?:public|private|protected|internal|open|"
    r"final|abstract|static|async|export|default|override|suspend|pub|"
    r"sealed|data)\s+)*([A-Za-z_$][\w$]*)\s*\(", re.M)
_VAR_RE = re.compile(r"\b(?:const|let|var|val)\s+([A-Za-z_$][\w$]*)\s*[:=]")
# C/C++ declaration lines in signatures output (v0.8): an optional
# return-type prefix ending in whitespace (or a pointer/reference),
# then the name and its parameter list. Constructors (no prefix, the
# name itself capitalised or the class name) are covered because the
# prefix group is optional. Only applied to c/cpp signatures output.
_C_SYM_RE = re.compile(
    r"^\s*[\w:<>,\*&\[\]~ ]*?"
    r"([A-Za-z_~]\w*|operator\s*\S+?)\s*\([^;{}]*\)"
    r"\s*(?:(?:const|noexcept|override|final|&|&&)\s*)*(?:\{|;)", re.M)
_PY_DEF_RE = re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_]\w*)", re.M)
_NOT_SYMBOLS = {
    "if", "for", "while", "switch", "catch", "return", "sizeof", "with",
    "when", "print", "elif", "else", "try", "except", "constructor",
}


def split_symbol_name(name: str) -> set[str]:
    """Split a symbol name into lowercase parts, including the whole name.

    `render_invoice` -> {render, invoice, render_invoice};
    `HTTPServer` -> {http, server, httpserver}.
    """
    parts: set[str] = set()
    for chunk in re.split(r"[_\-\s]+", name):
        if not chunk:
            continue
        for piece in _CAMEL_RE.findall(chunk):
            parts.add(piece.lower())
    parts.add(name.lower())
    return parts


def _target_names(target) -> list[str]:
    """Simple names bound by an assignment target (tuple/list/starred)."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in target.elts:
            out.extend(_target_names(elt))
        return out
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []  # Attribute/Subscript targets bind no new simple name


def _collect_assign_names(body, names: set[str]) -> None:
    for node in body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(_target_names(target))
        elif isinstance(node, ast.AnnAssign):
            names.update(_target_names(node.target))


def _py_symbols(source: str) -> set[str]:
    """Symbol names in Python source: ast defs/classes, slicer fallback.

    Definitions are defs/classes at any depth plus simple assignment
    targets at module level or in a class body (constants and class
    attributes are definitions; function-local variables are not).
    """
    try:
        tree = ast.parse(source)
    except Exception:
        # Unparseable: reuse the slicer's fallback (def/class lines only).
        return set(_PY_DEF_RE.findall(_py_fallback_defs(source)))
    names: set[str] = set()
    _collect_assign_names(tree.body, names)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        if isinstance(node, ast.ClassDef):
            _collect_assign_names(node.body, names)
    return names


def _lite_symbols(source: str, language: str, path: str) -> set[str]:
    """Symbol names from the slicer's own signatures output (parser-lite).

    No second parser: slice to signatures with the existing slicer and
    read declaration names out of what it kept.
    """
    try:
        sig = slice_source(source, language, "signatures", path=path)
    except Exception:
        return set()
    names: set[str] = set()
    names.update(_DECL_KW_RE.findall(sig))
    names.update(_GO_FUNC_RE.findall(sig))
    names.update(_METHOD_RE.findall(sig))
    names.update(_VAR_RE.findall(sig))
    if language in ("c", "cpp"):
        names.update(m.group(1) for m in _C_SYM_RE.finditer(sig))
    return {n for n in names if n not in _NOT_SYMBOLS and len(n) >= 2}


_YAML_KEY_SYM_RE = re.compile(r"^\s*-?\s*\"?([A-Za-z_][\w.\-]*)\"?\s*:", re.M)
_TOML_KEY_SYM_RE = re.compile(r"^\s*\"?([A-Za-z_][\w\-]*)\"?\s*=", re.M)
_TOML_TABLE_SYM_RE = re.compile(r"^\[\[?([A-Za-z0-9_.\-]+)\]\]?", re.M)


def _config_symbols(language: str, source: str) -> set[str]:
    """Symbol names for config files (v0.9): mapping/table keys.

    A task that names a config key (`database`, `api_token`) should
    earn the symbol bonus on the file that defines it, exactly like
    a function name in code. JSON keys come from a real parse (all
    depths, capped); YAML/TOML keys from line patterns. Never raises.
    """
    names: set[str] = set()
    try:
        if language == "json":
            import json as _json
            data = _json.loads(source)
            stack = [data]
            seen = 0
            while stack and seen < 500:
                node = stack.pop()
                if isinstance(node, dict):
                    for k, v in node.items():
                        names.add(str(k))
                        seen += 1
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(node, list):
                    stack.extend(v[:5])
        elif language == "yaml":
            names.update(_YAML_KEY_SYM_RE.findall(source))
        elif language == "toml":
            names.update(_TOML_KEY_SYM_RE.findall(source))
            for table in _TOML_TABLE_SYM_RE.findall(source):
                names.update(seg for seg in table.split(".") if seg)
    except Exception:
        pass
    return {n for n in names if n not in _NOT_SYMBOLS and len(n) >= 2}


def symbols_for_source(language: str, source: str, path: str = "") -> set[str]:
    """All symbol names defined in one file (empty when not applicable)."""
    if language == "python":
        return _py_symbols(source)
    if language in ("yaml", "toml", "json"):
        return _config_symbols(language, source)
    if _plugins.has_outline(language):
        # v0.23: a plugin language's symbols come from its outline —
        # the same names `ghostslice symbols` lists.
        from .symslice import outline_source
        syms = outline_source(source, language, path) or []
        return {s.name for s in syms} | {s.qualified for s in syms}
    if language in SLICABLE and language != "notebook":
        return _lite_symbols(source, language, path)
    return set()


def _keyword_parts(keywords: list[str]) -> set[str]:
    """All split parts of all keywords (each keyword itself included)."""
    parts: set[str] = set()
    for kw in keywords:
        parts.update(split_symbol_name(kw))
    return parts


def _keyword_parts_in(parts: set[str], lowered_text: str) -> bool:
    """True when any precomputed keyword part appears in the text."""
    return any(part in lowered_text for part in parts)


def _any_keyword_part_in(keywords: list[str], lowered_text: str) -> bool:
    """Gate for symbol extraction: could any keyword match a symbol here?

    A symbol bonus implies a textual trace in the source — the
    symbol's lowercased name (exact tier), one of its camelCase/
    snake_case parts (part tier), or every part of the keyword
    (subset tier) — and each of those strings is a part of the
    keyword's own split. If no keyword part appears in the text at
    all, the symbol component is provably 0 and extraction (which
    slices the file) can be skipped. False positives only cost the
    extraction; there are no false negatives.
    """
    return _keyword_parts_in(_keyword_parts(keywords), lowered_text)


def _symbol_component(keywords: list[str], symbols: set[str]) -> float:
    """Symbol bonus for one file: best tier per keyword, capped per file."""
    if not symbols or not keywords:
        return 0.0
    prepared = [(name.lower(), split_symbol_name(name)) for name in symbols]
    total = 0.0
    for kw in keywords:
        best = 0.0
        kw_parts: set[str] | None = None
        for low, parts in prepared:
            if kw == low:
                best = SYMBOL_EXACT_BONUS
                break
            if kw in parts:
                best = max(best, SYMBOL_PART_BONUS)
            elif "_" in kw:
                if kw_parts is None:
                    kw_parts = split_symbol_name(kw) - {kw}
                if kw_parts and kw_parts <= parts:
                    best = max(best, SYMBOL_PART_BONUS)
        total += best
        if total >= SYMBOL_CAP:
            return SYMBOL_CAP
    return min(total, SYMBOL_CAP)


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
            source = _gs_read_text(entry.abspath)
            cache[key] = slice_text(entry.path, source, mode).sliced_tokens
    return cache[key]


def resolve_mode(entry, profile=None, default_mode: str | None = None) -> str:
    if profile is not None:
        m = profile.mode_for(entry.path)
        if m:
            return m
    if default_mode and is_slicable(entry.language):
        return "strip-tests" if entry.is_test else default_mode
    return default_mode_for(entry)


def _select_for_task_impl(root, task: str, budget: int | None = None, profile=None):
    """Core of task selection; returns (result, selections, chosen, breakdown).

    breakdown maps path -> {"tfidf", "symbol", "graph", "total"} floats
    for every candidate (base score > 0, or graph-boosted). Selection is
    two-stage: seeds by base score (TF-IDF + symbol) within the budget,
    then one-hop graph neighbours of the seeds with the budget that
    remains. See the module docstring for the weights and the rules.
    """
    result = scan(root, ignore_matcher=profile.is_ignored if profile and profile.path else None)
    keywords = keywords_from_task(task)
    if not keywords:
        raise ValueError("task has no usable keywords (need words of 3+ characters)")
    entries = [e for e in result.files if not e.is_lockfile]
    raw: dict[str, str] = {}
    lowered: dict[str, str] = {}
    counters: dict[str, Counter] = {}
    doc_freq: Counter = Counter()
    for entry in entries:
        try:
            content = _gs_read_text(entry.abspath)
        except OSError:
            content = ""
        raw[entry.path] = content
        lowered[entry.path] = content.lower()
        counts = Counter(_WORD_RE.findall(lowered[entry.path]))
        counters[entry.path] = counts
        for word in counts:
            doc_freq[word] += 1
    n_docs = len(entries)
    weights = {kw: idf(doc_freq.get(kw, 0), n_docs) for kw in keywords}
    gate_parts = _keyword_parts(keywords)
    cache: dict = {}
    rows: list[dict] = []
    for idx, entry in enumerate(entries):
        path_text = entry.path.lower()
        counts = counters[entry.path]
        tfidf = 0.0
        for kw in keywords:
            w = weights[kw]
            tfidf += _PATH_BOOST * path_text.count(kw) * w
            tfidf += min(counts.get(kw, 0), _TF_CAP) * w
        symbol = 0.0
        if _keyword_parts_in(gate_parts, lowered[entry.path]):
            symbol = _symbol_component(
                keywords, symbols_for_source(entry.language, raw[entry.path], entry.path))
        rows.append({
            "idx": idx, "entry": entry, "mode": resolve_mode(entry, profile),
            "tfidf": tfidf, "symbol": symbol, "base": tfidf + symbol,
        })
    effective_budget = budget if budget is not None else (profile.budget_tokens if profile else None)
    chosen: list[str] = []
    selections: dict[str, str] = {}
    spent = 0
    breakdown: dict[str, dict] = {}

    def _take(row: dict, graph_boost: float) -> None:
        nonlocal spent
        stoks = _sliced_tokens(row["entry"], row["mode"], cache)
        chosen.append(row["entry"].path)
        selections[row["entry"].path] = row["mode"]
        spent += stoks
        breakdown[row["entry"].path] = {
            "tfidf": round(row["tfidf"], 4),
            "symbol": round(row["symbol"], 4),
            "graph": round(graph_boost, 4),
            "total": round(row["base"] + graph_boost, 4),
        }

    # Stage A: seeds, ranked by base score exactly as v0.5 ranked by
    # TF-IDF (score desc, larger file first, then scan order), with the
    # best-file-always-included rule.
    seeds = sorted((r for r in rows if r["base"] > 0),
                   key=lambda r: (-r["base"], -r["entry"].tokens, r["idx"]))
    seed_base: dict[str, float] = {}
    for row in seeds:
        stoks = _sliced_tokens(row["entry"], row["mode"], cache)
        if effective_budget is not None and chosen and spent + stoks > effective_budget:
            continue
        _take(row, 0.0)
        seed_base[row["entry"].path] = row["base"]
    # Every positive-base file is a reported candidate, chosen or not.
    for row in seeds:
        breakdown.setdefault(row["entry"].path, {
            "tfidf": round(row["tfidf"], 4),
            "symbol": round(row["symbol"], 4),
            "graph": 0.0,
            "total": round(row["base"], 4),
        })

    # Stage B: one-hop graph neighbours of the seeds earn a bounded
    # boost (max over adjacent seeds, never a sum) and are selected
    # with the remaining budget. Zero-sliced-token candidates (e.g. a
    # profile-excluded neighbour) are skipped: they would add a path
    # but no context.
    if seed_base:
        graph = build_graph(result)
        rev = importers_of(graph)
        chosen_set = set(chosen)
        candidates: list[tuple[dict, float]] = []
        for row in rows:
            path = row["entry"].path
            if path in chosen_set:
                continue
            adjacent = [seed_base[s] for s in graph.get(path, {}).get("imports", [])
                        if s in seed_base]
            adjacent += [seed_base[s] for s in rev.get(path, []) if s in seed_base]
            if not adjacent:
                continue
            boost = min(GRAPH_BOOST_CAP, GRAPH_BOOST_FRACTION * max(adjacent))
            if boost > 0:
                candidates.append((row, boost))
        candidates.sort(key=lambda rb: (-(rb[0]["base"] + rb[1]),
                                        -rb[0]["entry"].tokens, rb[0]["idx"]))
        for row, boost in candidates:
            path = row["entry"].path
            breakdown[path] = {
                "tfidf": round(row["tfidf"], 4),
                "symbol": round(row["symbol"], 4),
                "graph": round(boost, 4),
                "total": round(row["base"] + boost, 4),
            }
            stoks = _sliced_tokens(row["entry"], row["mode"], cache)
            if stoks <= 0:
                continue
            if effective_budget is not None and spent + stoks > effective_budget:
                continue
            _take(row, boost)
    return result, selections, chosen, breakdown


def select_for_task(root, task: str, budget: int | None = None, profile=None):
    """Return (scan_result, selections dict path->mode, chosen paths, scores).

    Scores are total floats (TF-IDF + symbol + graph since v0.7; see
    module docstring), keyed by path. Use select_for_task_breakdown
    for the per-component breakdown.
    """
    result, selections, chosen, breakdown = _select_for_task_impl(
        root, task, budget=budget, profile=profile)
    scores = {path: bd["total"] for path, bd in breakdown.items()}
    return result, selections, chosen, scores


def select_for_task_breakdown(root, task: str, budget: int | None = None, profile=None):
    """Like select_for_task, but the 4th value is the score breakdown.

    breakdown maps path -> {"tfidf", "symbol", "graph", "total"} for
    every candidate file (chosen or not).
    """
    return _select_for_task_impl(root, task, budget=budget, profile=profile)


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
