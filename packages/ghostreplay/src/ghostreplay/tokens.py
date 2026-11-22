"""Token estimation, mirroring GhostSlice's method v2.

Same documented approximation GhostSlice uses, reimplemented here
(stdlib only, no cross-package import so GhostReplay works on a
machine without GhostSlice installed):

  raw(text) = sum over matches of r"[A-Za-z0-9_]+|[^\\w\\s]"
              of 1 if len(match) <= 4 else ceil(len(match) / 4),
  then multiplied by the per-language-family calibration factor
  and rounded. Factors copied from GhostSlice tokens.py v2
  (prose 0.85, python 0.86, ts-js 0.75, go 0.73, rust 0.89,
  c-family 0.87, json-data 0.95, minified-js 0.65, other 1.0).

All counts are ESTIMATES, never exact tokenizer counts, and are
labelled as such on every surface. Provider-reported usage, when a
transcript carries it, is stored separately (field name prefix
"reported_") and never blended with these estimates.
"""
from __future__ import annotations

import math
import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]")

METHOD = ("estimates (BPE-like split v2, per-language calibrated, "
          "not exact tokenizer counts)")
METHOD_VERSION = 2

FAMILY_FACTORS: dict[str, float] = {
    "prose": 0.85, "python": 0.86, "ts-js": 0.75, "go": 0.73,
    "rust": 0.89, "c-family": 0.87, "json-data": 0.95,
    "minified-js": 0.65, "other": 1.0,
}

_LANGUAGE_FAMILY = {
    "python": "python", "notebook": "python",
    "typescript": "ts-js", "javascript": "ts-js", "go": "go",
    "rust": "rust", "c": "c-family", "cpp": "c-family",
    "java": "c-family", "csharp": "c-family", "scala": "c-family",
    "kotlin": "c-family", "swift": "c-family", "php": "c-family",
    "ruby": "c-family", "markdown": "prose", "json": "json-data",
    "yaml": "json-data", "toml": "json-data",
}

_EXT_LANGUAGE = {
    ".py": "python", ".ipynb": "notebook", ".ts": "typescript",
    ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".go": "go", ".rs": "rust", ".c": "c",
    ".h": "c", ".cpp": "cpp", ".java": "java", ".cs": "csharp",
    ".md": "markdown", ".json": "json", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "toml",
}


def language_for_path(path: str) -> str | None:
    """Best-guess language name from a file extension, or ``None``."""
    for ext, lang in _EXT_LANGUAGE.items():
        if path.endswith(ext):
            return lang
    return None


def looks_minified(text: str) -> bool:
    """Heuristic: very long lines suggest minified JS/TS."""
    if len(text) < 400:
        return False
    lines = text.splitlines()
    if not lines:
        return False
    return max(len(ln) for ln in lines) >= 300 and len(text) / len(lines) >= 200


def family_for(language: str | None, text: str | None = None) -> str:
    """Calibration family for a language (``other`` when unknown)."""
    if not language:
        return "other"
    fam = _LANGUAGE_FAMILY.get(language, "other")
    if fam == "ts-js" and text is not None and looks_minified(text):
        return "minified-js"
    return fam


def estimate_tokens_raw(text: str) -> int:
    """Uncalibrated token estimate (before the family factor)."""
    if not text:
        return 0
    total = 0
    for match in _TOKEN_RE.findall(text):
        n = len(match)
        total += 1 if n <= 4 else int(math.ceil(n / 4))
    return total


def estimate_tokens(text: str, language: str | None = None) -> int:
    """Estimated token count for ``text``. An estimate, never exact."""
    raw = estimate_tokens_raw(text)
    if raw == 0:
        return 0
    factor = FAMILY_FACTORS[family_for(language, text)]
    if factor == 1.0:
        return raw
    return int(raw * factor + 0.5)
