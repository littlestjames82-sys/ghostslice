"""Scoring: deliberately boring (PLAN.md section 4).

- Task success = a user test command passes (when tests are run),
  or, for Tier A static runs, a recorded patch that exists, touches
  at least one expected file, and carries no Verify hard gap.
- No LLM judge anywhere in v0.1.
- Files-touched is INFORMATIONAL: extra files are listed, never
  auto-failures. Real fixes touch unexpected files.
"""
from __future__ import annotations

import hashlib
import re

_DIFF_FILE_RE = re.compile(r"^\+\+\+ [ab]/(.+)$", re.M)
_OLD_FILE_RE = re.compile(r"^--- [ab]/(.+)$", re.M)
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def manifest_hash_for_bundle(bundle_dir: str | None = None,
                             manifest_path: str | None = None) -> str | None:
    """sha256 of a bundle manifest.json, for report traceability."""
    import os
    path = manifest_path
    if path is None and bundle_dir:
        path = os.path.join(bundle_dir, "manifest.json")
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return "sha256:" + h.hexdigest()


def _valid_token_count(value) -> bool:
    """A token count is a non-negative int. bool is an int subclass
    in Python, so True/False must be rejected explicitly, and a
    negative count is nonsense that would invent >100% savings."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def manifest_tokens(manifest_path: str) -> int | None:
    """Total sliced tokens from a GhostSlice-style manifest, if the
    manifest carries a recognisable total. None if not determinable:
    Bench surfaces the gap instead of averaging or guessing."""
    import json
    import os
    if not os.path.isfile(manifest_path):
        return None
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    totals = data.get("totals")
    if not isinstance(totals, dict):
        totals = {}
    for key in ("sliced_tokens", "tokens", "total_tokens"):
        if _valid_token_count(totals.get(key)):
            return totals[key]
    files = data.get("files")
    if not isinstance(files, list):
        return None
    total = 0
    found = False
    for entry in files:
        if isinstance(entry, dict) and _valid_token_count(entry.get("sliced_tokens")):
            total += entry["sliced_tokens"]
            found = True
    return total if found else None


def parse_patch(text: str) -> dict:
    """Static facts about a unified diff."""
    files = []
    # Scan both header lines in file order: a deletion has
    # '+++ /dev/null' (its name only appears on the '--- a/...'
    # line) and a creation has '--- /dev/null'. Consulting the old
    # name only when no new name exists anywhere in the patch would
    # silently drop deletions from mixed patches.
    for line in (text or "").splitlines():
        match = _DIFF_FILE_RE.match(line) or _OLD_FILE_RE.match(line)
        if match:
            name = match.group(1).strip()
            if name != "/dev/null" and name not in files:
                files.append(name)
    added = removed = 0
    for line in (text or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {
        "files_touched": files,
        "lines_added": added,
        "lines_removed": removed,
        "patch_sha256": "sha256:" + hashlib.sha256(
            (text or "").encode()).hexdigest(),
        "is_empty": not files and added == 0 and removed == 0,
    }


def _as_gap_list(value) -> list:
    """Coerce a gaps field to a list. A single gap given as a dict
    or string is ONE gap: list('oops') would count its characters
    as four separate gaps."""
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def normalise_verify_report(data: dict | None) -> dict:
    """Accept GhostVerify report shapes tolerantly, extract the
    signals Bench compares: verdict + hard gaps + soft gaps."""
    if not data or not isinstance(data, dict):
        return {"present": False, "verdict": None,
                "hard_gaps": [], "soft_gaps": []}
    hard = _as_gap_list(data.get("hard_gaps") or data.get("missing_hard")
                        or data.get("gaps_hard"))
    soft = _as_gap_list(data.get("soft_gaps") or data.get("missing_soft")
                        or data.get("gaps_soft"))
    gaps = _as_gap_list(data.get("gaps"))
    if gaps and not hard and not soft:
        for gap in gaps:
            if isinstance(gap, dict) and str(
                    gap.get("severity", "")).lower() in ("hard", "error"):
                hard.append(gap)
            else:
                soft.append(gap)
    verdict = data.get("verdict") or data.get("status")
    if verdict is None and "sufficient" in data:
        verdict = "sufficient" if data["sufficient"] else "insufficient"
    return {"present": True, "verdict": verdict,
            "hard_gaps": list(hard), "soft_gaps": list(soft)}


def symbol_leaf(symbol: str) -> str:
    """Last dotted component of an expected symbol: 'Pair.swap' -> 'swap',
    'mini.stats.mean' -> 'mean'. A bare name is its own leaf."""
    return str(symbol).rsplit(".", 1)[-1].strip()


def _symbol_present(symbol: str, text: str) -> bool:
    """Lexical whole-word presence: the full dotted name or its leaf
    appearing as a whole identifier in *text*. Substrings do not count
    ('mean' is not present in 'meaningful'). This is a static lexical
    check, not an AST or import resolution: Bench surfaces the result
    and never pretends it proved more than it measured."""
    candidates = {str(symbol), symbol_leaf(symbol)} - {""}
    for cand in candidates:
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(cand) + r"(?![A-Za-z0-9_])"
        if re.search(pattern, text or ""):
            return True
    return False


def patch_added_text(patch_text: str | None) -> str | None:
    """The added lines of a unified diff ('+' lines, header excluded),
    or None when there is no patch to inspect."""
    if patch_text is None:
        return None
    return "\n".join(
        line[1:] for line in patch_text.splitlines()
        if line.startswith("+") and not line.startswith("+++"))


def score_expected_symbols(expected_symbols: list, file_texts: dict,
                           patch_text: str | None = None) -> dict:
    """Score a task's expected_symbols, which the corpus format has
    always carried but Tier A previously never checked: a slice that
    silently dropped a needed symbol used to pass unnoticed.

    - found / missing are judged against the concatenated text of the
      task's expected_files (exactly the files the derived sliced arm
      is built from, so a missing symbol is a symbol the derived slice
      cannot contain).
    - the patch check is INFORMATIONAL, like files-touched extras: it
      records which expected symbols the recorded patch's added lines
      mention. A correct fix need not name every expected symbol in
      its added lines, so this never fails a task on its own.
    """
    expected = [str(s) for s in (expected_symbols or [])]
    combined = "\n".join((file_texts or {}).values())
    found = [s for s in expected if _symbol_present(s, combined)]
    missing = [s for s in expected if s not in found]
    added = patch_added_text(patch_text)
    if added is None:
        in_patch = missing_patch = None
    else:
        in_patch = [s for s in expected if _symbol_present(s, added)]
        missing_patch = [s for s in expected if s not in in_patch]
    return {
        "expected_symbols": expected,
        "found_in_expected_files": found,
        "missing_from_expected_files": missing,
        "coverage_pct": (round(len(found) * 100.0 / len(expected), 1)
                         if expected else None),
        "checked_against": "expected-files",
        "in_patch_added_lines": in_patch,
        "missing_from_patch_added_lines": missing_patch,
        "patch_check_informational_only": True,
    }


def score_files_touched(patch_info: dict | None, expected_files: list) -> dict:
    """Compare a patch's touched files with the expected files.

    Informational only (``informational_only`` is always true): extra
    files are listed, never treated as failures on their own.
    """
    touched = (patch_info or {}).get("files_touched") or []
    expected = list(expected_files or [])
    return {
        "expected_files": expected,
        "touched_files": touched,
        "matched_files": sorted(set(touched) & set(expected)),
        "extra_files": sorted(set(touched) - set(expected)),
        "missing_expected_files": sorted(set(expected) - set(touched)),
        "informational_only": True,
    }


def saving_pct(full_tokens: int, variant_tokens: int | None) -> float | None:
    """Percentage saved vs full (one decimal), or ``None`` when undefined."""
    if variant_tokens is None or not full_tokens:
        return None
    if variant_tokens < 0 or full_tokens < 0:
        return None
    return round((full_tokens - variant_tokens) * 100.0 / full_tokens, 1)
