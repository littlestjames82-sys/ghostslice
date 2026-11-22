"""Diff sources and optional GhostVerify / GhostScope report readers.

Local only: git is invoked as a subprocess on the local project, files
are read from disk. Nothing here writes to the project or the network.
Optional reports are cited when supplied and readable; a supplied but
unreadable report is named as such, never silently dropped and never
invented.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def diff_from_file(path: str):
    """Return ``(diff_text, source_label)`` for a diff file.

    ``path == "-"`` reads stdin and labels the source ``stdin``;
    any other path is read as UTF-8 with replacement, so a stray
    non-UTF-8 byte cannot crash a review. Raises ``OSError`` for an
    unreadable file; the CLI turns that into exit code 2.
    """
    if path == "-":
        return sys.stdin.read(), "stdin"
    return Path(path).read_text(encoding="utf-8", errors="replace"), f"file:{path}"


def diff_from_git(project, staged: bool = False):
    """(diff_text, source_label, notes) from the local git repo."""
    args = ["git", "-C", str(project), "diff", "--no-color"]
    label = "git:staged" if staged else "git:working-tree-vs-HEAD"
    if staged:
        args.append("--cached")
    else:
        args.append("HEAD")
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return "", label, [f"could not run git diff: {exc}"]
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        return "", label, ["git diff failed: " +
                           (detail[0] if detail else "not a git repository?")]
    notes = []
    try:
        proc2 = subprocess.run(
            ["git", "-C", str(project), "status", "--porcelain"],
            capture_output=True, text=True, timeout=60)
        untracked = [ln[3:] for ln in proc2.stdout.splitlines()
                     if ln.startswith("?? ")]
        if untracked:
            notes.append(f"{len(untracked)} untracked file(s) are not in "
                         "this diff and were not reviewed: " +
                         ", ".join(sorted(untracked)[:10]))
    except (OSError, subprocess.SubprocessError):
        pass
    return proc.stdout, label, notes


def load_verify_report(path):
    """Summarise a GhostVerify verify-report.json, or return an absent/
    unreadable record. Only fields GhostVerify actually writes are read:
    verdict, exit_code, gaps / soft_gaps counts, post outcome."""
    if not path:
        return {"present": False}
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        return {"present": False, "supplied": str(p),
                "unreadable": f"could not read the supplied Verify report: {exc}"}
    if not isinstance(data, dict):
        # Valid JSON, wrong shape: name it unreadable instead of
        # crashing on .get or inventing counts from it.
        return {"present": False, "supplied": str(p),
                "unreadable": "could not read the supplied Verify report: "
                              "top-level JSON is not an object"}
    post = data.get("post") or {}
    if not isinstance(post, dict):
        post = {}
    tests = post.get("tests") or {}
    if not isinstance(tests, dict):
        tests = {}

    def _count(value):
        # Only a real list is counted; len() of a stray string would
        # report its characters as gaps that do not exist.
        return len(value) if isinstance(value, list) else 0

    return {
        "present": True,
        "path": str(p),
        "verdict": data.get("verdict"),
        "exit_code": data.get("exit_code"),
        "kind": data.get("kind"),
        "hard_gaps": _count(data.get("gaps")),
        "soft_gaps": _count(data.get("soft_gaps")),
        "post_verdict": post.get("verdict"),
        "post_tests_status": tests.get("status"),
    }


def _scope_str_list(value) -> list:
    """Normalise a scope.json list field to a list of strings.

    Entries are usually plain strings; a dict entry contributes its
    path / name / file value when it has one. Anything else is
    stringified. Order is preserved and duplicates are dropped by
    the caller-side merge, not here.
    """
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            for key in ("path", "name", "file"):
                if item.get(key):
                    out.append(str(item[key]))
                    break
            else:
                continue
        elif item is not None:
            out.append(str(item))
    return out


def _scope_reading_order(data: dict) -> list:
    """Reading order as recorded: [{path, order, mode}, ...].

    GhostScope writes a top-level ``reading_order`` list of dicts
    (path / order / mode); plain string entries are tolerated.
    Sorted by the recorded order number when every entry that has
    one is numeric; otherwise the recorded order is kept.
    """
    raw = data.get("reading_order")
    if not isinstance(raw, list):
        return []
    out = []
    for idx, entry in enumerate(raw):
        if isinstance(entry, dict):
            epath = entry.get("path")
            if not epath:
                continue
            order = entry.get("order")
            out.append({"path": str(epath),
                        "order": order if isinstance(order, int) else idx + 1,
                        "mode": entry.get("mode")})
        elif isinstance(entry, str) and entry:
            out.append({"path": entry, "order": idx + 1, "mode": None})
    out.sort(key=lambda e: e["order"])
    return out


def load_scope_pack(path):
    """Summarise a GhostScope pack: accepts a pack directory or the
    scope.json file itself. Reads scope.json only; builds nothing.

    Beyond the changed-file list and risk reasons, the reader also
    cites the per-file facts GhostScope records in the same entries
    (changed symbols, covering tests, direct caller counts), the
    recorded reading order, and the pack totals. All of it is copied
    verbatim from scope.json; nothing is recomputed or inferred."""
    if not path:
        return {"present": False}
    p = Path(path)
    scope_file = p if p.name == "scope.json" else p / "scope.json"
    try:
        data = json.loads(scope_file.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        return {"present": False, "supplied": str(p),
                "unreadable": f"could not read the supplied Scope pack: {exc}"}
    if not isinstance(data, dict):
        return {"present": False, "supplied": str(p),
                "unreadable": "could not read the supplied Scope pack: "
                              "top-level JSON is not an object"}
    # Every list GhostScope writes changed files into is read:
    # changed_files, files, changed, and analysis.changed. Earlier
    # versions of this reader skipped the top-level "changed" list,
    # silently dropping any risk reasons recorded only there.
    lists: list = []
    for key in ("changed_files", "files", "changed"):
        v = data.get(key)
        if isinstance(v, list):
            lists.extend(v)
    analysis = data.get("analysis") or {}
    if isinstance(analysis, dict) and isinstance(analysis.get("changed"), list):
        lists.extend(analysis["changed"])
    risk_reasons = []
    reasons_by_file: dict = {}
    changed_files: list = []
    symbols_by_file: dict = {}
    covering_by_file: dict = {}
    callers_by_file: dict = {}
    for entry in lists:
        if isinstance(entry, dict):
            epath = entry.get("path")
            if epath and epath not in changed_files:
                changed_files.append(epath)
            raw_reasons = entry.get("risk_reasons")
            if not (isinstance(raw_reasons, list) and raw_reasons):
                raw_reasons = entry.get("risks")
            if not isinstance(raw_reasons, list):
                # A stray string/dict here is not a list of reasons;
                # iterating it would invent one reason per character
                # or per key.
                raw_reasons = []
            for r in raw_reasons:
                if isinstance(r, (dict, list)):
                    continue
                reason = str(r)
                risk_reasons.append(reason)
                if epath:
                    bucket = reasons_by_file.setdefault(epath, [])
                    if reason not in bucket:
                        bucket.append(reason)
            if epath:
                # Per-file facts GhostScope records alongside the
                # risk reasons. Merged (never overwritten) because
                # the same file can appear in more than one list
                # (e.g. both "changed" and "files"). An explicitly
                # recorded empty covering_tests list is kept as an
                # empty entry: "recorded, and it is empty" is a
                # different cited fact from "not recorded".
                if "changed_symbols" in entry:
                    bucket = symbols_by_file.setdefault(epath, [])
                    for sym in _scope_str_list(entry.get("changed_symbols")):
                        if sym not in bucket:
                            bucket.append(sym)
                if "covering_tests" in entry:
                    bucket = covering_by_file.setdefault(epath, [])
                    for test in _scope_str_list(entry.get("covering_tests")):
                        if test not in bucket:
                            bucket.append(test)
                callers = entry.get("direct_callers")
                if isinstance(callers, int) and epath not in callers_by_file:
                    callers_by_file[epath] = callers
        elif isinstance(entry, str) and entry not in changed_files:
            changed_files.append(entry)
    totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
    tokens_raw = data.get("tokens")
    pack_tokens = totals.get("pack_tokens_estimate")
    if pack_tokens is None and isinstance(tokens_raw, int):
        pack_tokens = tokens_raw
    if pack_tokens is None and isinstance(tokens_raw, dict):
        pack_tokens = tokens_raw.get("pack_tokens_estimate") \
            or tokens_raw.get("total") or tokens_raw.get("estimate")
    reading_order = _scope_reading_order(data)
    return {
        "present": True,
        "path": str(p),
        "scope_file": str(scope_file),
        "base": data.get("base"),
        "head": data.get("head"),
        "changed_files": changed_files,
        "risk_reasons": sorted(set(risk_reasons)),
        "risk_reasons_by_file": reasons_by_file,
        "risk_reason_entries": sum(len(v) for v in reasons_by_file.values())
                               or len(set(risk_reasons)),
        "changed_symbols_by_file": symbols_by_file,
        "covering_tests_by_file": covering_by_file,
        "direct_callers_by_file": callers_by_file,
        "reading_order": reading_order,
        "reading_order_paths": [e["path"] for e in reading_order],
        "pack_files": totals.get("pack_files"),
        "pack_tokens_estimate": pack_tokens,
        "tokens": data.get("tokens"),
        "keys": sorted(data.keys()),
    }
