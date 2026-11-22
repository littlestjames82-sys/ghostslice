"""Marker scan and verification-report discovery.

Both are pure reads: marker lines are quoted (redacted, truncated),
reports are summarised from what is already on disk. Nothing in the
described project is executed, ever.

- :func:`scan_markers` finds TODO / FIXME / XXX / HACK markers and
  splits them into code context (counts as open loops) versus
  documentation / fixture context (listed, but not a loop); see
  :func:`marker_context`.
- :func:`discover_reports` finds known Ghost tool report files
  (GhostVerify, GhostBench, GhostSlice ledger and bundles, pytest
  last-failed cache) and summarises each from its contents and
  modification time. Results stored anywhere else are missed by
  design, and the pack's coverage note says so.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from .redact import clean_line

MARKER_RE = re.compile(r"(?<![A-Za-z0-9_])(TODO|FIXME|XXX|HACK)\b[:\s-]*(.*)")
MAX_FILE_BYTES = 512 * 1024

# A marker's context decides whether it counts as an open loop. Only
# unambiguous documentation or fixture locations are "docs": a docs /
# doc / documentation or fixture directory segment, or a documentation
# file extension (.md and kin, wherever the file lives). Everything
# else is "code". The split is deliberately conservative: a marker is
# never down-weighted on a guess, and docs-context markers are still
# listed in the pack with file and line, only subtotalled separately.
DOCS_DIRS = {"docs", "doc", "documentation"}
FIXTURE_DIRS = {"fixtures", "fixture", "testdata", "test_data", "__fixtures__"}
DOCS_EXTS = {".md", ".markdown", ".rst", ".adoc"}


def _contained_file(project: str, rel: str) -> str | None:
    """Resolved full path for a project-relative file, or None when the
    resolved path escapes the project tree. A symlink planted inside
    the project must not let a scan or a report read quote a file that
    is not part of the project. Both sides are resolved, so a project
    reached through a symlink itself still works."""
    root = os.path.realpath(project)
    full = os.path.realpath(os.path.join(project, rel))
    if full != root and not full.startswith(root + os.sep):
        return None
    if not os.path.isfile(full):
        return None
    return full


def marker_context(rel: str) -> str:
    """Classify a project-relative path as ``"code"`` or ``"docs"``.

    ``"docs"`` means a docs / fixture directory segment or a
    documentation file extension (``.md``, ``.rst``, and kin);
    everything else is ``"code"``. Only code-context markers count
    as open loops.
    """
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    for seg in parts[:-1]:
        low = seg.lower()
        if low in DOCS_DIRS or low in FIXTURE_DIRS:
            return "docs"
    if parts and os.path.splitext(parts[-1])[1].lower() in DOCS_EXTS:
        return "docs"
    return "code"


def scan_markers(project: str, files: list[str], max_markers: int = 200,
                 max_files: int = 20000) -> dict:
    """Scan ``files`` (relative to project) for TODO/FIXME/XXX/HACK markers.

    Skips files over 512 KB and files that look binary. Returns
    totals overall and split by kind and by context (``code_*`` vs
    ``docs_*``), the capped ``items`` list (each with ``file``,
    ``line``, ``kind``, ``context``, and redacted ``text``), and
    truncation flags for both the marker list and the file list, so
    a capped scan is visible in the pack rather than silent.
    """
    items: list[dict] = []
    total = 0
    by_kind: dict[str, int] = {}
    code_total = 0
    docs_total = 0
    code_by_kind: dict[str, int] = {}
    docs_by_kind: dict[str, int] = {}
    scanned = 0
    for rel in files[:max_files]:
        full = _contained_file(project, rel)
        if full is None:
            continue
        try:
            if os.path.getsize(full) > MAX_FILE_BYTES:
                continue
            with open(full, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if b"\0" in raw[:4096]:
            continue  # binary, skip
        scanned += 1
        context = marker_context(rel)
        text = raw.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            m = MARKER_RE.search(line)
            if not m:
                continue
            kind = m.group(1)
            total += 1
            by_kind[kind] = by_kind.get(kind, 0) + 1
            if context == "docs":
                docs_total += 1
                docs_by_kind[kind] = docs_by_kind.get(kind, 0) + 1
            else:
                code_total += 1
                code_by_kind[kind] = code_by_kind.get(kind, 0) + 1
            if len(items) < max_markers:
                items.append({
                    "file": rel,
                    "line": lineno,
                    "kind": kind,
                    "context": context,
                    "text": clean_line(m.group(2) or "", 140),
                })
    return {
        "total": total,
        "by_kind": by_kind,
        "code_total": code_total,
        "docs_total": docs_total,
        "code_by_kind": code_by_kind,
        "docs_by_kind": docs_by_kind,
        "items": items,
        "truncated": total > len(items),
        "files_scanned": scanned,
        "files_considered": len(files),
        "files_limit": max_files,
        "files_truncated": len(files) > max_files,
    }


def _iso_mtime(path: str) -> str:
    """ISO-8601 modification time of ``path``, or ``""`` if unreadable."""
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat(timespec="seconds")
    except OSError:
        return ""


def _read_json(path: str):
    """Parse ``path`` as JSON, returning ``None`` on any read/parse error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _first_verdict_line(path: str) -> str:
    """First non-blank line of ``path``, redacted and truncated (or ``""``)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if ln.strip():
                    return clean_line(ln, 160)
    except OSError:
        pass
    return ""


def discover_reports(project: str, max_bundles: int = 20) -> list[dict]:
    """Find verification evidence already on disk. Summaries only.

    Looks for, in the project root unless noted: ``verify-report.json``
    and ``VERIFY.md`` (GhostVerify), a GhostBench report file, the
    ``.ghostslice-history.jsonl`` ledger, the pytest
    ``.pytest_cache`` last-failed file, and GhostSlice bundle folders
    (a ``manifest.json`` in the top two levels, capped at
    ``max_bundles``). Each result is ``{"kind", "path", "modified",
    "summary"}`` plus kind-specific extras such as ``verdict`` or
    ``failing_count``, sorted by path. Nothing is executed or
    re-run; a report's age is part of its summary.
    """
    reports: list[dict] = []

    def add(kind: str, rel: str, summary: str, extra: dict | None = None):
        entry = {
            "kind": kind,
            "path": rel,
            "modified": _iso_mtime(os.path.join(project, rel)),
            "summary": summary,
        }
        if extra:
            entry.update(extra)
        reports.append(entry)

    # GhostVerify machine verdict
    vr = _contained_file(project, "verify-report.json")
    if vr is not None:
        data = _read_json(vr)
        verdict = None
        if isinstance(data, dict):
            for key in ("verdict", "status", "result", "ok"):
                if key in data:
                    verdict = data[key]
                    break
        if isinstance(verdict, str):
            # The verdict is quoted verbatim into both pack files (the
            # report entry and the open-loop detail), so it goes
            # through the same redaction pass as every other quote.
            verdict = clean_line(verdict, 80)
        summary = f"verdict field: {verdict}" if verdict is not None else "present, no verdict field parsed"
        add("ghostverify-report", "verify-report.json", clean_line(summary, 160),
            {"verdict": verdict})

    # GhostVerify human report
    vm = _contained_file(project, "VERIFY.md")
    if vm is not None:
        add("ghostverify-md", "VERIFY.md", _first_verdict_line(vm))

    # GhostBench report (any of the common names, root level)
    for name in ("bench-report.json", "BENCH.md", "bench-results.json"):
        p = _contained_file(project, name)
        if p is not None:
            if name.endswith(".json"):
                data = _read_json(p)
                keys = sorted(data.keys())[:6] if isinstance(data, dict) else []
                add("ghostbench-report", name,
                    clean_line("keys: " + ", ".join(keys) if keys else "present, unparsed", 160))
            else:
                add("ghostbench-report", name, _first_verdict_line(p))
            break

    # GhostSlice history ledger tail
    ledger = _contained_file(project, ".ghostslice-history.jsonl")
    if ledger is not None:
        last = ""
        count = 0
        try:
            with open(ledger, "r", encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    if ln.strip():
                        last = ln.strip()
                        count += 1
        except OSError:
            pass
        entry = _read_json_from_str(last)
        keys = sorted(entry.keys())[:6] if isinstance(entry, dict) else []
        add("ghostslice-ledger", ".ghostslice-history.jsonl",
            clean_line(f"{count} entries; last entry keys: " + ", ".join(keys), 160))

    # pytest lastfailed cache: counts only, recorded failures from the last run
    lf = _contained_file(project, os.path.join(
        ".pytest_cache", "v", "cache", "lastfailed"))
    if lf is not None:
        data = _read_json(lf)
        n = len(data) if isinstance(data, dict) else 0
        add("pytest-lastfailed", ".pytest_cache/v/cache/lastfailed",
            f"{n} test(s) recorded failing in the last pytest run",
            {"failing_count": n})

    # GhostSlice bundles: folders holding manifest.json, top two levels
    bundles: list[str] = []
    try:
        for name in sorted(os.listdir(project)):
            full = os.path.join(project, name)
            if os.path.isdir(full):
                if os.path.isfile(os.path.join(full, "manifest.json")):
                    bundles.append(name)
                else:
                    try:
                        for sub in sorted(os.listdir(full)):
                            if os.path.isfile(os.path.join(full, sub, "manifest.json")):
                                bundles.append(f"{name}/{sub}")
                    except OSError:
                        pass
    except OSError:
        pass
    for rel in bundles[:max_bundles]:
        manifest = _contained_file(project, os.path.join(rel, "manifest.json"))
        if manifest is None:
            continue  # bundle folder is a symlink out of the project
        data = _read_json(manifest)
        files_n = None
        if isinstance(data, dict):
            files_field = data.get("files")
            if isinstance(files_field, list):
                files_n = len(files_field)
        add("ghostslice-bundle", rel,
            f"GhostSlice bundle manifest ({files_n} files listed)" if files_n is not None
            else "GhostSlice bundle manifest (unparsed)")

    reports.sort(key=lambda r: r["path"])
    return reports


def _read_json_from_str(text: str):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None
