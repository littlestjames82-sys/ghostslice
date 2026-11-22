"""Token estimator.

Prefers GhostSlice's estimator when a GhostSlice checkout/install is
reachable (so a GhostPort bundle validates under `ghostslice check`,
which recomputes sliced tokens with that estimator). Falls back to a
documented chars/4 estimate. Either way figures are estimates only.
"""
from __future__ import annotations

import math
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
        if (candidate / "ghostslice" / "tokens.py").is_file() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            try:
                from ghostslice.tokens import METHOD as _m  # type: ignore
                from ghostslice.tokens import estimate_tokens as _e  # type: ignore
                _gs_estimate, _gs_method = _e, _m
            except Exception:
                pass
            break

if _gs_estimate is not None:
    METHOD = f"ghostslice estimator ({_gs_method}); estimates only"

    def estimate_tokens(text: str) -> int:
        """Estimate the token count of ``text`` (GhostSlice estimator)."""
        return int(_gs_estimate(text, "python"))
else:
    METHOD = "ghostport-estimate-v1: ceil(len(text)/4), estimates only"

    def estimate_tokens(text: str) -> int:
        """Estimate the token count of ``text`` as ceil(len(text) / 4)."""
        if not text:
            return 0
        return int(math.ceil(len(text) / 4))
