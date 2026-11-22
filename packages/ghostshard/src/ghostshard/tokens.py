"""Token estimation. All counts are ESTIMATES, labelled as such in
every artifact GhostShard writes. Method mirrors GhostSlice's raw
estimator: word-like runs and punctuation, long runs charged len/4."""
from __future__ import annotations
import math, re
_RUN = re.compile(r"[A-Za-z0-9_]+|[^\w\s]")

def estimate_tokens(text: str) -> int:
    """Estimate the token count of *text* (never an exact count).

    Word-like runs of up to 4 characters count as 1 token; longer
    runs count as ``ceil(len / 4)``. Empty or ``None`` input counts
    as 0. Every artifact that reports this value labels it with
    :data:`ESTIMATOR_NOTE`.
    """
    total = 0
    for m in _RUN.finditer(text or ""):
        s = m.group(0)
        total += 1 if len(s) <= 4 else math.ceil(len(s) / 4)
    return total

ESTIMATOR_NOTE = "token counts are estimates (GhostSlice-style raw estimator), not exact tokenizer counts"
