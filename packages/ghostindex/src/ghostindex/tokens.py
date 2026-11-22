"""Token estimation for GhostIndex.

Index and search results carry token figures so a reader can see what
an excerpt costs versus pulling the whole file. Those figures come
from GhostSlice's calibrated estimator whenever a GhostSlice install
or checkout is reachable (import, ``GHOSTINDEX_GHOSTSLICE_SRC`` /
``GHOSTSLICE_SRC``, or a sibling ``ghostslice/src`` checkout), so the
numbers agree with what GhostSlice itself would print for the same
file.

When GhostSlice is not reachable, the fallback is GhostSlice's own raw
v1 split (BPE-like, documented in ghostslice/tokens.py) at factor 1.0:
uncalibrated, and the method string says so. Either way the counts are
estimates, never exact tokenizer counts, and the method string in
force is stored with the index and printed by ``list``/``stats``.
"""
from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]")

_gs_estimate = None
_gs_method = None


def _try_load_ghostslice() -> None:
    global _gs_estimate, _gs_method
    try:
        from ghostslice.tokens import METHOD, estimate_tokens

        _gs_estimate, _gs_method = estimate_tokens, METHOD
        return
    except Exception:
        pass
    candidates: list[Path] = []
    for env in ("GHOSTINDEX_GHOSTSLICE_SRC", "GHOSTSLICE_SRC"):
        value = os.environ.get(env)
        if value:
            candidates.append(Path(value).expanduser())
    here = Path(__file__).resolve()
    # src/ghostindex/tokens.py -> workspace root is parents[3] when the
    # checkout lives at <workspace>/ghostindex/src/ghostindex/.
    candidates.append(here.parents[3] / "ghostslice" / "src")
    candidates.append(Path.home() / "workspace" / "ghostslice" / "src")
    for candidate in candidates:
        if (candidate / "ghostslice" / "tokens.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            try:
                from ghostslice.tokens import METHOD, estimate_tokens

                _gs_estimate, _gs_method = estimate_tokens, METHOD
            except Exception:
                _gs_estimate = _gs_method = None
            return


_try_load_ghostslice()

FALLBACK_METHOD = (
    "estimates (ghostindex fallback: BPE-like split v1, uncalibrated, "
    "not exact tokenizer counts)"
)


def _raw_split(text: str) -> int:
    """GhostSlice's raw v1 split, uncalibrated (factor 1.0)."""
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


def using_ghostslice() -> bool:
    """True when the calibrated GhostSlice estimator was loaded;
    False when the documented fallback estimator is in force."""
    return _gs_estimate is not None


def method() -> str:
    """The estimator method string currently in force."""
    if _gs_estimate is not None:
        return _gs_method
    return FALLBACK_METHOD


def estimate_tokens(text: str, language: str | None = None) -> int:
    """Estimate the token count of ``text``. The result is always
    an estimate (see :func:`method`), never an exact tokenizer
    count; ``language`` lets the calibrated estimator apply its
    per-language factor."""
    if _gs_estimate is not None:
        return _gs_estimate(text, language)
    return _raw_split(text)
