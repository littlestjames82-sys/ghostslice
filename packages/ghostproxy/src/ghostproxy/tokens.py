"""Token estimation, delegated to GhostSlice when importable.

GhostProxy must agree with GhostSlice exports, so when the ``ghostslice``
package (or a sibling checkout) is available we use its estimator and
stamp its METHOD_VERSION on every ledger record. When it is not, we fall
back to the same documented raw split GhostSlice v1 used (factor 1.0);
the fallback is recorded, never hidden, and all counts are estimates.
"""
from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]")


def _raw_estimate(text: str) -> int:
    if not text:
        return 0
    total = 0
    for match in _TOKEN_RE.findall(text):
        n = len(match)
        total += 1 if n <= 4 else int(math.ceil(n / 4))
    return total


def _load_ghostslice():
    """Return the imported ghostslice package or None (never raises)."""
    try:
        import ghostslice  # noqa: F401
        return ghostslice
    except Exception:
        pass
    candidates = []
    env = os.environ.get("GHOSTPROXY_GHOSTSLICE_SRC")
    if env:
        candidates.append(Path(env))
    # Sibling checkout layout: ~/workspace/ghostproxy/src/ghostproxy/
    # parents[3] is the workspace dir containing ghostslice/.
    try:
        candidates.append(Path(__file__).resolve().parents[3] / "ghostslice" / "src")
    except Exception:
        pass
    for cand in candidates:
        if (cand / "ghostslice" / "tokens.py").is_file():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            try:
                import ghostslice
                return ghostslice
            except Exception:
                continue
    return None


_GS = _load_ghostslice()
if _GS is not None:
    try:
        from ghostslice.tokens import METHOD_VERSION as _GS_VERSION
        from ghostslice.tokens import estimate_tokens as _gs_estimate
        ESTIMATOR = "ghostslice"
        ESTIMATOR_VERSION = int(_GS_VERSION)
    except Exception:  # pragma: no cover - partial GhostSlice install
        ESTIMATOR = "fallback-raw-v1"
        ESTIMATOR_VERSION = 1
        _gs_estimate = None
else:
    ESTIMATOR = "fallback-raw-v1"
    ESTIMATOR_VERSION = 1
    _gs_estimate = None


def ghostslice_available() -> bool:
    return _gs_estimate is not None


def estimate_tokens(text: str, language: str | None = None) -> int:
    """Estimated tokens for *text* (an estimate, never an exact count)."""
    if not text:
        return 0
    if _gs_estimate is not None:
        try:
            return int(_gs_estimate(text, language))
        except Exception:
            pass
    return _raw_estimate(text)
