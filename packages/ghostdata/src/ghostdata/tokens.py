"""Token estimation, delegated to GhostSlice where available.

Same discipline as the other companions: prefer the real GhostSlice
estimator (installed package, then the sibling checkout), and fall back
to a documented local estimate with its own method string so counts are
never confused with Slice's calibrated ones.
"""
from __future__ import annotations

import importlib
import os
import sys

_METHOD = None
_ESTIMATE = None


def _load():
    global _METHOD, _ESTIMATE
    if _ESTIMATE is not None:
        return
    candidates = []
    env = os.environ.get("GHOSTDATA_GHOSTSLICE_SRC")
    if env:
        candidates.append(env)
    candidates.append(os.path.expanduser("~/workspace/ghostslice/src"))
    mod = None
    try:
        mod = importlib.import_module("ghostslice.tokens")
    except Exception:
        for base in candidates:
            if os.path.isdir(base) and base not in sys.path:
                sys.path.insert(0, base)
                try:
                    mod = importlib.import_module("ghostslice.tokens")
                    break
                except Exception:
                    continue
    if mod is not None and hasattr(mod, "estimate_tokens"):
        _ESTIMATE = mod.estimate_tokens
        _METHOD = getattr(mod, "METHOD", "ghostslice estimator")
    else:
        def _fallback(text, language=None):
            return max(1, -(-len(text) // 4)) if text else 0

        _ESTIMATE = _fallback
        _METHOD = "ghostdata fallback: ceil(chars/4), uncalibrated"


def estimate_tokens(text: str) -> int:
    """Estimate the token count of a text with the loaded estimator.

    Which estimator that is, GhostSlice's or the local fallback, is
    reported by method() and stamped wherever an estimate is used.
    """
    _load()
    try:
        return int(_ESTIMATE(text))
    except TypeError:
        return int(_ESTIMATE(text, None))


def method() -> str:
    """Return the method string of the active estimator, so every
    reported estimate can be attributed to the estimator that made
    it."""
    _load()
    return str(_METHOD)


class ChunkedEstimator:
    """Sums estimates over streamed chunks so a huge file is never held
    whole just to count it. Chunked sums are labelled approximate."""

    def __init__(self, chunk_chars: int = 65536):
        self._buf = []
        self._size = 0
        self._chunk_chars = chunk_chars
        self.total = 0

    def feed(self, text: str) -> None:
        if not text:
            return
        self._buf.append(text)
        self._size += len(text)
        if self._size >= self._chunk_chars:
            self.flush()

    def flush(self) -> None:
        if self._buf:
            self.total += estimate_tokens("".join(self._buf))
            self._buf = []
            self._size = 0
