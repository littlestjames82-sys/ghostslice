"""Token estimation, byte-for-byte compatible with GhostSlice v1.0.6.

GhostScope packs must validate with `ghostslice check`, which
recomputes sliced token totals with GhostSlice's own estimator.
This module therefore reproduces that estimator exactly (BPE-like
split v2, per-language calibrated factors, ghostslice/tokens.py).
Counts are ESTIMATES, not exact model tokenizer counts.
"""
from __future__ import annotations

import math
import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]")

METHOD = (
    "estimates (BPE-like split v2, per-language calibrated, "
    "not exact tokenizer counts)"
)
METHOD_VERSION = 2

FAMILY_CALIBRATION: dict[str, tuple[float, float]] = {
    "prose": (0.85, 4.00),
    "python": (0.86, 3.60),
    "ts-js": (0.75, 3.50),
    "go": (0.73, 3.40),
    "rust": (0.89, 3.30),
    "c-family": (0.87, 3.30),
    "json-data": (0.95, 3.00),
    "minified-js": (0.65, 3.10),
    "other": (1.00, 0.0),
}
FAMILY_FACTORS: dict[str, float] = {
    fam: fac for fam, (fac, _tgt) in FAMILY_CALIBRATION.items()
}

_LANGUAGE_FAMILY = {
    "python": "python",
    "notebook": "python",
    "typescript": "ts-js",
    "javascript": "ts-js",
    "go": "go",
    "rust": "rust",
    "c": "c-family",
    "cpp": "c-family",
    "java": "c-family",
    "csharp": "c-family",
    "scala": "c-family",
    "kotlin": "c-family",
    "swift": "c-family",
    "php": "c-family",
    "ruby": "c-family",
    "markdown": "prose",
    "json": "json-data",
    "yaml": "json-data",
    "toml": "json-data",
}


def looks_minified(text: str) -> bool:
    if len(text) < 400:
        return False
    lines = text.splitlines()
    if not lines:
        return False
    longest = max(len(ln) for ln in lines)
    return longest >= 300 and len(text) / len(lines) >= 200


def family_for(language: str | None, text: str | None = None) -> str:
    if not language:
        return "other"
    fam = _LANGUAGE_FAMILY.get(language, "other")
    if fam == "ts-js" and text is not None and looks_minified(text):
        return "minified-js"
    return fam


def estimate_tokens_raw(text: str) -> int:
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


def estimate_tokens(text: str, language: str | None = None) -> int:
    raw = estimate_tokens_raw(text)
    if raw == 0:
        return 0
    factor = FAMILY_FACTORS[family_for(language, text)]
    if factor == 1.0:
        return raw
    return int(raw * factor + 0.5)
