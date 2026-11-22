"""Token estimator.

Prefers GhostSlice's estimator when a GhostSlice checkout/install is
reachable (so a GhostExposure bundle validates under
``ghostslice check``, which recomputes sliced tokens with that
estimator and the per-file language from the file path). Falls back
to a documented chars/4 estimate when GhostSlice is not reachable;
bundles written under the fallback carry the fallback method string
in their manifest, and their token figures are estimates either way.

This mirrors the GhostPort bundle approach (ghostport/tokens.py).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_gs_estimate = None
_gs_method = None
_gs_language_for = None
try:
    from ghostslice.tokens import METHOD as _m  # type: ignore
    from ghostslice.tokens import estimate_tokens as _e  # type: ignore
    from ghostslice.scanner import language_for as _lf  # type: ignore
    _gs_estimate, _gs_method, _gs_language_for = _e, _m, _lf
except Exception:
    for candidate in (Path(__file__).resolve().parents[3] / "ghostslice" / "src",
                      Path.home() / "workspace" / "ghostslice" / "src"):
        if (candidate / "ghostslice" / "tokens.py").is_file() \
                and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            try:
                from ghostslice.tokens import METHOD as _m  # type: ignore
                from ghostslice.tokens import estimate_tokens as _e  # type: ignore
                from ghostslice.scanner import language_for as _lf  # type: ignore
                _gs_estimate, _gs_method, _gs_language_for = _e, _m, _lf
            except Exception:
                _gs_estimate = _gs_method = _gs_language_for = None
            break

# Fallback language map: mirrors GhostSlice scanner.LANGUAGE_BY_EXT
# for the extensions an Exposure bundle can carry, so the fallback
# path still names languages the same way GhostSlice would.
_LANGUAGE_BY_EXT = {
    ".py": "python",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript",
    ".md": "markdown", ".markdown": "markdown",
    ".txt": "text", ".json": "json",
    ".go": "go", ".rs": "rust", ".java": "java", ".cs": "csharp",
    ".php": "php", ".rb": "ruby", ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".scala": "scala", ".sc": "scala",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".sql": "sql",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".ps1": "powershell", ".psm1": "powershell",
    ".ipynb": "notebook",
}


def language_for(path) -> str:
    """Language label for a bundle-relative path, GhostSlice's when
    reachable, else the mirrored extension map above."""
    if _gs_language_for is not None:
        return _gs_language_for(str(path))
    return _LANGUAGE_BY_EXT.get(Path(str(path)).suffix.lower(), "text")


if _gs_estimate is not None:
    METHOD = _gs_method

    def estimate_tokens(text, path=None) -> int:
        """Estimate tokens in ``text`` with GhostSlice's estimator.

        ``path`` selects the per-file language when given. Empty or
        missing text estimates to 0. The result is an estimate, not a
        measured count.
        """
        if not text:
            return 0
        language = language_for(path) if path else None
        return int(_gs_estimate(text, language))
else:
    METHOD = "ghostexposure-estimate-v1: ceil(len(text)/4), estimates only"

    def estimate_tokens(text, path=None) -> int:
        """Estimate tokens in ``text`` as ``ceil(len(text) / 4)``.

        Fallback used only when GhostSlice is not reachable; ``path``
        is accepted for signature compatibility and does not change
        the estimate. Empty or missing text estimates to 0.
        """
        if not text:
            return 0
        return int(math.ceil(len(text) / 4))
