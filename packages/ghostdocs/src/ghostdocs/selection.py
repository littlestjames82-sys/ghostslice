"""TF-IDF task selection over sections. No embeddings, no model calls."""
from __future__ import annotations

import math
from collections import Counter

from .scan import Corpus
from .sections import Section
from .tokens import words


def tfidf_scores(corpus: Corpus, task: str) -> dict[tuple[str, int], float]:
    """Score every section in *corpus* against the *task* text (TF-IDF).

    Returns a mapping of ``(doc_path, section_index)`` to score;
    sections sharing no words with the task score 0.
    """
    sections: list[Section] = [s for d in corpus.docs for s in d.sections]
    if not sections:
        return {}
    doc_freq: Counter = Counter()
    term_counts: list[Counter] = []
    for s in sections:
        c = Counter(words(s.text))
        term_counts.append(c)
        for term in c:
            doc_freq[term] += 1
    n = len(sections)
    query = Counter(words(task))
    scores: dict[tuple[str, int], float] = {}
    for s, counts in zip(sections, term_counts):
        total = sum(counts.values()) or 1
        score = 0.0
        for term, qn in query.items():
            if counts.get(term):
                idf = math.log((1 + n) / (1 + doc_freq[term])) + 1.0
                score += qn * (counts[term] / total) * idf
        scores[(s.doc_path, s.index)] = score
    return scores


def select_sections(corpus: Corpus, task: str | None,
                    docs: list) -> tuple[list[Section], dict]:
    """Sections from the given docs, optionally narrowed to a task.

    Without a task, every section of *docs* is returned. With a task,
    only sections scoring above 0 are kept; if none score above 0, the
    five best-scoring sections are returned as a fallback so an export
    is never silently empty. Also returns the score mapping.
    """
    all_sections = [s for d in docs for s in d.sections]
    if not task:
        return all_sections, {}
    scores = tfidf_scores(corpus, task)
    kept = [s for s in all_sections if scores.get((s.doc_path, s.index), 0) > 0]
    if not kept and all_sections:
        kept = sorted(all_sections,
                      key=lambda s: -scores.get((s.doc_path, s.index), 0))[:5]
    return kept, scores
