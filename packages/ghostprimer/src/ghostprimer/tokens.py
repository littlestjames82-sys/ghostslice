"""Token estimation.

Prefers GhostSlice's calibrated estimator so Primer bundle totals can be
reproduced by `ghostslice check`. Resolution order: an importable
ghostslice package, $GHOSTPRIMER_GHOSTSLICE_SRC, then the sibling
checkout ~/workspace/ghostslice/src. Falls back to a documented chars/4
estimate with its own method string when GhostSlice is not available;
bundles built on the fallback carry that method string in the manifest
and will not reproduce under `ghostslice check` (stated in the report).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

FALLBACK_METHOD = "ghostprimer-chars4-fallback-v1"


def _load_slice_tokens():
    try:
        from ghostslice import tokens as t  # type: ignore
        return t
    except Exception:
        pass
    candidates = []
    env = os.environ.get("GHOSTPRIMER_GHOSTSLICE_SRC")
    if env:
        candidates.append(Path(env))
    candidates.append(Path.home() / "workspace" / "ghostslice" / "src")
    for cand in candidates:
        if (cand / "ghostslice" / "tokens.py").exists():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            try:
                from ghostslice import tokens as t  # type: ignore
                return t
            except Exception:
                continue
    return None


_SLICE = _load_slice_tokens()

if _SLICE is not None:
    METHOD = getattr(_SLICE, "METHOD", "ghostslice-estimator")

    def estimate(text: str, language: str | None = None) -> int:
        try:
            return int(_SLICE.estimate_tokens(text, language))
        except TypeError:
            return int(_SLICE.estimate_tokens(text))
else:
    METHOD = FALLBACK_METHOD

    def estimate(text: str, language: str | None = None) -> int:
        if not text:
            return 0
        return max(1, -(-len(text) // 4))


def slice_available() -> bool:
    """True when GhostSlice's estimator was loaded (see module docstring);
    False means totals use the chars/4 fallback and will not reproduce
    under ``ghostslice check``."""
    return _SLICE is not None


def language_for(path: str) -> str:
    """Language label for *path*, used for estimation and the manifest.
    Delegates to GhostSlice when available, else maps the extension."""
    if _SLICE is not None:
        try:
            from ghostslice.scanner import language_for as lf  # type: ignore
            return lf(path)
        except Exception:
            pass
    ext = Path(path).suffix.lower()
    return {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "typescript", ".jsx": "javascript", ".md": "markdown",
        ".json": "json", ".toml": "toml", ".yaml": "yaml", ".yml": "yaml",
    }.get(ext, "text")
