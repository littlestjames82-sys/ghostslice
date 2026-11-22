"""Token estimation. Counts are ESTIMATES (BPE-like split, prose factor
0.85, aligned in method with GhostSlice's calibrated estimator for
prose). They are not exact model tokenizer counts."""
from __future__ import annotations
import math, re

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]")
METHOD = "estimates (BPE-like split, prose-calibrated, not exact tokenizer counts)"
METHOD_VERSION = 2
PROSE_FACTOR = 0.85

def estimate(text: str) -> int:
    """Estimated token count for *text* (see METHOD; an estimate, not
    an exact tokenizer count). Empty text estimates to 0."""
    if not text:
        return 0
    raw = 0
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        raw += 1 if len(tok) <= 4 else math.ceil(len(tok) / 4)
    return max(1, round(raw * PROSE_FACTOR)) if raw else 0

def sha256_text(text: str) -> str:
    """Hex sha256 of *text* as UTF-8, the digest recorded in manifests."""
    import hashlib
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
