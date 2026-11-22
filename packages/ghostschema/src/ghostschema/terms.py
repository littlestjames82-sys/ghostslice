"""Lexical task-term matching, the same class of heuristic as
`ghostslice task`: split the task into terms, split identifiers into
tokens (camelCase, snake_case, kebab, path segments), and score.
It will miss operations whose names share no words with the task;
explicit --select is the precise route. Scores are deterministic.
"""
from __future__ import annotations

import re

STOPWORDS = {
    "a", "an", "the", "to", "of", "for", "in", "on", "with", "and",
    "or", "is", "it", "that", "this", "from", "by", "at", "as", "be",
    "add", "get", "set", "use", "using", "make", "create", "new",
    "endpoint", "api", "task", "need", "needs", "want", "show",
}

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SPLIT = re.compile(r"[^A-Za-z0-9]+")


def ident_tokens(text) -> set:
    """'listStorePets' / 'GET /store/pets/{id}' -> {'list','store','pets','id'}"""
    out = set()
    if not text:
        return out
    for chunk in _SPLIT.split(str(text)):
        if not chunk:
            continue
        for piece in _CAMEL.sub(" ", chunk).split():
            tok = piece.lower()
            if tok:
                out.add(tok)
                if tok.endswith("s") and len(tok) > 3:
                    out.add(tok[:-1])
    return out


def task_terms(task: str):
    """Split task wording into match terms: lowercased alphanumeric
    tokens of length 2 or more, with stopwords removed, in first-seen
    order and de-duplicated. An empty result means the task wording
    carried no usable terms."""
    terms = []
    for tok in re.findall(r"[a-z0-9]+", (task or "").lower()):
        if len(tok) >= 2 and tok not in STOPWORDS and tok not in terms:
            terms.append(tok)
    return terms


def score_against(terms, weighted_haystacks) -> int:
    """weighted_haystacks: list of (weight, text). Exact token match
    scores the full weight; a prefix/substring match (len >= 3) half."""
    total = 0
    for term in terms:
        best = 0
        for weight, text in weighted_haystacks:
            tokens = ident_tokens(text)
            if term in tokens:
                best = max(best, weight)
            elif len(term) >= 3 and any(
                t.startswith(term) or term.startswith(t) for t in tokens if len(t) >= 3
            ):
                best = max(best, max(1, weight // 2))
        total += best
    return total
