"""Token estimation for GhostBench.

Parity rule (PLAN.md): Bench owns no slicing logic and no second
estimator in spirit. If GhostSlice is importable, its estimator is
used directly so Bench and Slice totals agree by construction. If
it is not importable, the fallback below reproduces the GhostSlice
v2 formula (BPE-like split + the same per-family calibration
factors, copied with attribution from ghostslice/tokens.py) and
every report stamps estimator_version so the source is visible.
A disagreement between Slice and Bench totals is a bug to surface,
never a number to average: reports record which estimator ran.
"""
from __future__ import annotations

import math
import re

try:  # Prefer the real GhostSlice estimator when available.
    from ghostslice.tokens import estimate_tokens as _gs_estimate
    from ghostslice.tokens import METHOD_VERSION as _GS_METHOD_VERSION

    ESTIMATOR_SOURCE = "ghostslice"
    ESTIMATOR_VERSION = f"ghostslice-estimator-v{_GS_METHOD_VERSION}"

    def estimate_tokens(text: str, language: str | None = None) -> int:
        """Estimate tokens with the installed GhostSlice estimator."""
        return _gs_estimate(text, language)

except Exception:  # pragma: no cover - exercised only without Slice
    ESTIMATOR_SOURCE = "fallback"
    ESTIMATOR_VERSION = "fallback-estimator-v2-compatible"

    _TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]")
    _FACTORS = {
        "prose": 0.85, "python": 0.86, "ts-js": 0.75, "go": 0.73,
        "rust": 0.89, "c-family": 0.87, "json-data": 0.95,
        "minified-js": 0.65, "other": 1.00,
    }
    _LANG_FAMILY = {
        "python": "python", "notebook": "python",
        "typescript": "ts-js", "javascript": "ts-js", "go": "go",
        "rust": "rust", "c": "c-family", "cpp": "c-family",
        "java": "c-family", "csharp": "c-family", "scala": "c-family",
        "kotlin": "c-family", "swift": "c-family", "php": "c-family",
        "ruby": "c-family", "markdown": "prose", "json": "json-data",
        "yaml": "json-data", "toml": "json-data",
    }

    def _looks_minified(text: str) -> bool:
        if len(text) < 400:
            return False
        lines = text.splitlines()
        if not lines:
            return False
        return max(len(ln) for ln in lines) >= 300 and len(text) / len(lines) >= 200

    def _family(language: str | None, text: str) -> str:
        if not language:
            return "other"
        fam = _LANG_FAMILY.get(language, "other")
        if fam == "ts-js" and _looks_minified(text):
            return "minified-js"
        return fam

    def estimate_tokens(text: str, language: str | None = None) -> int:
        """Estimate tokens with the fallback v2-compatible formula."""
        if not text:
            return 0
        raw = 0
        for match in _TOKEN_RE.findall(text):
            n = len(match)
            raw += 1 if n <= 4 else int(math.ceil(n / 4))
        factor = _FACTORS[_family(language, text)]
        if factor == 1.0:
            return raw
        return int(raw * factor + 0.5)


# Extension -> scanner-style language label (subset GhostSlice uses).
EXT_LANGUAGE = {
    ".py": "python", ".ipynb": "notebook", ".ts": "typescript",
    ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".go": "go", ".rs": "rust", ".c": "c",
    ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".java": "java",
    ".cs": "csharp", ".scala": "scala", ".kt": "kotlin",
    ".swift": "swift", ".php": "php", ".rb": "ruby",
    ".md": "markdown", ".json": "json", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "toml", ".txt": "markdown",
}


def language_for_path(path: str) -> str | None:
    """Return the scanner-style language label for ``path``, or ``None``.

    Based only on the file extension (see ``EXT_LANGUAGE``); unknown
    extensions return ``None``.
    """
    import os
    return EXT_LANGUAGE.get(os.path.splitext(path)[1].lower())


def slice_version() -> str | None:
    """Installed GhostSlice version, or None. Recorded on reports."""
    try:
        import ghostslice
        return getattr(ghostslice, "__version__", None)
    except Exception:
        return None
