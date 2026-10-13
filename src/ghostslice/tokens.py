"""Token estimation (method v2, calibrated per language family).

Token counts in GhostSlice are ESTIMATES, not exact model tokenizer
counts. No real tokenizer is available to a zero-dependency stdlib
tool, and none is pretended: the method below is a documented
approximation whose per-family behaviour is characterised on the
golden corpora in tests/fixtures/calibration/ and can be inspected
on any project with `ghostslice calibrate`.

Raw estimator (unchanged since v0.1): a BPE-like split,

  raw(text) = sum over each match of  r"[A-Za-z0-9_]+|[^\\w\\s]"
              of  1 if len(match) <= 4 else ceil(len(match) / 4)

Measured on the golden corpora, the raw estimator's implied
characters-per-token is 2.0-3.4 depending on family: it over-counts
versus published tokenizer behaviour because real BPE vocabularies
merge frequent substrings (common words, `function`, `return`,
indentation runs) that the raw split charges at full price.

Calibration (v0.10): each language family gets a multiplicative
factor so the calibrated estimator's implied chars/token on its
golden corpus matches a published-anchor TARGET rate:

  family       corpus  v1 implied  target  factor  basis
  prose        md      3.42        4.00    0.85    [1]
  python       py      3.10        3.60    0.86    [1]+density
  ts-js        ts      2.63        3.50    0.75    [1]+density
  go           go      2.48        3.40    0.73    [1]+density
  rust         rs      2.93        3.30    0.89    [1]+density
  c-family     c       2.86        3.30    0.87    [1]+density
  json-data    json    2.84        3.00    0.95    [1]+density
  minified-js  js      2.02        3.10    0.65    [1]+density

[1] OpenAI Help Center, "What are tokens and how to count them?":
    the published rules of thumb are ~4 characters per token and
    ~0.75 words per token for English text. The prose target IS
    that anchor. Code/data targets are engineering approximations:
    set denser than the prose anchor (0.75x-0.90x) because BPE
    tokenizers spend extra tokens on operators, punctuation and
    structural characters that prose lacks, and ordered by the
    relative symbol density the raw split exposes on the corpora.
    They are NOT measured against any vendor tokenizer (none is
    available offline); treat them as labelled approximations,
    exactly like every other number GhostSlice prints.

Languages without a corpus keep factor 1.0, i.e. raw v1
behaviour, until a corpus exists: yaml/toml map to json-data as
fellow structured data, and notebooks map to the python family
(their sliced rendering is code cells, so the python factor fits
the sliced side and the raw JSON side inherits it); sql, shell,
powershell and unknown labels map to "other". Unknown language or
no language: factor 1.0.

Evidence limits, stated plainly: each family corpus is ONE
representative hand-written sample of roughly 1-2 KB, so the
measured implied rates carry sampling noise at the second decimal;
the factors are coarse (two decimals) for exactly that reason.

Family derivation is per text, not per file: a minified JS file's
original is estimated with the minified-js factor while its (short,
readable) slice is estimated with the ts-js factor. That is
deliberate — bundle validation must be able to reproduce build-time
sliced totals from the bundle alone, and the bundle only contains
the sliced text.

Migration note: v0.10 totals are LOWER than v0.9 totals for the
calibrated families (all factors <= 1). Old bundles remain valid;
their manifests name the old method string. `check-budget` and
profile budgets compare against calibrated totals from v0.10 on,
so a budget tuned under v0.9 may need re-checking.
"""
from __future__ import annotations

import math
import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]")

METHOD = (
    "estimates (BPE-like split v2, per-language calibrated, "
    "not exact tokenizer counts)"
)

# Short stamp for surfaces that record which estimator produced a
# total (savings-ledger records from v0.14 on, bundle manifests carry
# the full METHOD string). v1 = the raw split (pre-v0.10), v2 = the
# calibrated method above. Totals across versions are NOT directly
# comparable; the history analytics warn instead of trending silently.
METHOD_VERSION = 2

# family -> (factor, target chars/token on the golden corpus)
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
    """Heuristic: JS/TS shipped minified has very long lines and
    almost no newlines relative to its size. Deterministic."""
    if len(text) < 400:
        return False
    lines = text.splitlines()
    if not lines:
        return False
    longest = max(len(ln) for ln in lines)
    return longest >= 300 and len(text) / len(lines) >= 200


def family_for(language: str | None, text: str | None = None) -> str:
    """Calibration family for a scanner language label. JS/TS text
    that looks minified gets its own family (its raw implied rate
    is far from readable JS)."""
    if not language:
        return "other"
    fam = _LANGUAGE_FAMILY.get(language, "other")
    if fam == "ts-js" and text is not None and looks_minified(text):
        return "minified-js"
    return fam


def estimate_tokens_raw(text: str) -> int:
    """The v1 BPE-like split, uncalibrated."""
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
    """Calibrated estimate. Without a language, factor 1.0 (raw)."""
    raw = estimate_tokens_raw(text)
    if raw == 0:
        return 0
    factor = FAMILY_FACTORS[family_for(language, text)]
    if factor == 1.0:
        return raw
    return int(raw * factor + 0.5)
