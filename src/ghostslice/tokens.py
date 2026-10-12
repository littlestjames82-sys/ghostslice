"""Token estimation.

Method (documented, deliberately simple and deterministic):
Token counts in GhostSlice are ESTIMATES, not exact model tokenizer counts.

We approximate a BPE-style tokenizer with a whitespace/punctuation split:

  tokens(text) = sum over each match of  r"[A-Za-z0-9_]+|[^\\w\\s]"
                 of  1 if len(match) <= 4 else ceil(len(match) / 4)

Rationale: short words and punctuation are roughly one token each in
common BPE tokenizers, long identifiers/words split into roughly one
token per 4 characters, and whitespace/indentation is mostly merged
into neighbouring tokens (so it is not counted separately).
This is close to the widely used "about 4 characters per token"
rule for English/code, while penalising long identifiers less
crudely than a flat chars/4 over the raw file.

No third-party tokenizer is used (zero-dependency rule). Treat every
number GhostSlice prints as "estimated tokens".
"""
from __future__ import annotations

import math
import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]")

METHOD = (
    "estimate: BPE-like split (word/punct chunks, 1 token per chunk up to "
    "4 chars, then 1 per 4 chars); not an exact model tokenizer count"
)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    total = 0
    for match in _TOKEN_RE.findall(text):
        n = len(match)
        if n <= 4:
            total += 1
        else:
            total += int(math.ceil(n / 4))
    return total
