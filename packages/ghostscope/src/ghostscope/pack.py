"""GhostScope core: changed-symbol mapping, blast radius + risk,
covering tests, factual notes, and review pack export.

A pack is a GhostSlice-compatible bundle (manifest.json + PROMPT.md
+ files/) plus scope.json and REVIEW.md. The manifest uses
GhostSlice's exact token method (see tokens.py) so a pack validates
with `ghostslice check`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .gitinput import ChangeInput
from .graphbuild import (TRANSITIVE_DEPTH_CAP, build_project_graph,
                         covering_tests, outline_cover)
from .outline import FileOutline, build_outline, resolve_imports
from .profile import ScopeProfile
from .scanner import ScanResult, is_test_file, language_for, read_text, scan
from .secretslite import scan_added_lines
from .slicer import SLICABLE, slice_text
from .tokens import METHOD, estimate_tokens

MODE_FOR_DISTANCE = {0: "full", 1: "signatures", 2: "interfaces"}


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _changed_symbols(change, head_outline: FileOutline | None,
                     base_outline: FileOutline | None) -> list[dict]:
    found: dict[str, dict] = {}

    def note_symbol(outline: FileOutline | None, line: int, side: str):
        if outline is None or outline.method == "none":
            return
        sym = outline.symbol_at_line(line)
        if sym is None:
            key = "<module>"
            if key not in found:
                found[key] = {"name": "<module>", "qualified": "<module>",
                              "kind": "module", "side": side}
            return
        if sym.qualified not in found:
            entry = {"name": sym.name, "qualified": sym.qualified,
                     "kind": sym.kind, "side": side}
            if outline is head_outline:
                entry["signature_new"] = sym.signature
            else:
                entry["signature_old"] = sym.signature
            found[sym.qualified] = entry

    for lineno, _t in change.added:
        note_symbol(head_outline, lineno, "added")
    for lineno, _t in change.deleted:
        note_symbol(base_outline or head_outline, lineno, "deleted")
    # enrich with signatures from both sides
    for entry in found.values():
        qual = entry["qualified"]
        if head_outline and qual in head_outline.symbols:
            entry["signature_new"] = head_outline.symbols[qual].signature
        if base_outline and qual in base_outline.symbols:
            entry["signature_old"] = base_outline.symbols[qual].signature
        old, new = entry.get("signature_old"), entry.get("signature_new")
        entry["signature_changed"] = bool(old and new and old != new)
        entry["removed"] = bool(old and not new and entry["side"] == "deleted")
    return sorted(found.values(), key=lambda e: e["qualified"])


def analyse(project: str | Path, inp: ChangeInput,
            profile: ScopeProfile) -> dict:
    """Analyse a change: scan the project, build its graph, and report
    each changed file with its symbols, callers, covering tests, risk
    score and risk reasons, plus the factual notes for the pack.
    """
    root = Path(project).expanduser().resolve()
    scan_result = scan(root)
    graph = build_project_graph(scan_result)
    entries = scan_result.by_path()
    changed_paths = {c.path for c in inp.changes if c.path}

    changed_reports: list[dict] = []
    all_covering: dict[str, dict] = {}
    for change in inp.changes:
        path = change.path
        head_text = inp.head_content(root, change) if change.status != "deleted" else None
        base_text = inp.base_content(root, change)
        head_outline = None
        if head_text is not None and path in entries:
            head_outline = build_outline(path, head_text, entries[path].language)
            resolve_imports(head_outline, set(entries))
        elif path in graph.outlines:
            head_outline = graph.outlines[path]
        base_outline = None
        if base_text is not None:
            lang = entries[path].language if path in entries else language_for(path)
            base_outline = build_outline(path, base_text, lang)
            resolve_imports(base_outline, set(entries))

        syms = _changed_symbols(change, head_outline, base_outline)
        sym_names = [s["name"] for s in syms if s["name"] != "<module>"]

        covering = covering_tests(scan_result, graph, path, sym_names) \
            if change.status != "deleted" else []
        for cov in covering:
            all_covering[cov["path"]] = cov

        secret_findings = scan_added_lines(path, change.added)
        entry_file = entries.get(path)
        is_entry_file = profile.is_entry_point_file(path) or bool(
            head_outline and head_outline.has_main_guard)
        imported_by = graph.file_callers.get(path, set()) if path in graph.file_callers else set()

        for s in syms:
            qual_full = f"{path}:{s['qualified']}" if s["qualified"] != "<module>" else None
            direct_all = graph.direct_symbol_callers(qual_full) if qual_full else []
            transitive_all = graph.transitive_symbol_callers(qual_full) if qual_full else []
            # Blast radius counts production dependents. A covering
            # test calling the symbol is cover, not risk, and is
            # reported separately (caller_count is the number a
            # reviewer would count by hand in the fixture: the
            # non-test callers).
            from .scanner import is_test_file as _is_test
            direct = [c for c in direct_all if not _is_test(c.split(":")[0])]
            test_callers = [c for c in direct_all if _is_test(c.split(":")[0])]
            transitive = [c for c in transitive_all
                          if not _is_test(c.split(":")[0])]
            s["direct_callers"] = direct
            s["test_callers"] = test_callers
            s["all_direct_callers"] = direct_all
            s["transitive_callers"] = transitive
            s["caller_count"] = len(direct)
            s["covering_tests"] = [c["path"] for c in covering]
            exported = False
            if head_outline and s["qualified"] in head_outline.symbols:
                hs = head_outline.symbols[s["qualified"]]
                exported = hs.exported or (
                    "." not in s["qualified"] and not s["name"].startswith("_")
                    and bool(imported_by))
            s["exported"] = exported
            s["entry_point"] = bool(is_entry_file and (
                s["name"] == "main" or s["kind"] != "module"))
            # --- risk ---
            score = 0
            reasons: list[str] = []
            if direct:
                score += min(len(direct) * 5, 50)
                reasons.append(f"{len(direct)} callers")
            extra = len([t for t in transitive if t not in direct])
            if extra:
                score += min(extra * 2, 20)
                reasons.append(
                    f"{len(transitive)} callers within {TRANSITIVE_DEPTH_CAP} hops")
            if exported:
                score += 20
                reasons.append("exported API")
            if s["entry_point"]:
                score += 15
                reasons.append("entry point")
            if not covering:
                score += 20
                reasons.append("no covering test")
            if s.get("signature_changed"):
                score += 15
                reasons.append("signature changed")
            if s.get("removed"):
                score += 10
                reasons.append("symbol removed")
            if profile.is_sensitive(path):
                score += 20
                reasons.append(f"touches sensitive path in profile ({path})")
            if secret_findings:
                score += 25
                reasons.append("secret-shaped line added")
            s["risk_score"] = score
            s["risk_reasons"] = reasons

        file_score = max((s["risk_score"] for s in syms), default=10)
        if change.status == "deleted":
            file_score += 10
        # file-level signals must show even when no symbol was mapped
        # (a changed JSON file with a secret in it has no symbols)
        file_reasons = sorted({r for s in syms for r in s["risk_reasons"]})
        if secret_findings and "secret-shaped line added" not in file_reasons:
            file_reasons.append("secret-shaped line added")
            file_score = max(file_score, 45)
        if profile.is_sensitive(path):
            sens = f"touches sensitive path in profile ({path})"
            if sens not in file_reasons:
                file_reasons.append(sens)
                file_score = max(file_score, 40)
        changed_reports.append({
            "path": path,
            "old_path": change.old_path,
            "status": change.status,
            "added_lines": change.added_count,
            "deleted_lines": change.deleted_count,
            "language": entries[path].language if path in entries else
                        language_for(path),
            "method": (head_outline.method if head_outline else "none"),
            "symbols": syms,
            "covering_tests": covering,
            "secret_findings": secret_findings,
            "is_generated": bool(entry_file and entry_file.is_generated),
            "is_minified": bool(entry_file and entry_file.is_minified),
            "is_vendored": bool(entry_file and entry_file.is_vendored),
            "risk_score": file_score,
            "risk_reasons": file_reasons,
        })

    lost_map = _lost_covering_tests(root, inp, scan_result, graph,
                                    changed_reports)
    _apply_lost_coverage(changed_reports, lost_map)

    distances = graph.distances_from(changed_paths)
    notes = _factual_notes(changed_reports, changed_paths, all_covering, inp)
    return {
        "root": str(root),
        "scan": scan_result,
        "graph": graph,
        "changed": changed_reports,
        "distances": distances,
        "covering_tests_all": all_covering,
        "lost_covering_tests": lost_map,
        "notes": notes,
        "repo_total_tokens": scan_result.total_tokens,
    }


def _lost_covering_tests(root, inp, scan_result, graph,
                         changed_reports) -> dict[str, list[dict]]:
    """Test cover this diff itself removed, linked to what it covered.

    Head-side covering tests can never see a test file the diff
    deleted (it is gone from the scan) or a test function the diff
    edited away, so without this pass a changed symbol whose only
    cover vanished in the same diff reads as a generic "no covering
    test" and the reviewer must infer the connection by hand. This
    pass rebuilds the base-side outline of every test file the diff
    deleted or modified and checks, with the same covering semantics
    as covering_tests(), what it covered at base and no longer
    covers at head. Only test files named by the diff are examined:
    an untouched test file's cover cannot be lost by this diff.

    Returns {changed_path: [{path, how, reasons, symbols,
    file_level_only, method}]}. ``symbols`` holds only call-proven
    symbols; an import-only base cover is file-level and is flagged
    ``file_level_only`` rather than guessed onto symbols.
    """
    entries = scan_result.by_path()
    all_paths = set(entries) | {c.path for c in inp.changes if c.path}
    targets = [rep for rep in changed_reports
               if rep["status"] != "deleted" and not is_test_file(rep["path"])]
    if not targets:
        return {}
    lost: dict[str, list[dict]] = {}
    for change in inp.changes:
        tpath = change.path
        if not tpath or not is_test_file(tpath):
            continue
        if change.status not in ("deleted", "modified"):
            continue
        base_text = inp.base_content(root, change)
        if base_text is None:
            continue
        lang = entries[tpath].language if tpath in entries \
            else language_for(tpath)
        base_outline = build_outline(tpath, base_text, lang)
        resolve_imports(base_outline, all_paths)
        head_outline = graph.outlines.get(tpath) \
            if change.status != "deleted" else None
        for rep in targets:
            if rep["path"] == tpath:
                continue
            sym_names = [s["name"] for s in rep["symbols"]
                         if s["name"] != "<module>"]
            if not sym_names:
                continue
            base_cover = outline_cover(base_outline, rep["path"], sym_names)
            if not base_cover["reasons"]:
                continue
            head_cover = outline_cover(head_outline, rep["path"], sym_names) \
                if head_outline is not None else {"reasons": [], "symbols": []}
            lost_syms = [s for s in base_cover["symbols"]
                         if s not in head_cover["symbols"]]
            if not lost_syms and head_cover["reasons"]:
                continue  # base cover fully intact at head
            lost.setdefault(rep["path"], []).append({
                "path": tpath,
                "how": "deleted" if change.status == "deleted" else "removed",
                "reasons": base_cover["reasons"],
                "symbols": lost_syms,
                "file_level_only": not base_cover["symbols"],
                "method": base_cover["method"],
            })
    for entries_lost in lost.values():
        entries_lost.sort(key=lambda e: e["path"])
    return lost


def _apply_lost_coverage(changed_reports, lost_map) -> None:
    """Fold lost cover into per-symbol/per-file risk, reasons first.

    A symbol proven (by call) to have lost a covering test gains the
    explicit reason "covering test deleted/removed in this diff
    (<test path>)" and +10. File-level-only cover (import-proven)
    raises the file's reasons and score without inventing a
    symbol-level claim.
    """
    for rep in changed_reports:
        entries_lost = lost_map.get(rep["path"], [])
        rep["lost_covering_tests"] = entries_lost
        if not entries_lost:
            continue
        file_reasons = list(rep["risk_reasons"])
        bumped_symbol = False
        for entry in entries_lost:
            reason = (f"covering test {entry['how']} in this diff "
                      f"({entry['path']})")
            file_reasons.append(reason)
            for s in rep["symbols"]:
                if s["name"] in entry["symbols"] \
                        and reason not in s["risk_reasons"]:
                    s["risk_reasons"].append(reason)
                    s["risk_score"] += 10
                    bumped_symbol = True
        rep["risk_reasons"] = sorted(set(file_reasons) | {
            r for s in rep["symbols"] for r in s["risk_reasons"]})
        best = max([rep["risk_score"]] +
                   [s["risk_score"] for s in rep["symbols"]])
        # Symbol bumps already flow into `best`; a file-level-only
        # loss has no symbol to carry the raise, so the file takes it.
        rep["risk_score"] = best if bumped_symbol else best + 10


def _factual_notes(changed_reports, changed_paths, all_covering, inp) -> list[dict]:
    notes: list[dict] = []
    for rep in changed_reports:
        path = rep["path"]
        for s in rep["symbols"]:
            if s.get("signature_changed"):
                notes.append({
                    "kind": "signature-changed", "path": path,
                    "symbol": s["qualified"],
                    "text": f"{path}: symbol {s['qualified']} changed signature "
                            f"from `{s.get('signature_old')}` to `{s.get('signature_new')}`",
                })
            if s.get("removed"):
                notes.append({
                    "kind": "symbol-removed", "path": path,
                    "symbol": s["qualified"],
                    "text": f"{path}: symbol {s['qualified']} was removed by this change",
                })
            stale = [c for c in s.get("direct_callers", [])
                     if c.split(":")[0] not in changed_paths]
            if stale and (s.get("signature_changed") or s.get("removed")):
                notes.append({
                    "kind": "caller-not-updated", "path": path,
                    "symbol": s["qualified"],
                    "text": f"{path}: symbol {s['qualified']} changed but "
                            f"{len(stale)} caller(s) were not updated in this "
                            f"diff: {', '.join(sorted(stale)[:10])}",
                })
            lost_for_sym = [e for e in rep.get("lost_covering_tests", [])
                            if s["name"] in e["symbols"]]
            for entry in lost_for_sym:
                notes.append({
                    "kind": "covering-test-deleted"
                            if entry["how"] == "deleted"
                            else "covering-test-removed",
                    "path": path,
                    "symbol": s["qualified"],
                    "text": f"{path}: symbol {s['qualified']} lost its "
                            f"covering test {entry['path']}, "
                            f"{entry['how']} in this diff",
                })
            if not rep["covering_tests"] and s["name"] != "<module>" \
                    and not lost_for_sym:
                # When a lost-cover note fires it already states the
                # cover is gone, more precisely; do not duplicate it
                # with the generic note for the same symbol.
                notes.append({
                    "kind": "no-covering-test", "path": path,
                    "symbol": s["qualified"],
                    "text": f"{path}: no covering test found for symbol "
                            f"{s['qualified']}",
                })
        for entry in rep.get("lost_covering_tests", []):
            if entry["file_level_only"]:
                notes.append({
                    "kind": "covering-test-deleted"
                            if entry["how"] == "deleted"
                            else "covering-test-removed",
                    "path": path,
                    "symbol": None,
                    "text": f"{path}: covering test {entry['path']} was "
                            f"{entry['how']} in this diff; it covered this "
                            f"file at import level (method: "
                            f"{entry['method']})",
                })
        if rep["status"] == "deleted":
            from .scanner import is_test_file
            if is_test_file(path):
                notes.append({
                    "kind": "test-deleted", "path": path, "symbol": None,
                    "text": f"{path}: this test file was deleted by the change; "
                            f"tests deleted in a diff no longer cover anything",
                })
    return notes


# ---------------------------------------------------------------------------
# Pack export
# ---------------------------------------------------------------------------

def _mode_for(path: str, analysis: dict, entries: dict) -> str | None:
    changed = {c["path"]: c for c in analysis["changed"]}
    if path in changed:
        return "exclude" if changed[path]["status"] == "deleted" else "full"
    if path in analysis["covering_tests_all"]:
        return "full"
    dist = analysis["distances"].get(path)
    if dist is None or dist > 2:
        return None
    entry = entries.get(path)
    if entry is not None and entry.language == "markdown":
        return "headings"
    return MODE_FOR_DISTANCE[dist]


def build_pack(project: str | Path, out: str | Path, inp: ChangeInput,
               profile: ScopeProfile, fit: int | None = None) -> dict:
    """Write a review pack to ``out`` and return its summary dict.

    The returned dict has ``out``, ``scope`` (the scope.json content),
    and ``fit_ok``. When ``fit`` is given and cannot be met without
    downgrading a changed file or covering test, the pack is still
    written and ``fit_ok`` is False.
    """
    root = Path(project).expanduser().resolve()
    out = Path(out)
    analysis = analyse(root, inp, profile)
    scan_result: ScanResult = analysis["scan"]
    entries = scan_result.by_path()
    distances: dict[str, int] = analysis["distances"]

    modes: dict[str, str] = {}
    for path in entries:
        mode = _mode_for(path, analysis, entries)
        if mode is not None:
            modes[path] = mode
    # deleted changed files are not on disk; add them as exclude rows
    for rep in analysis["changed"]:
        if rep["status"] == "deleted":
            modes[rep["path"]] = "exclude"

    def slice_all(mode_map: dict[str, str]) -> list[dict]:
        recs: list[dict] = []
        for path in sorted(mode_map):
            mode = mode_map[path]
            change = next((c for c in inp.changes if c.path == path), None)
            if change is not None and change.status == "deleted":
                base_text = inp.base_content(root, change) or ""
                from .scanner import language_for
                lang = language_for(path)
                recs.append({
                    "path": path, "mode": "exclude", "language": lang,
                    "package": "",
                    "original_tokens": estimate_tokens(base_text, lang),
                    "sliced_tokens": 0,
                    "sha256": hashlib.sha256(b"").hexdigest(),
                    "text": "",
                })
                continue
            text = None
            if change is not None:
                text = inp.head_content(root, change)
            if text is None:
                entry = entries[path]
                text = read_text(entry.abspath)
            result = slice_text(path, text, mode)
            recs.append({
                "path": path, "mode": mode, "language": result.language,
                "package": "",
                "original_tokens": result.original_tokens,
                "sliced_tokens": result.sliced_tokens,
                "sha256": hashlib.sha256(result.text.encode("utf-8")).hexdigest(),
                "text": result.text,
            })
        return recs

    records = slice_all(modes)
    total = sum(r["sliced_tokens"] for r in records)
    fit_report = None
    if fit is not None:
        before = total
        ladder = [
            (2, "interfaces", "exclude"),
            (1, "signatures", "interfaces"),
            (1, "interfaces", "exclude"),
            (2, "signatures", "exclude"),  # unreachable normally; kept for safety
        ]
        steps: list[str] = []
        for dist_want, from_mode, to_mode in ladder:
            if total <= fit:
                break
            changed_any = False
            for path in list(modes):
                if modes[path] != from_mode:
                    continue
                if distances.get(path) != dist_want:
                    continue
                if path in analysis["covering_tests_all"]:
                    continue
                modes[path] = to_mode
                changed_any = True
                steps.append(f"{path}: {from_mode} -> {to_mode}")
            if changed_any:
                records = slice_all(modes)
                total = sum(r["sliced_tokens"] for r in records)
        fit_report = {
            "requested_tokens": fit, "before_tokens": before,
            "after_tokens": total, "ok": total <= fit, "steps": steps,
            "note": "changed files and covering tests are never downgraded by --fit",
        }

    total_original = sum(r["original_tokens"] for r in records)
    manifest_files = [{k: r[k] for k in
                       ("path", "mode", "language", "package",
                        "original_tokens", "sliced_tokens", "sha256")}
                      for r in records]
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "tool": "ghostscope",
        "version": __version__,
        "preset": None,
        "generated_at": generated_at,
        "root": str(root),
        "token_method": METHOD,
        "total_original_tokens": total_original,
        "total_sliced_tokens": total,
        "total_saved_tokens": total_original - total,
        "files": manifest_files,
        "packages": [],
        "scope_sidecar": "scope.json",
    }
    if fit_report is not None:
        manifest["fit"] = fit_report

    reading_order = _reading_order(analysis, modes)
    scope = {
        "tool": "ghostscope",
        "version": __version__,
        "generated_at": generated_at,
        "input": {"mode": inp.mode, "base": inp.base, "head": inp.head},
        "transitive_caller_depth_cap": TRANSITIVE_DEPTH_CAP,
        "totals": {
            "repo_tokens_estimate": analysis["repo_total_tokens"],
            "diff_tokens_estimate": estimate_tokens(inp.diff_text, "text"),
            "pack_tokens_estimate": total,
            "pack_original_tokens_estimate": total_original,
            "changed_files": len(analysis["changed"]),
            "pack_files": len(records),
            "lost_covering_tests": sum(
                len(c.get("lost_covering_tests", []))
                for c in analysis["changed"]),
        },
        "changed": analysis["changed"],
        "files": [
            {"path": r["path"], "mode": r["mode"],
             "distance": distances.get(r["path"]),
             "risk_score": next((c["risk_score"] for c in analysis["changed"]
                                 if c["path"] == r["path"]), 0),
             "risk_reasons": next((c["risk_reasons"] for c in analysis["changed"]
                                   if c["path"] == r["path"]), []),
             "covering_test": r["path"] in analysis["covering_tests_all"]}
            for r in records
        ],
        "reading_order": reading_order,
        "notes": analysis["notes"],
        "fit": fit_report,
        "token_method": METHOD,
        "labels": {
            "token_counts": "estimates, not exact tokenizer counts",
            "non_python_symbols": "parser-lite (regex by line)",
            "covering_tests_non_python": "heuristic (name/import based)",
            "lost_covering_tests": "reconstructed from the base side of "
                                   "the diff for test files the diff "
                                   "deleted or edited; symbol links are "
                                   "call-proven, import-only cover is "
                                   "reported at file level",
        },
    }

    out.mkdir(parents=True, exist_ok=True)
    files_dir = out / "files"
    prompt_parts: list[str] = []
    for r in records:
        if r["mode"] == "exclude" or not r["text"]:
            continue
        dest = files_dir / r["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r["text"].encode("utf-8"))
        prompt_parts.append(f"\n\n## File: {r['path']} (mode: {r['mode']})\n\n```\n{r['text'].rstrip()}\n```\n")
    prompt = (
        "# GhostScope review pack\n\n"
        f"Estimated tokens: {total}. Token counts are estimates, "
        "see manifest.json for the method.\n"
        + "".join(prompt_parts)
    )
    (out / "PROMPT.md").write_text(prompt, encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "scope.json").write_text(
        json.dumps(_json_safe(scope), indent=2) + "\n", encoding="utf-8")
    (out / "REVIEW.md").write_text(
        render_review(analysis, scope, modes), encoding="utf-8")
    return {"out": str(out), "manifest": manifest, "scope": scope,
            "analysis": analysis, "fit_ok": (fit_report["ok"] if fit_report else True)}


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()
                if k not in ("scan", "graph")}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, set):
        return sorted(obj)
    return obj


def _reading_order(analysis: dict, modes: dict[str, str]) -> list[dict]:
    changed = {c["path"]: c for c in analysis["changed"]}
    items: list[dict] = []
    for path, mode in modes.items():
        if mode == "exclude":
            continue
        rep = changed.get(path)
        collapsed = bool(rep and (rep["is_generated"] or rep["is_vendored"]
                                  or rep["is_minified"]))
        items.append({
            "path": path, "mode": mode,
            "distance": analysis["distances"].get(path),
            "risk_score": rep["risk_score"] if rep else 0,
            "risk_reasons": rep["risk_reasons"] if rep else [],
            "collapsed_generated_or_vendored": collapsed,
            "covering_test": path in analysis["covering_tests_all"],
            "changed": rep is not None,
        })
    # riskiest first; generated/vendored changed files collapse to
    # the end of the reading order (listed, not hidden)
    items.sort(key=lambda i: (i["collapsed_generated_or_vendored"],
                              -i["risk_score"], i["path"]))
    for idx, item in enumerate(items, 1):
        item["order"] = idx
    return items


def render_review(analysis: dict, scope: dict, modes: dict[str, str]) -> str:
    """Render REVIEW.md: totals, riskiest-first reading order, and notes."""
    totals = scope["totals"]
    lines: list[str] = []
    lines.append("# GhostScope review pack")
    lines.append("")
    lines.append("Facts only. This pack prepares reading for a review; "
                 "it does not approve, request changes, or comment.")
    lines.append("")
    lines.append("## Totals (all token counts are estimates)")
    lines.append("")
    lines.append(f"- Repository total: {totals['repo_tokens_estimate']} estimated tokens")
    lines.append(f"- Raw diff: {totals['diff_tokens_estimate']} estimated tokens")
    lines.append(f"- This pack: {totals['pack_tokens_estimate']} estimated tokens "
                 f"(from {totals['pack_original_tokens_estimate']} across "
                 f"{totals['pack_files']} packed files)")
    lines.append(f"- Changed files: {totals['changed_files']}")
    if scope.get("fit"):
        f = scope["fit"]
        lines.append(f"- Fit budget: {f['requested_tokens']} tokens, "
                     f"{'met' if f['ok'] else 'NOT met'} "
                     f"(before {f['before_tokens']}, after {f['after_tokens']}). "
                     "Changed files are never downgraded by fit.")
    lines.append("")
    lines.append("## Risk list (highest first, reasons always shown)")
    lines.append("")
    ranked = sorted(analysis["changed"], key=lambda c: -c["risk_score"])
    for rep in ranked:
        reasons = "; ".join(rep["risk_reasons"]) or "no risk signals found"
        lines.append(f"- {rep['path']} (score {rep['risk_score']}): {reasons}")
        for s in rep["symbols"]:
            if s["risk_reasons"]:
                lines.append(f"  - {s['qualified']}: {'; '.join(s['risk_reasons'])}")
    lines.append("")
    lines.append("## Change summary by file")
    lines.append("")
    for rep in analysis["changed"]:
        lines.append(f"### {rep['path']} ({rep['status']}, +{rep['added_lines']} "
                     f"-{rep['deleted_lines']}, {rep['language']}, "
                     f"symbols by {rep['method']})")
        if rep["symbols"]:
            for s in rep["symbols"]:
                callers = s.get("caller_count", 0)
                lines.append(f"- {s['qualified']} ({s['kind']}): {callers} callers")
        else:
            lines.append("- No symbols mapped for this file.")
        if rep["covering_tests"]:
            for cov in rep["covering_tests"]:
                lines.append(f"- Covering test: {cov['path']} "
                             f"({'; '.join(cov['reasons'])}; method: {cov['method']})")
        else:
            lines.append("- No covering tests found for this file. "
                         "That is stated plainly: review this change "
                         "without test cover behind it.")
        for lost in rep.get("lost_covering_tests", []):
            covered = ", ".join(lost["symbols"]) if lost["symbols"] \
                else "this file (import-level cover)"
            lines.append(f"- Lost covering test: {lost['path']} "
                         f"({lost['how']} in this diff; covered: {covered}; "
                         f"method: {lost['method']})")
        if rep["secret_findings"]:
            for fnd in rep["secret_findings"]:
                lines.append(f"- Secret-shaped line added at line {fnd['line']} "
                             f"(type: {fnd['type']}); value not shown.")
        lines.append("")
    lines.append("## Reading order (riskiest first)")
    lines.append("")
    for item in scope["reading_order"]:
        tag = []
        if item["changed"]:
            tag.append("changed")
        if item["covering_test"]:
            tag.append("covering test")
        if item["collapsed_generated_or_vendored"]:
            tag.append("generated/vendored, collapsed to the end")
        dist = item["distance"]
        lines.append(f"{item['order']}. {item['path']} (mode: {item['mode']}, "
                     f"distance: {dist}, risk score: {item['risk_score']}"
                     f"{', ' + ', '.join(tag) if tag else ''})")
    lines.append("")
    lines.append("## Factual notes")
    lines.append("")
    if analysis["notes"]:
        for note in analysis["notes"]:
            lines.append(f"- {note['text']}")
    else:
        lines.append("- None.")
    lines.append("")
    lines.append("## Labels and limits")
    lines.append("")
    lines.append("- Token counts are estimates (BPE-like split v2, per-language "
                 "calibrated), not exact tokenizer counts.")
    lines.append("- Python symbols and calls are exact (stdlib ast). Other "
                 "languages are parser-lite (regex by line) and labelled as such.")
    lines.append("- Covering tests for non-Python files are heuristic "
                 "(name/import based), not proven.")
    lines.append("- Lost covering tests are reconstructed from the base "
                 "side of the diff for test files the diff deleted or "
                 "edited. Symbol links are call-proven; import-only "
                 "cover is reported at file level, not guessed onto a "
                 "symbol.")
    lines.append(f"- Transitive callers are capped at depth "
                 f"{TRANSITIVE_DEPTH_CAP}.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Explain
# ---------------------------------------------------------------------------

def explain_from_scope(scope: dict, path: str) -> dict:
    """Explain ``path`` from a pack's parsed scope.json.

    Returns whether the file is in the pack and, if so, its mode,
    graph distance, risk score and reasons; if not, a plain reason.
    """
    for f in scope.get("files", []):
        if f["path"] == path:
            return {"path": path, "in_pack": True, "mode": f["mode"],
                    "distance": f.get("distance"),
                    "risk_score": f.get("risk_score"),
                    "risk_reasons": f.get("risk_reasons", []),
                    "covering_test": f.get("covering_test", False)}
    return {"path": path, "in_pack": False,
            "reason": "not a changed file, not a covering test, and not "
                      "within graph distance 2 of a changed file"}
