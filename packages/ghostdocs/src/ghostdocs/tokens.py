"""Token estimation. Estimates only, never billed counts.

The estimator is deliberately simple and provider-neutral: roughly
four characters per token. Every output that uses these numbers
labels them as estimates, so they can be compared with each other
(corpus versus deduped export, document versus document) without
pretending to be an exact count from any one AI provider.
"""
from __future__ import annotations
import re

_WORD = re.compile(r"[a-z0-9]+")


def estimate_tokens(text: str) -> int:
    """Estimate the token count of *text* (about 4 characters per token).

    Returns 0 for empty text and at least 1 for any non-empty text.
    """
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def words(text: str) -> list[str]:
    """Return the lowercase alphanumeric words in *text*.

    Used for word-count similarity and TF-IDF selection; punctuation
    is dropped and case is folded.
    """
    return _WORD.findall(text.lower())
