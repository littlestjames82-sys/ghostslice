"""Token estimation.

Prefers GhostSlice's calibrated estimator (method v2) when a
GhostSlice install or sibling checkout is reachable, so GhostLogs
figures read the same way as GhostSlice figures across the suite.
Falls back to a documented local estimator when GhostSlice is not
reachable. Either way the counts are ESTIMATES, not vendor tokenizer
counts, and the manifest stamps which method produced them.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

_gs_estimate = None
_gs_method = None
try:
    from ghostslice.tokens import METHOD as _m  # type: ignore
    from ghostslice.tokens import estimate_tokens as _e  # type: ignore
    _gs_estimate, _gs_method = _e, _m
except Exception:
    for candidate in (Path(__file__).resolve().parents[3] / "ghostslice" / "src",
                      Path.home() / "workspace" / "ghostslice" / "src"):
        if (candidate / "ghostslice" / "tokens.py").is_file() \
                and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            try:
                from ghostslice.tokens import METHOD as _m  # type: ignore
                from ghostslice.tokens import estimate_tokens as _e  # type: ignore
                _gs_estimate, _gs_method = _e, _m
            except Exception:
                _gs_estimate = _gs_method = None
            break

# Fallback: the raw BPE-like split GhostSlice documents as its v1
# estimator (a word/punctuation split, 1 token per short piece,
# ceil(len/4) per long piece), uncalibrated. Documented here so the
# fallback figures are reproducible, and labelled as a fallback in
# every manifest that uses them.
_SPLIT_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]")


def _fallback_estimate(text: str) -> int:
    """Uncalibrated fallback estimate, used only when GhostSlice is
    not reachable. Splits on word/punctuation boundaries: one token
    per short piece, ceil(len/4) per long piece."""
    if not text:
        return 0
    total = 0
    for match in _SPLIT_RE.findall(text):
        total += 1 if len(match) <= 4 else math.ceil(len(match) / 4)
    return total


if _gs_estimate is not None:
    METHOD = _gs_method
    SOURCE = "ghostslice"

    def _estimate_impl(text: str) -> int:
        if not text:
            return 0
        return _gs_estimate(text)
else:
    METHOD = "ghostlogs-fallback-raw-split-v1 (uncalibrated BPE-like split)"
    SOURCE = "fallback"

    def _estimate_impl(text: str) -> int:
        return _fallback_estimate(text)


from functools import lru_cache as _lru_cache


@_lru_cache(maxsize=65536)
def _estimate_cached(text: str) -> int:
    return _estimate_impl(text)


def estimate_tokens(text: str) -> int:
    """Estimate tokens for one line. Memoised on the exact line
    text: real logs repeat whole lines heavily, and the estimate of
    an identical line is identical, so the cache never changes a
    figure, only the time taken to produce it."""
    if not text:
        return 0
    return _estimate_cached(text)
