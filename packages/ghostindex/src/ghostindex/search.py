"""Search: FTS5 bm25 ranking in, bounded sliced excerpts out.

A hit never returns a whole file. For each matching file the excerpt
builder finds the lines that contain a query term, grows a window of
+/- context lines around each, merges overlapping windows, and caps
the result by estimated tokens (per hit and across the result set),
using the same estimator as the index itself. Files matched only by
name (the term is in the path, not the body) return a short head
excerpt and are labelled as name matches.

Caps are never silent: search() returns a SearchResult that carries
the exact number of files that matched before capping (an FTS5
COUNT over the same query) and the name of every limit that cut the
result, so a capped answer can never present itself as complete.

Query syntax (parsed by parse_query, the one parser every part of
this module uses, so the FTS query, the total count, and the excerpt
marker can never disagree about what a term means):

- plain terms: AND by default, OR with any_terms (--any)
- ``term*``: prefix term
- ``"two words"``: phrase; the words must occur in order, adjacent
  as FTS tokens (a file holding both words apart does not match)
- ``-term``, ``-term*``, ``-"two words"``: exclusion; a file that
  contains the excluded term or phrase anywhere (body or file name,
  the same places a positive term can match) is dropped from the
  result, however well it matches the positive terms

A query with exclusions but no positive term is an error: there is
nothing to rank. Exclusions only ever subtract rows the index
already holds; they cannot make an ignored, binary, or outside-root
file searchable.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from . import tokens

DEFAULT_LIMIT = 10
DEFAULT_CONTEXT = 3
DEFAULT_PER_HIT_TOKENS = 200
DEFAULT_TOTAL_TOKENS = 2000

# Visible marker placed where a single over-long line was cut inside
# the line (see _truncate_line). The kept text on both sides of a
# marker is verbatim file text; the marker itself is not.
TRUNCATION_MARKER = "..."


@dataclass
class Window:
    """One excerpt window: a run of lines around one or more match
    lines (overlapping windows are merged before this is built)."""

    start_line: int  # 1-based, inclusive
    end_line: int    # 1-based, inclusive
    lines: list[tuple[int, str, bool]] = field(default_factory=list)  # (lineno, text, is_match)

    def text(self) -> str:
        """The window's lines joined as plain text (no line numbers
        or match markers; those are presentation, added by the CLI)."""
        return "\n".join(text for _n, text, _m in self.lines)

    def as_dict(self) -> dict:
        """The window as it appears inside a ``search --json`` hit."""
        return {
            "start_line": self.start_line,
            "end_line": self.end_line,
            "text": self.text(),
            "match_lines": [n for n, _t, m in self.lines if m],
        }


@dataclass
class Hit:
    """One matching file: where it lives, its bm25 ``rank``, the
    excerpt windows to show, and token estimates for the excerpt
    versus the whole file. A hit never carries the whole file."""

    root: str
    rel: str
    language: str
    rank: float
    file_tokens: int
    excerpt_tokens: int
    name_only: bool
    windows: list[Window] = field(default_factory=list)
    # True when the per-hit token budget cut this excerpt short
    # (windows dropped, lines trimmed, or a line cut within itself).
    excerpt_truncated: bool = False

    def as_dict(self) -> dict:
        """The hit as it appears in ``search --json`` output."""
        return {
            "root": self.root,
            "rel": self.rel,
            "language": self.language,
            "rank": round(self.rank, 4),
            "file_tokens_est": self.file_tokens,
            "excerpt_tokens_est": self.excerpt_tokens,
            "name_only": self.name_only,
            "excerpt_truncated": self.excerpt_truncated,
            "windows": [w.as_dict() for w in self.windows],
        }


class SearchResult(list):
    """The hits of one search, plus the accounting of what was cut.

    Behaves exactly like the list of Hit it contains (iteration,
    len(), indexing) and additionally carries:

    - total_matches: files matching the query before any capping,
      an exact FTS5 COUNT over the same MATCH and root filter.
    - capped_by: every limit that cut this result, drawn from
      "limit" (the hit limit), "total_tokens" (the result-set
      excerpt budget) and "per_hit_tokens" (at least one shown
      excerpt was shortened by the per-hit budget). Empty when
      no limit bound.
    - limits: the effective limits the search ran with.
    """

    def __init__(self, hits=(), total_matches: int = 0,
                 capped_by: list[str] | None = None,
                 limits: dict | None = None):
        super().__init__(hits)
        self.total_matches = total_matches
        self.capped_by = list(capped_by or [])
        self.limits = dict(limits or {})

    @property
    def capped(self) -> bool:
        """True when any limit cut this result (see ``capped_by``)."""
        return bool(self.capped_by)

    def summary_dict(self) -> dict:
        """The cap accounting printed alongside ``search --json``
        hits: total matches, shown count, and what bound."""
        return {
            "total_matches": self.total_matches,
            "shown": len(self),
            "capped": self.capped,
            "capped_by": list(self.capped_by),
            "limits": dict(self.limits),
        }


@dataclass
class ParsedTerm:
    text: str       # term text, or the phrase text for a quoted unit
    phrase: bool = False
    prefix: bool = False
    negated: bool = False


def parse_query(query: str) -> list[ParsedTerm]:
    """Split a user query into its units (see the module docstring).

    A small hand scanner rather than str.split, so a quoted phrase
    survives as one unit and a leading ``-`` binds to the unit after
    it (a phrase included). An unmatched quote treats the rest of
    the query as the phrase. Quotes inside a plain term are dropped,
    as before; they carry no meaning there.
    """
    units: list[ParsedTerm] = []
    i, n = 0, len(query)
    while i < n:
        while i < n and query[i].isspace():
            i += 1
        if i >= n:
            break
        negated = False
        if query[i] == "-" and i + 1 < n and not query[i + 1].isspace():
            negated = True
            i += 1
        if i < n and query[i] == '"':
            end = query.find('"', i + 1)
            if end == -1:
                text, i = query[i + 1:], n
            else:
                text, i = query[i + 1:end], end + 1
            prefix = i < n and query[i] == "*"
            if prefix:
                i += 1
            text = " ".join(text.split())
            if text:
                units.append(ParsedTerm(text, phrase=True,
                                        prefix=prefix, negated=negated))
        else:
            start = i
            while i < n and not query[i].isspace():
                i += 1
            token = query[start:i].replace('"', "")
            prefix = token.endswith("*")
            token = token.rstrip("*")
            if token:
                units.append(ParsedTerm(token, prefix=prefix,
                                        negated=negated))
    return units


def _fts_unit(unit: ParsedTerm) -> str:
    # For a phrase, a trailing * prefixes the phrase's last token;
    # FTS5 accepts that form ("two word"* matches "two words").
    clean = unit.text.replace('"', '""')
    return f'"{clean}"' + ("*" if unit.prefix else "")


def build_match_query(query: str, any_terms: bool = False) -> str:
    """Turn the positive units of a query into a safe FTS5 MATCH
    expression. Every unit is quoted, so user input cannot inject
    FTS operators. Raises ValueError when there is no positive unit.
    """
    parts = [_fts_unit(u) for u in parse_query(query) if not u.negated]
    if not parts:
        raise ValueError(
            "empty search query: exclusions (-term) need at least "
            "one positive term to search for")
    return (" OR " if any_terms else " AND ").join(parts)


def build_exclusion_query(query: str) -> str | None:
    """The excluded units as one FTS5 MATCH expression, or None.

    Units are OR-joined: containing any one of them is enough to
    drop a file. Callers apply it as a NOT IN subquery over docs, so
    the exclusions bind the count query and the hit query alike.
    """
    parts = [_fts_unit(u) for u in parse_query(query) if u.negated]
    if not parts:
        return None
    return " OR ".join(parts)


def _phrase_words_match(wanted: list[str], words: list[str],
                        last_prefix: bool = False) -> bool:
    """True when `wanted` occurs as a contiguous run in `words`;
    with last_prefix, the run's last token only has to start with
    the wanted word (the FTS "phrase"* condition)."""
    if not wanted or len(words) < len(wanted):
        return False
    span = len(wanted)
    for i in range(len(words) - span + 1):
        run = words[i:i + span]
        if run == wanted:
            return True
        if last_prefix and run[:-1] == wanted[:-1] \
                and run[-1].startswith(wanted[-1]):
            return True
    return False


def _phrase_in_line(phrase: str, line: str,
                    last_prefix: bool = False) -> bool:
    """True when a phrase's words occur in order, adjacent as tokens
    in the line (the FTS phrase condition, at line granularity), or
    when the literal phrase text appears in the line."""
    if not last_prefix and phrase in line.lower():
        return True
    return _phrase_words_match(_words(phrase), _words(line), last_prefix)


def _term_predicates(query: str) -> list:
    """One predicate per POSITIVE unit, mirroring the FTS5 side.
    Excluded units never mark a line as a match: they remove whole
    files in the SQL, and an excerpt built from a surviving file
    shows only what it was actually found for. Plain terms match
    as substrings of the lowered line, trailing-* terms match when
    any word in the line starts with the term, and phrases match
    token-adjacent spans."""
    preds = []
    for unit in parse_query(query):
        if unit.negated:
            continue
        clean = unit.text.lower()
        if unit.phrase:
            preds.append(lambda line, t=clean, p=unit.prefix:
                         _phrase_in_line(t, line, p))
        elif unit.prefix:
            preds.append(lambda line, t=clean: any(
                word.startswith(t) for word in _words(line)))
        else:
            preds.append(lambda line, t=clean: t in line.lower())
    return preds


def _words(line: str) -> list[str]:
    """The word tokens of a line, as the prefix matcher sees them."""
    import re

    return re.findall(r"[a-z0-9_]+", line.lower())


def _match_lines(body: str, query: str) -> list[int]:
    """0-based indexes of the lines in ``body`` matching any term."""
    preds = _term_predicates(query)
    if not preds:
        return []
    lines = body.splitlines()
    return [i for i, line in enumerate(lines) if any(p(line) for p in preds)]


def _windows_for(body: str, match_idx: list[int], context: int) -> list[tuple[int, int]]:
    """Merge match line indexes into (start, end) 0-based inclusive
    spans, each grown by ``context`` lines on both sides."""
    lines = body.splitlines()
    spans: list[list[int]] = []
    for i in match_idx:
        start = max(0, i - context)
        end = min(len(lines) - 1, i + context)
        if spans and start <= spans[-1][1] + 1:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    return [(s, e) for s, e in spans]


def _anchor_for(line: str, query: str) -> tuple[int, int] | None:
    """Earliest (position, length) at which a query term matches a line.

    Mirrors _term_predicates: plain terms match as substrings of the
    lowered line; a trailing-* term matches the first word it prefixes;
    a phrase matches its literal text or its token-adjacent span.
    Excluded units never anchor. Returns None when no positive term
    matches (context lines, name-only heads).
    """
    lowered = line.lower()
    best: tuple[int, int] | None = None
    for unit in parse_query(query):
        if unit.negated:
            continue
        clean = unit.text.lower()
        cand: tuple[int, int] | None = None
        if unit.phrase:
            idx = lowered.find(clean)
            if idx >= 0:
                cand = (idx, len(clean))
            else:
                # Token-adjacent but not a literal substring (extra
                # punctuation or spacing in the line): anchor on the
                # first phrase word and span through the last one.
                wanted = _words(clean)
                spans = [(m.start(), m.end()) for m in
                         re.finditer(r"[a-z0-9_]+", lowered)]
                words = [lowered[s:e] for s, e in spans]
                for j in range(len(words) - len(wanted) + 1):
                    if wanted and _phrase_words_match(
                            wanted, words[j:j + len(wanted)], unit.prefix):
                        cand = (spans[j][0],
                                spans[j + len(wanted) - 1][1] - spans[j][0])
                        break
        elif unit.prefix:
            for m in re.finditer(r"[a-z0-9_]+", lowered):
                if m.group(0).startswith(clean):
                    cand = (m.start(), len(m.group(0)))
                    break
        else:
            idx = lowered.find(clean)
            if idx >= 0:
                cand = (idx, len(clean))
        if cand is not None and (best is None or cand[0] < best[0]):
            best = cand
    return best


def _slice_bounds(length: int, pos: int, span: int, keep: int) -> tuple[int, int]:
    """[start, end) of `keep` chars inside a line of `length` chars,
    positioned around [pos, pos+span) and clamped to the line. The
    anchored span is always fully inside the slice when keep >= span.
    """
    keep = min(keep, length)
    start = pos - (keep - span) // 2
    start = max(0, min(start, pos))
    start = min(start, length - keep)
    start = max(start, pos + span - keep)
    return start, start + keep


def _truncate_line(text: str, query: str, budget_tokens: int,
                   language: str | None) -> str:
    """Truncate one over-budget line within the line, around the match.

    The kept slice stays anchored on the matched term (the full term
    is always present when the line matches), and each cut end is
    marked with TRUNCATION_MARKER so the excerpt never pretends to be
    the whole line. The result is the largest slice whose estimated
    tokens fit the budget; if even the bare term plus markers exceeds
    a tiny budget, that minimal anchored slice is returned anyway (a
    floor, like the line-level trim keeping at least the match line).
    A line with no query anchor is cut from the start.
    """
    if tokens.estimate_tokens(text, language) <= budget_tokens:
        return text
    anchor = _anchor_for(text, query)
    pos, span = anchor if anchor is not None else (0, 0)

    def render(keep: int) -> str:
        start, end = _slice_bounds(len(text), pos, span, keep)
        piece = text[start:end]
        if start > 0:
            piece = TRUNCATION_MARKER + " " + piece
        if end < len(text):
            piece = piece + " " + TRUNCATION_MARKER
        return piece

    lo, hi = min(span, len(text)), len(text)
    if tokens.estimate_tokens(render(lo), language) > budget_tokens:
        return render(lo)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tokens.estimate_tokens(render(mid), language) <= budget_tokens:
            lo = mid
        else:
            hi = mid - 1
    return render(lo)


def _cap_lines(wlines: list[tuple[int, str, bool]], budget_tokens: int,
               query: str, language: str | None) -> list[tuple[int, str, bool]]:
    """Enforce a token budget on window lines, truncating within a
    line when whole lines alone cannot fit (one very long line).

    Lines are kept whole while they fit. A line that does not fit is
    truncated within the line around its match position, except a
    context line ahead of a not-yet-kept match line, which is skipped
    so the remaining budget is spent on the match itself.
    """
    joined = "\n".join(text for _n, text, _m in wlines)
    if tokens.estimate_tokens(joined, language) <= budget_tokens:
        return wlines
    out: list[tuple[int, str, bool]] = []
    used = 0
    for idx, (n, text, is_match) in enumerate(wlines):
        remaining = budget_tokens - used
        line_est = tokens.estimate_tokens(text, language)
        if line_est <= remaining:
            out.append((n, text, is_match))
            used += line_est
            continue
        later_match = any(m for _n2, _t2, m in wlines[idx + 1:])
        if not is_match and later_match:
            continue
        if is_match or remaining > 0:
            piece = _truncate_line(text, query, max(remaining, 0), language)
            if piece:
                out.append((n, piece, is_match))
                used += tokens.estimate_tokens(piece, language)
        if not later_match:
            break
    return out


def _build_hit(row: sqlite3.Row, body: str, query: str, context: int,
               per_hit_tokens: int) -> Hit:
    lines = body.splitlines()
    match_idx = _match_lines(body, query)
    language = row["language"]
    windows: list[Window] = []
    truncated = False

    if match_idx:
        spans = _windows_for(body, match_idx, context)
        match_set = set(match_idx)
        used = 0
        for start, end in spans:
            wlines = [
                (n + 1, lines[n], n in match_set) for n in range(start, end + 1)
            ]
            window = Window(start + 1, end + 1, wlines)
            est = tokens.estimate_tokens(window.text(), language)
            if windows and used + est > per_hit_tokens:
                # Further windows exist but the per-hit budget is
                # spent: the excerpt is capped, and it must say so.
                truncated = True
                break
            if not windows and est > per_hit_tokens:
                # A single window over budget: trim trailing lines
                # until it fits, keeping at least the match line.
                trimmed: list[tuple[int, str, bool]] = []
                running = 0
                for item in wlines:
                    running += tokens.estimate_tokens(item[1], language)
                    trimmed.append(item)
                    if running >= per_hit_tokens and any(m for _n, _t, m in trimmed):
                        break
                if len(trimmed) < len(wlines):
                    truncated = True
                window = Window(start + 1, trimmed[-1][0], trimmed)
                est = tokens.estimate_tokens(window.text(), language)
            if est > per_hit_tokens:
                # Still over budget after line-granular trimming: a
                # single line (or the lines left) is itself too long.
                # Truncate within the line, around the match.
                capped = _cap_lines(window.lines, per_hit_tokens, query,
                                    language)
                if capped:
                    if capped != window.lines:
                        truncated = True
                    window = Window(window.start_line, capped[-1][0], capped)
                    est = tokens.estimate_tokens(window.text(), language)
            windows.append(window)
            used += est
        excerpt_tokens = used
        name_only = False
    else:
        # Name-only match: show the head of the file, bounded.
        head: list[tuple[int, str, bool]] = []
        running = 0
        head_window = lines[:50]
        for n, line in enumerate(head_window):
            running += tokens.estimate_tokens(line, language)
            head.append((n + 1, line, False))
            if running >= per_hit_tokens:
                if n < len(head_window) - 1:
                    # The token budget stopped the head before its
                    # preview window was done: the cap cut this excerpt.
                    truncated = True
                break
        if head:
            head_est = tokens.estimate_tokens(
                "\n".join(t for _n, t, _m in head), language)
            if head_est > per_hit_tokens:
                # Same one-long-line case as the match branch: the
                # head line alone busts the cap, so cut within it.
                capped = _cap_lines(head, per_hit_tokens, query, language)
                if capped:
                    if capped != head:
                        truncated = True
                    head = capped
            windows.append(Window(1, head[-1][0], head))
        excerpt_tokens = tokens.estimate_tokens(
            "\n".join(t for _n, t, _m in head), language) if head else 0
        name_only = True

    return Hit(
        root=row["root"],
        rel=row["rel"],
        language=language,
        rank=row["rank"],
        file_tokens=row["tokens"],
        excerpt_tokens=excerpt_tokens,
        name_only=name_only,
        windows=windows,
        excerpt_truncated=truncated,
    )


def search(
    conn: sqlite3.Connection,
    query: str,
    root: str | None = None,
    limit: int = DEFAULT_LIMIT,
    context: int = DEFAULT_CONTEXT,
    any_terms: bool = False,
    per_hit_tokens: int = DEFAULT_PER_HIT_TOKENS,
    total_tokens: int = DEFAULT_TOTAL_TOKENS,
) -> SearchResult:
    """Run one search and return a :class:`SearchResult`.

    ``root`` restricts the search to one indexed root. Hits are
    ranked by bm25 and capped three ways: at most ``limit`` hits,
    at most ``total_tokens`` estimated excerpt tokens across the
    result, and at most ``per_hit_tokens`` per hit. The result
    carries the exact pre-cap match count and the name of every
    cap that bound, so a capped answer never looks complete.
    Raises ``ValueError`` for an empty query.
    """
    # Reject nonsense limits instead of silently misbehaving on
    # them: a limit of 0 used to report "no matches" for files that
    # do match, a negative limit fell through to sqlite's "no LIMIT"
    # semantics, and a negative context produced empty excerpts
    # labelled with inverted line ranges (L2-L0).
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if context < 0:
        raise ValueError("context must be at least 0")
    if per_hit_tokens < 1:
        raise ValueError("per_hit_tokens must be at least 1")
    if total_tokens < 1:
        raise ValueError("total_tokens must be at least 1")
    match = build_match_query(query, any_terms=any_terms)
    exclusion = build_exclusion_query(query)
    # Exclusions subtract whole files through a NOT IN subquery over
    # the same docs table, so an excluded term in the body or in the
    # file name drops the file exactly as a positive term there
    # would have matched it. The same clause binds the count query
    # and the hit query, so total_matches is the post-exclusion
    # total, never the pre-exclusion one.
    excl_sql = ""
    if exclusion is not None:
        excl_sql = (" AND docs.rowid NOT IN"
                    " (SELECT rowid FROM docs WHERE docs MATCH ?)")
    # The exact number of matching files, counted over the same MATCH
    # and root filter as the hit query below. FTS5 can always count
    # its matches, so a capped result never has to guess its total.
    count_sql = "SELECT COUNT(*) AS n FROM docs WHERE docs MATCH ?"
    count_params: list = [match]
    if root is not None:
        count_sql += " AND docs.root = ?"
        count_params.append(root)
    count_sql += excl_sql
    if exclusion is not None:
        count_params.append(exclusion)
    total_matches = conn.execute(count_sql, count_params).fetchone()["n"]

    sql = (
        "SELECT files.root, files.rel, files.language, files.tokens,"
        " bm25(docs) AS rank, docs.body AS body"
        " FROM docs JOIN files ON files.id = docs.rowid"
        " WHERE docs MATCH ?"
    )
    params: list = [match]
    if root is not None:
        sql += " AND docs.root = ?"
        params.append(root)
    sql += excl_sql
    if exclusion is not None:
        params.append(exclusion)
    sql += " ORDER BY rank LIMIT ?"
    params.append(max(limit * 3, limit))  # headroom for budget drops

    hits: list[Hit] = []
    spent = 0
    budget_skipped = False
    for row in conn.execute(sql, params):
        hit = _build_hit(row, row["body"], query, context, per_hit_tokens)
        if hits and spent + hit.excerpt_tokens > total_tokens:
            budget_skipped = True
            continue
        hits.append(hit)
        spent += hit.excerpt_tokens
        if len(hits) >= limit:
            break

    capped_by: list[str] = []
    if total_matches > len(hits) and len(hits) >= limit:
        capped_by.append("limit")
    if budget_skipped:
        capped_by.append("total_tokens")
    if any(hit.excerpt_truncated for hit in hits):
        capped_by.append("per_hit_tokens")
    return SearchResult(
        hits,
        total_matches=total_matches,
        capped_by=capped_by,
        limits={
            "limit": limit,
            "total_tokens": total_tokens,
            "per_hit_tokens": per_hit_tokens,
        },
    )
