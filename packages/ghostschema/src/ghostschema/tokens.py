"""Token estimator.

Prefers GhostSlice's calibrated estimator when a GhostSlice install or
sibling checkout is reachable (so GhostSchema figures are comparable
with GhostSlice bundle figures across the suite). Falls back to a
documented chars/4 estimate. Either way figures are estimates only.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

_gs_estimate = None
_gs_method = None


def _try_import():
    global _gs_estimate, _gs_method
    try:
        from ghostslice.tokens import METHOD as _m  # type: ignore
        from ghostslice.tokens import estimate_tokens as _e  # type: ignore
        _gs_estimate, _gs_method = _e, _m
        return True
    except Exception:
        return False


if not _try_import():
    _candidates = []
    _env = os.environ.get("GHOSTSCHEMA_GHOSTSLICE_SRC")
    if _env:
        _candidates.append(Path(_env))
    _candidates.append(Path(__file__).resolve().parents[3] / "ghostslice" / "src")
    _candidates.append(Path.home() / "workspace" / "ghostslice" / "src")
    for _candidate in _candidates:
        if (_candidate / "ghostslice" / "tokens.py").is_file():
            if str(_candidate) not in sys.path:
                sys.path.insert(0, str(_candidate))
            if _try_import():
                break

if _gs_estimate is not None:
    METHOD = f"ghostslice estimator ({_gs_method}); estimates only"

    def estimate_tokens(text: str) -> int:
        """Estimate tokens in ``text`` with GhostSlice's estimator.
        The result is an estimate, not an exact tokenizer count."""
        return int(_gs_estimate(text))
else:
    METHOD = "ghostschema-estimate-v1: ceil(len(text)/4), estimates only"

    def estimate_tokens(text: str) -> int:
        """Estimate tokens in ``text`` as ``ceil(len(text) / 4)``.
        Fallback used when no GhostSlice estimator is reachable;
        the result is an estimate only."""
        if not text:
            return 0
        return int(math.ceil(len(text) / 4))
