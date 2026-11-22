"""Adapter over GhostSlice: slicing + secret scan.

GhostProxy is a runtime for GhostSlice, not a second slicer. All real
slicing and secret detection is delegated to the ``ghostslice`` package
when importable (see tokens._load_ghostslice). When GhostSlice is not
available, slicing reports unavailable and the caller passes content
through untouched (fail-open), which is the plan's stated behaviour.
The secret fallback is a narrow shape check used only when GhostSlice
is absent, and it returns path/line/type only -- never a value.
"""
from __future__ import annotations

import posixpath
import re

from . import tokens as _tokens_mod  # ensures the sibling-path bootstrap ran

_EXTENSION_LANGUAGE = {
    ".py": "python", ".ipynb": "notebook",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java", ".cs": "csharp",
    ".php": "php", ".rb": "ruby", ".kt": "kotlin", ".swift": "swift",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    ".scala": "scala", ".md": "markdown", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
}


def language_for(path: str) -> str:
    if _tokens_mod.ghostslice_available():
        try:
            from ghostslice.slicer import language_for as gs_language_for
            return gs_language_for(path)
        except Exception:
            pass
    ext = posixpath.splitext(path or "")[1].lower()
    return _EXTENSION_LANGUAGE.get(ext, "text")


def available() -> bool:
    return _tokens_mod.ghostslice_available()


def slice_text(path: str, source: str, mode: str) -> str | None:
    """Slice *source* to *mode* via GhostSlice; None if unavailable/fails."""
    if not available():
        return None
    try:
        from ghostslice.slicer import slice_source
        return slice_source(source, language_for(path), mode, path=path)
    except Exception:
        return None


# Narrow fallback shapes (used ONLY when GhostSlice is absent). Values are
# matched then discarded; only the finding type is ever returned.
#
# Parity policy (seam fix, Oct 14 2026; full audit in SEAM_FIX_REPORT.md):
# these shapes mirror GhostSlice's canonical guard
# (ghostslice/secrets_scan.py, _KNOWN_PATTERNS) so the Slice-absent path
# does not silently catch less than the delegated path for every shape it
# carries. Two canonical behaviours are deliberately NOT mirrored:
# high-entropy-assignment (per-line entropy scoring is Slice's job; the
# fallback stays a pure shape net, which also keeps the fail-open hot
# path free of scoring work) and Slice's full placeholder heuristics
# (the fallback keeps only the marker/repetition checks in
# _looks_placeholder). sensitive-assignment keeps a narrower name gate
# than Slice's on purpose; see the report.
_FALLBACK_SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai-or-anthropic-key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("password-in-url", re.compile(r"://[^/\s:@'\"]+:[^/\s:@'\"]{3,}@")),
    ("sensitive-assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']")),
)

# Slice gates its bare-40-char "aws-secret-key" shape behind an
# AWS-secret context on the same line; the fallback applies the same
# gate, plus the placeholder check below.
_FALLBACK_AWS_SECRET_CONTEXT = re.compile(
    r"aws.{0,20}secret|secret.{0,20}aws", re.IGNORECASE)
_FALLBACK_BARE_40 = re.compile(r"\b[A-Za-z0-9/+=]{40}\b")

# Trimmed copy of Slice's PLACEHOLDER_MARKERS: enough to keep obvious
# documentation examples (AWS's own docs carry a 40-char example key)
# from tripping the bare-40 shape on the fallback path.
_FALLBACK_PLACEHOLDER_MARKERS = (
    "example", "xxx", "your-", "your_", "yourkey", "placeholder",
    "changeme", "change-me", "change_me", "dummy", "sample", "fixture",
    "redacted", "insert-", "insert_", "todo", "fake", "test-key",
    "test_key", "not-a-real", "not_real", "mock",
)


def _looks_placeholder(value: str) -> bool:
    v = (value or "").strip().strip("\"'")
    if not v:
        return True
    low = v.lower()
    if any(m in low for m in _FALLBACK_PLACEHOLDER_MARKERS):
        return True
    if set(v) <= {"*", "x", "X", ".", "-", "_"}:
        return True
    if len(v) >= 6 and len(set(v)) <= 2:
        return True  # repeated short pattern, e.g. abcabcabc or 11111111
    return False


# ---------------------------------------------------------------------------
# Duplicate detection (exact-normalized + near), delegated to GhostSlice.
#
# GhostSlice's canonical detector (ghostslice/duplicates.py) defines:
# exact = sha256 of normalized content (per-line trailing whitespace
# stripped, trailing blank lines dropped), ignoring content shorter
# than 20 normalized characters; near = Jaccard similarity over the
# set of distinct non-empty stripped lines ("line shingles"), only for
# texts with at least 200 normalized characters and at least 8
# distinct lines, at similarity >= 0.85. The helpers below use those
# very functions when GhostSlice is importable; the local definitions
# are a line-for-line copy of the same algorithm (constants included)
# so the Slice-absent path -- where duplicate dropping still runs,
# unlike slicing itself -- detects exactly the same duplicates.
# Only digests, line sets, and a similarity score ever leave this
# module: never file content.

NEAR_THRESHOLD = 0.85
NEAR_MIN_LINES = 8
NEAR_MIN_CHARS = 200
EXACT_MIN_CHARS = 20


def _local_normalize(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _local_line_shingles(text: str) -> set:
    return {ln.strip() for ln in _local_normalize(text).splitlines()
            if ln.strip()}


def _gs_duplicates():
    """The ghostslice.duplicates module, or None when unavailable."""
    if not available():
        return None
    try:
        from ghostslice import duplicates
        return duplicates
    except Exception:
        return None


def normalize_content(text: str) -> str:
    """GhostSlice's normalization for duplicate comparison."""
    mod = _gs_duplicates()
    if mod is not None:
        try:
            return mod.normalize(text)
        except Exception:
            pass
    return _local_normalize(text)


def line_shingles(text: str) -> set:
    """The distinct non-empty stripped lines of *text* (near shingles)."""
    mod = _gs_duplicates()
    if mod is not None:
        try:
            return set(mod.line_shingles(text))
        except Exception:
            pass
    return _local_line_shingles(text)


def duplicate_fingerprint(text: str) -> dict:
    """Everything duplicate comparison needs for one text, content-free
    beyond the in-memory line set: the normalized text's digest (None
    below GhostSlice's exact noise floor), its line shingles, and
    whether it clears the near-duplicate size floors."""
    mod = _gs_duplicates()
    threshold_chars = NEAR_MIN_CHARS
    min_lines = NEAR_MIN_LINES
    exact_min = EXACT_MIN_CHARS
    if mod is not None:
        threshold_chars = getattr(mod, "NEAR_MIN_CHARS", threshold_chars)
        min_lines = getattr(mod, "NEAR_MIN_LINES", min_lines)
        exact_min = getattr(mod, "EXACT_MIN_CHARS", exact_min)
    normalized = normalize_content(text)
    shingles = line_shingles(text)
    digest = None
    if len(normalized) >= exact_min:
        import hashlib
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return {
        "normalized_digest": digest,
        "shingles": shingles,
        "near_eligible": len(normalized) >= threshold_chars
                         and len(shingles) >= min_lines,
    }


def near_similarity(fp_a: dict, fp_b: dict) -> float:
    """Jaccard similarity of two fingerprints' line shingles (0.0-1.0)."""
    sa, sb = fp_a.get("shingles") or set(), fp_b.get("shingles") or set()
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


def near_threshold() -> float:
    mod = _gs_duplicates()
    if mod is not None:
        return float(getattr(mod, "NEAR_THRESHOLD", NEAR_THRESHOLD))
    return NEAR_THRESHOLD


def scan_secrets(path: str, text: str) -> list[dict]:
    """Secret findings for one text: [{path, line, type}] and nothing else.

    The flagged VALUE is never included anywhere in the return value.
    """
    if available():
        try:
            from ghostslice.secrets_scan import scan_text
            return [{"path": f.get("path", path), "line": f.get("line", 0),
                     "type": f.get("type", "unknown")}
                    for f in scan_text(path, text)]
        except Exception:
            pass
    findings = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for ptype, pat in _FALLBACK_SECRET_PATTERNS:
            if pat.search(line):
                findings.append({"path": path, "line": line_no, "type": ptype})
        if _FALLBACK_AWS_SECRET_CONTEXT.search(line):
            m = _FALLBACK_BARE_40.search(line)
            if m and not _looks_placeholder(m.group(0)):
                findings.append({"path": path, "line": line_no,
                                 "type": "aws-secret-key"})
    return findings
