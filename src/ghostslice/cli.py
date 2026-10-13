"""GhostSlice command line.

Commands:
  ghostslice scan         <path> [--json] [--model ID] [--timing] [--no-cache]
  ghostslice graph        <path> [--json]
  ghostslice slice        <path> --mode MODE -o <dir> [--no-cache]
  ghostslice task         <path> (--task "words" | --diff) [--budget N] [--fit N] -o <bundle> [--preset P]
  ghostslice export       <path> -o <bundle> [--mode MODE] [--model ID] [--preset P] [--fit N] [--exclude-secrets] [--redact] [--auto-shrink] [--symbols SPEC] [--timing] [--no-cache] [--workers N]
  ghostslice symbols      <path> [file] [--json]
  ghostslice calls        <path> [file] [--json] [--dead]
  ghostslice watch        <path> [--export] [-o <bundle>] [--interval S] [--debounce S] [--once] [--max-events N] [--fit N] [--redact] [--auto-shrink]
  ghostslice check-budget <path> [--max-tokens N]
  ghostslice lint         <path> [--json] [--strict]
  ghostslice init         <path> [--yes] [--force] [--dry-run] [--budget N] [--model ID]
  ghostslice cache        stats|clear <path>
  ghostslice check        <bundle>
  ghostslice diff         <bundleA> <bundleB> [--json]
  ghostslice history      <path> [--json] [--trend] [--model ID]
  ghostslice mcp                              (stdio MCP server, see mcp_server.py)
  ghostslice serve        <path> --port 8765
  ghostslice prices

A `.ghostslice.json` profile in the project root is loaded automatically
(ignores, per-glob modes, model, budget_tokens, entry_points, preset).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from . import __version__
from .cache import cached_slice_text, clear_cache, open_cache
from .cache import cache_stats as _cache_stats
from .exporter import SLICABLE, build_bundle, estimate_context_tokens, validate_bundle
from .graph import build_graph, importers_of, recommendations
from .ledger import analytics as ledger_analytics
from .ledger import summary as ledger_summary
from .pricing import estimate_cost, get_model, load_prices, models, preflight
from .profile import PRESETS, load_profile
from .scanner import scan
from .secrets_scan import RedactionError, scan_scan_result, scan_text
from .selection import select_for_diff, select_for_task, select_for_task_breakdown
from .configslice import CONFIG_LANGUAGES
from .slicer import MODES, slice_text
from .tokens import METHOD as TOKEN_METHOD


def _print_history_trend(data) -> None:
    """--trend block for `ghostslice history`: per-run table with
    deltas, aggregates, ASCII charts. $ figures use the payload's
    model block (input rates; prices labelled as of their snapshot)."""
    runs = data["runs_detail"]
    if not runs:
        print("\nNo recorded runs yet — nothing to trend.")
        return
    model = data.get("model") or {}
    print(f"\nTrend ({len(runs)} run(s), oldest first; $ at "
          f"{model.get('name', model.get('id'))}, {model.get('prices_note', '')}):")
    header = (f"{'#':>3}  {'at (UTC)':<19}  {'kind':<7}  {'before':>9} -> "
              f"{'after':>9}  {'saved':>9}  {'saved%':>6}  {'Δafter':>8}  "
              f"{'$ saved':>8}  {'$ cum.':>8}")
    print(header)
    for r in runs:
        at = (r["at"] or "?")[:19].replace("T", " ")
        delta = "—" if r["delta_after_tokens"] is None else f"{r['delta_after_tokens']:+,}"
        print(f"{r['index'] + 1:>3}  {at:<19}  {(r['kind'] or '?'):<7}  "
              f"{r['before_tokens']:>9,} -> {r['after_tokens']:>9,}  "
              f"{r['saved_tokens']:>9,}  {r['saved_pct']:>5.1f}%  {delta:>8}  "
              f"{r.get('saved_cost_usd', 0.0):>8.4f}  "
              f"{r.get('cumulative_saved_cost_usd', 0.0):>8.4f}")
    agg = data["aggregates"]
    print(f"\nSaved % per run: mean {agg['mean_saved_pct']:.2f}%, "
          f"median {agg['median_saved_pct']:.2f}%")
    if agg["best_run"] and agg["worst_run"]:
        b, w = agg["best_run"], agg["worst_run"]
        print(f"Best run: #{b['index'] + 1} saved {b['saved_tokens']:,} "
              f"({b['saved_pct']:.1f}%); worst run: #{w['index'] + 1} saved "
              f"{w['saved_tokens']:,} ({w['saved_pct']:.1f}%)")
    if agg["after_change_tokens"] is not None:
        pct = agg["after_change_pct"]
        pct_txt = f", {pct:+.1f}%" if pct is not None else ""
        print(f"Context size (after tokens), first -> last run: "
              f"{agg['first_after_tokens']:,} -> {agg['last_after_tokens']:,} "
              f"({agg['after_change_tokens']:+,} tokens{pct_txt})")
    if agg["span_days"] is not None:
        if agg["span_days"] < 1:
            print(f"Span: {agg['span_days'] * 24:.1f} hour(s)")
        elif agg["runs_per_week"] is not None:
            print(f"Span: {agg['span_days']:.1f} day(s), "
                  f"~{agg['runs_per_week']:.1f} run(s)/week")
        else:
            print(f"Span: {agg['span_days']:.1f} day(s)")
    if agg.get("total_saved_cost_usd") is not None:
        print(f"Total estimated $ saved: ~${agg['total_saved_cost_usd']:.4f}")
    charts = data["charts"]
    saved_vals = [r["saved_tokens"] for r in runs]
    after_vals = [r["after_tokens"] for r in runs]
    print(f"\nSaved tokens per run:  {charts['saved_tokens_sparkline']}  "
          f"(min {min(saved_vals):,}, max {max(saved_vals):,})")
    print(f"After tokens per run:  {charts['after_tokens_sparkline']}  "
          f"(min {min(after_vals):,}, max {max(after_vals):,})")


def _print_wrapper(manifest) -> None:
    """Print the v0.16 wrapper lines: the artifact CONTAINS the
    slices, so report its own total and the markup overhead beyond
    the sliced total separately — the manifest totals themselves
    count file slices only and never fold the wrapper in."""
    for name, info in (manifest.get("wrapper_artifacts") or {}).items():
        print(f"Wrapper: {name} is ~{info['estimated_tokens']:,} estimated tokens "
              f"in total ({info['bytes']:,} bytes), of which "
              f"~{info['overhead_estimated_tokens']:,} is format overhead beyond "
              "the sliced totals above; manifest totals count the file slices only.")


def _print_redaction(manifest, exclude_secrets_on: bool = False) -> None:
    """Print the v0.17 redaction summary from the manifest block:
    what was replaced, and — loudly — anything left in place."""
    block = manifest.get("redaction")
    if not block:
        return
    print(f"Redacted {block['values_redacted']} secret value(s) across "
          f"{block['files_affected']} file(s) (values replaced in place; files kept).")
    if block["left_in_place"]:
        print(f"WARNING: {block['left_in_place']} finding(s) of kind(s) "
              f"{', '.join(block['leftover_kinds'])} were left in place "
              "(kinds the redactor does not replace); review before sharing.")
    if exclude_secrets_on:
        print("Note: --exclude-secrets is also on: files flagged by the secret "
              "guard were excluded entirely (exclusion wins); redaction covered "
              "the remaining files.")


def _print_symbols(manifest) -> None:
    """Print the v0.18 symbol-selection report from the manifest:
    what was requested, how much matched where, and — loudly — the
    entries that matched in more than one file (all matches ship)."""
    block = manifest.get("symbols")
    if not block:
        return
    print(f"Symbols: {len(block['requested'])} requested; matched in "
          f"{len(block['files'])} file(s) (files with no match are excluded; "
          "profile entry points keep their mode)")
    for entry, found in block["matches"].items():
        where = ", ".join(f"{m['path']}:{m['symbol']}" for m in found)
        print(f"  {entry}: {len(found)} match(es): {where}")
    for entry in block["ambiguous"]:
        files = sorted({m["path"] for m in block["matches"][entry]})
        print(f"  note: {entry!r} matched in {len(files)} files "
              f"({', '.join(files)}); all matches included")
    for path in block.get("excluded_by_secrets", []):
        print(f"  note: {path} matched but was excluded by "
              "--exclude-secrets (exclusion wins)")


def _scan_with_profile(path, profile, cache=None):
    matcher = profile.is_ignored if profile.path else None
    return scan(path, ignore_matcher=matcher, cache=cache)


def _print_timing(timing, stream=None) -> None:
    """Print a build_bundle timing dict (--timing): phase seconds
    plus the content-cache counters for the run."""
    stream = stream or sys.stdout
    parts = [f"scan {timing['scan_s']:.3f}s",
             f"resolve {timing['resolve_s']:.3f}s",
             f"slice {timing['slice_s']:.3f}s",
             f"render {timing['render_s']:.3f}s"]
    print(f"Timing: {' + '.join(parts)} = {timing['total_s']:.3f}s "
          f"(workers: {timing['workers']})", file=stream)
    c = timing.get("cache")
    if c is None:
        print("Cache: off", file=stream)
    else:
        print(f"Cache: {c['hits']} hit(s), {c['misses']} miss(es), "
              f"{c['stores']} store(s), {c['corrupt']} corrupt, "
              f"{c['evictions']} eviction(s)", file=stream)


def _print_scan_timing(t0, t1, cache, stream=None) -> None:
    """`scan --timing`: the scan phase vs everything after it
    (graph, recommendations, secrets, duplicates, rendering)."""
    stream = stream or sys.stdout
    total = time.perf_counter() - t0
    print(f"Timing: scan {t1 - t0:.3f}s + analysis/render "
          f"{total - (t1 - t0):.3f}s = {total:.3f}s", file=stream)
    if cache is None:
        print("Cache: off", file=stream)
    else:
        c = cache.counters()
        print(f"Cache: {c['hits']} hit(s), {c['misses']} miss(es), "
              f"{c['stores']} store(s), {c['corrupt']} corrupt", file=stream)


def _with_dead_symbol_recs(result, graph, profile, recs):
    """Append v0.19 dead-symbol candidates to a recommendation list
    (the `scan` / `graph` surfaces). graph.recommendations itself is
    unchanged — lint consumes it and gains nothing this round. A
    call-graph failure must never break a scan, so this is guarded
    the same way graph.recommendations guards its duplicate pass."""
    try:
        from .callgraph import dead_symbol_recommendations
        extra = dead_symbol_recommendations(result, profile, graph)
    except Exception:
        return recs
    if not extra:
        return recs
    merged = list(recs) + extra
    merged.sort(key=lambda r: r["tokens"], reverse=True)
    return merged


def _warn_secrets(findings, heading="WARNING: possible secrets detected") -> None:
    if not findings:
        return
    print(f"\n{heading} ({len(findings)} finding(s), values redacted):", file=sys.stderr)
    for f in findings:
        print(f"  {f['path']}:{f['line']}  {f['type']}  ({f['redacted']})", file=sys.stderr)
    print("  Review these files before sharing the bundle. "
          "Use --exclude-secrets (export) to force-exclude flagged files, "
          "or --redact to replace the values in place.", file=sys.stderr)


def _print_fit(fit_report) -> bool:
    """Print the --fit report; return True when the bundle fitted."""
    if not fit_report:
        return True
    steps = fit_report["steps"]
    step_text = ", ".join(f"{k} x{n}" for k, n in steps.items()) if steps else "no downgrades needed"
    print(f"Fit target: {fit_report['fit_tokens']:,} estimated tokens: "
          f"{fit_report['before_tokens']:,} -> {fit_report['after_tokens']:,} "
          f"({'fitted' if fit_report['fitted'] else 'COULD NOT FIT'})")
    if "redacted_after_tokens" in fit_report:
        print(f"  after redaction: {fit_report['redacted_after_tokens']:,} estimated "
              "tokens (the ladder judged pre-redaction slices; manifest totals "
              "are post-redaction)")
    print(f"  downgrades: {step_text}")
    if not fit_report["fitted"]:
        print(f"WARNING: could not fit the bundle into {fit_report['fit_tokens']:,} estimated tokens "
              f"(best achievable {fit_report['after_tokens']:,}); the bundle was still written.",
              file=sys.stderr)
    return fit_report["fitted"]


def _print_scan(result, model=None, prices=None, recs=None, secrets=None, dups=None,
                packages=None, ws_missing=None, ws_warnings=None) -> None:
    print(f"Project: {result.root}")
    print(f"Files: {len(result.files)}  Estimated tokens: {result.total_tokens:,}")
    print(f"{'tokens':>9}  {'lines':>6}  file")
    for f in result.files[:200]:
        flags = []
        if f.is_test:
            flags.append("test")
        if f.is_lockfile:
            flags.append("lockfile")
        if f.is_generated:
            flags.append("generated")
        if f.is_minified:
            flags.append("minified")
        if f.is_vendored:
            flags.append("vendored")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"{f.tokens:>9,}  {f.lines:>6}  {f.path}{suffix}")
    if len(result.files) > 200:
        print(f"... and {len(result.files) - 200} more files")
    if packages and len(packages) > 1:
        print(f"\nPackages ({len(packages)}):")
        for p in packages:
            src = f", {p['source']}" if p["source"] else ""
            print(f"  {p['label']}  [{p['kind']}{src}]: {p['files']} file(s), "
                  f"{p['tokens']:,} estimated tokens ({p['share']:.1f}% of total)")
    if ws_missing:
        print("\nWorkspace members declared but missing on disk:")
        for m in ws_missing:
            print(f"  {m}")
    if ws_warnings:
        print("\nWorkspace warnings:")
        for w in ws_warnings:
            print(f"  {w}")
    if model is not None:
        cost = estimate_cost(result.total_tokens, model)
        print(f"\nPre-flight (input cost, prices as of {prices.get('as_of')} from local prices.json, not live):")
        print(f"  {model['name']}: ~${cost:.4f} for {result.total_tokens:,} estimated tokens")
    if secrets:
        print(f"\nSecrets warning ({len(secrets)} finding(s), values redacted):")
        for f in secrets[:20]:
            print(f"  {f['path']}:{f['line']}  {f['type']}  ({f['redacted']})")
        print("  Run `ghostslice secrets <path>` for the full list; export with --exclude-secrets to force-exclude flagged files.")
    if dups and (dups.get("exact") or dups.get("near")):
        print("\nDuplicates:")
        for g in dups.get("exact", []):
            print(f"  exact: {', '.join(g['files'])}  (up to {g['potential_savings']:,} estimated tokens)")
        for pair in dups.get("near", []):
            print(f"  near ({pair['similarity']}): {' <-> '.join(pair['files'])}")
    if recs:
        total = sum(r["potential_savings"] for r in recs)
        print(f"\nPrune recommendations ({len(recs)} candidates, up to {total:,} estimated tokens):")
        for r in recs[:15]:
            print(f"  {r['tokens']:>9,}  {r['path']}  ({r['reason']})")
        print("  Recommendations to review, not instructions: dynamic imports can hide real use.")


def _print_calls(payload, single=None, dead=False) -> None:
    c = payload["counts"]
    print(f"Call graph for {payload['root']} (Python only; "
          "token counts are estimates)")
    print(f"Symbols: {c['symbols']} in {c['files']} python file(s); "
          f"call sites: {c['calls']} "
          f"(exact {c['exact']}, heuristic {c['heuristic']}, "
          f"attribute {c['attribute']}, external {c['external']}, "
          f"unresolved {c['unresolved']}); "
          f"references: {c['references']}")
    if payload["skipped_files"]:
        print(f"Skipped (unparseable, no verdict): "
              f"{', '.join(payload['skipped_files'])}")
    symbols = payload["symbols"]
    if single:
        by_id = {s["id"]: s for s in symbols}
        callers: dict[str, list] = {}
        callees: dict[str, list] = {}
        for e in payload["edges"]:
            if e["kind"] == "reference":
                continue
            callees.setdefault(e["caller"], []).append(e)
            callers.setdefault(e["callee"], []).append(e)
        rows = [s for s in symbols if s["path"] == single]
        if not rows:
            print(f"{single}: no python symbols")
        for s in rows:
            print(f"\n{s['qualified']} ({s['kind']}, "
                  f"lines {s['start_line']}-{s['end_line']}, "
                  f"~{s['tokens']:,} tokens, fan-in {s['fan_in']}, "
                  f"references {s['references']})")
            for e in sorted(callees.get(s["id"], []),
                            key=lambda e: e["callee"]):
                callee = by_id.get(e["callee"])
                label = callee["id"] if callee else e["callee"]
                print(f"  calls [{e['kind']}] {label} (x{e['sites']})")
            for e in sorted(callers.get(s["id"], []),
                            key=lambda e: e["caller"]):
                print(f"  called by [{e['kind']}] {e['caller']} "
                      f"(x{e['sites']})")
    elif not dead:
        ranked = sorted((s for s in symbols if s["fan_in"]),
                        key=lambda s: (-s["fan_in"], s["id"]))
        if ranked:
            print("\nMost-called symbols (fan-in):")
            for s in ranked[:15]:
                print(f"  {s['fan_in']:>4}  {s['id']} ({s['kind']})")
    if dead or not single:
        dead_rows = payload["dead"]
        if single:
            dead_rows = [d for d in dead_rows if d["path"] == single]
        if dead:
            print(f"\nDead-function candidates ({len(dead_rows)}):")
            for d in dead_rows:
                print(f"  {d['path']}:{d['start_line']}-{d['end_line']}  "
                      f"{d['qualified']} ({d['kind']}, "
                      f"~{d['tokens']:,} estimated tokens)")
            total = sum(d["tokens"] for d in dead_rows)
            print(f"Total: ~{total:,} estimated tokens. "
                  f"{payload['note']}.")
        elif dead_rows:
            print(f"\n{len(dead_rows)} dead-function candidate(s); "
                  "run with --dead to list them.")


def _print_lint(payload) -> None:
    findings = payload["findings"]
    print(f"Lint: {payload['root']} (token counts are estimates)")
    if not findings:
        print("  No findings. The default export selection looks clean.")
    for f in findings:
        where = f["path"] or "(project)"
        print(f"  [{f['severity']}] {f['rule']} {where} — {f['message']}")
        print(f"          action: {f['action']}")
    c = payload["counts"]
    print(f"Findings: {c['error']} error, {c['warn']} warn, {c['info']} info; "
          f"flagged files hold ~{payload['flagged_tokens']:,} estimated tokens; "
          f"up to ~{payload['potential_savings']:,} recoverable.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostslice", description="GhostSlice: agent context & prompt optimizer (token counts are estimates)")
    parser.add_argument("--version", action="version", version=f"ghostslice {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="scan a project and rank files by estimated token cost")
    p_scan.add_argument("path")
    p_scan.add_argument("--json", action="store_true")
    p_scan.add_argument("--model", default=None, help="model id from prices.json, for a cost line")
    p_scan.add_argument("--timing", action="store_true",
                        help="print a phase breakdown (scan vs analysis) and cache counters")
    p_scan.add_argument("--no-cache", action="store_true",
                        help="do not consult or fill the .ghostslice-cache content cache")

    p_graph = sub.add_parser("graph", help="import graph + prune recommendations")
    p_graph.add_argument("path")
    p_graph.add_argument("--json", action="store_true")

    p_slice = sub.add_parser("slice", help="slice one file or a whole tree into an output dir")
    p_slice.add_argument("path")
    p_slice.add_argument("--mode", choices=MODES, default="signatures")
    p_slice.add_argument("-o", "--out", required=True)
    p_slice.add_argument("--no-cache", action="store_true",
                         help="do not consult or fill the .ghostslice-cache content cache "
                              "(tree slices only; a single file is never cached)")

    p_task = sub.add_parser("task", help="task-focused context: keyword or git-diff selection, exported as a bundle")
    p_task.add_argument("path")
    p_task.add_argument("--task", default=None, help="task description words to score files by")
    p_task.add_argument("--diff", action="store_true", help="select git-changed files + direct dependencies")
    p_task.add_argument("--budget", type=int, default=None, help="max sliced tokens for keyword selection")
    p_task.add_argument("--fit", type=int, default=None, metavar="N",
                        help="auto-fit: downgrade slice modes until the bundle fits N estimated tokens")
    p_task.add_argument("-o", "--out", required=True)
    p_task.add_argument("--preset", choices=PRESETS, default=None)
    p_task.add_argument("--model", default="claude-sonnet")
    p_task.add_argument("--redact", action=argparse.BooleanOptionalAction,
                        default=None,
                        help="replace flagged secret values in slices with "
                             "[REDACTED:...] placeholders instead of shipping them "
                             "(--no-redact overrides a profile's \"redact\": true; "
                             "default: the profile setting)")

    p_export = sub.add_parser("export", help="write an agent context bundle")
    p_export.add_argument("path")
    p_export.add_argument("-o", "--out", required=True)
    p_export.add_argument("--mode", choices=MODES, default=None,
                          help="apply this mode to slicable files (default: signatures, tests stripped, lockfiles excluded)")
    p_export.add_argument("--preset", choices=PRESETS, default=None)
    p_export.add_argument("--model", default="claude-sonnet")
    p_export.add_argument("--exclude-secrets", action="store_true",
                          help="force-exclude files flagged by the secret guard")
    p_export.add_argument("--redact", action=argparse.BooleanOptionalAction,
                          default=None,
                          help="replace flagged secret values in slices with "
                               "[REDACTED:...] placeholders instead of shipping them "
                               "(--no-redact overrides a profile's \"redact\": true; "
                               "default: the profile setting). With --exclude-secrets, "
                               "exclusion wins for flagged files and redaction covers "
                               "the rest")
    p_export.add_argument("--auto-shrink", action="store_true",
                          help="exclude files detected as generated/vendored/minified "
                               "(explicit modes and profile modes still win; "
                               "also settable as \"auto_shrink\": true in the profile)")
    p_export.add_argument("--fit", type=int, default=None, metavar="N",
                          help="auto-fit: downgrade slice modes until the bundle fits N estimated tokens "
                               "(exit 1 if it cannot fit; the bundle is still written)")
    p_export.add_argument("--symbols", default=None, metavar="SPEC",
                          help="symbol-level selection: comma list of symbol names, "
                               "Class.method qualified names, file.py:name scoping, or "
                               "* globs; matched files ship with those symbols' bodies "
                               "plus signature context, other files are excluded "
                               "(cannot combine with --fit)")
    p_export.add_argument("--timing", action="store_true",
                          help="print a phase breakdown (scan/resolve/slice/render) and cache counters")
    p_export.add_argument("--no-cache", action="store_true",
                          help="do not consult or fill the .ghostslice-cache content cache")
    p_export.add_argument("--workers", type=int, default=None, metavar="N",
                          help="slice files on N threads (default: 1; measured no "
                               "faster for this workload under the GIL — see "
                               "BENCHMARKS.md — but output is identical for any N)")

    p_symbols = sub.add_parser("symbols", help="list a project's symbols (name, kind, lines, estimated tokens) for symbol-level slicing")
    p_symbols.add_argument("path")
    p_symbols.add_argument("file", nargs="?", default=None,
                           help="optional single file, relative to the project root")
    p_symbols.add_argument("--json", action="store_true")

    p_calls = sub.add_parser("calls", help="python call graph: who calls what, most-called symbols, dead-function candidates")
    p_calls.add_argument("path")
    p_calls.add_argument("file", nargs="?", default=None,
                         help="optional single file, relative to the project root: show callers/callees per symbol")
    p_calls.add_argument("--json", action="store_true")
    p_calls.add_argument("--dead", action="store_true",
                         help="list dead-function candidates (symbols no caller or reference reaches)")

    p_diff = sub.add_parser("diff", help="diff two bundles: mode changes, token deltas, added/removed files")
    p_diff.add_argument("bundle_a")
    p_diff.add_argument("bundle_b")
    p_diff.add_argument("--json", action="store_true")

    p_secrets = sub.add_parser("secrets", help="scan a project for likely secrets (exit 1 if findings; values redacted)")
    p_secrets.add_argument("path")
    p_secrets.add_argument("--json", action="store_true")

    p_report = sub.add_parser("report", help="write a standalone HTML report for a project")
    p_report.add_argument("path")
    p_report.add_argument("-o", "--out", required=True)
    p_report.add_argument("--model", default="claude-sonnet")

    p_explain = sub.add_parser("explain", help="explain why one file is included/excluded and how it is sliced")
    p_explain.add_argument("path")
    p_explain.add_argument("file", help="file path relative to the project root")
    p_explain.add_argument("--mode", choices=MODES, default=None,
                           help="explicit mode override to explain (as export --mode would apply)")

    p_watch = sub.add_parser("watch", help="watch a project: rescan on change, print estimated-token deltas, optionally re-export the bundle")
    p_watch.add_argument("path")
    p_watch.add_argument("-o", "--out", default=None,
                         help="bundle directory to rewrite on change (implies --export; default with --export: <project>/.claude_context)")
    p_watch.add_argument("--export", action="store_true",
                         help="write the bundle at startup and after every settled change")
    p_watch.add_argument("--interval", type=float, default=1.0,
                         help="poll interval in seconds (default 1.0)")
    p_watch.add_argument("--debounce", type=float, default=None,
                         help="quiet window in seconds before a change settles "
                              "(default: max(1.0, 2 x interval)); 0 settles on the first differing poll")
    p_watch.add_argument("--once", action="store_true",
                         help="take an initial snapshot, poll once after one interval, report any change, and exit")
    p_watch.add_argument("--max-events", type=int, default=None,
                         help="exit after N settled change events (scripting/tests)")
    p_watch.add_argument("--mode", choices=MODES, default=None,
                         help="with --export: apply this mode to slicable files, as in export")
    p_watch.add_argument("--preset", choices=PRESETS, default=None)
    p_watch.add_argument("--exclude-secrets", action="store_true",
                         help="with --export: force-exclude files flagged by the secret guard")
    p_watch.add_argument("--redact", action=argparse.BooleanOptionalAction,
                         default=None,
                         help="with --export: redact flagged secret values in place, "
                              "as in export --redact (default: the profile setting)")
    p_watch.add_argument("--auto-shrink", action="store_true",
                         help="with --export: exclude detected generated/vendored/minified "
                              "files, as in export --auto-shrink")
    p_watch.add_argument("--fit", type=int, default=None, metavar="N",
                         help="with --export: auto-fit the bundle to N estimated tokens, as in export --fit")

    p_init = sub.add_parser("init", help="analyze a project and generate a tuned .ghostslice.json profile")
    p_init.add_argument("path")
    p_init.add_argument("--yes", action="store_true",
                        help="accept the analysis as-is (also the behaviour on a non-TTY stdin)")
    p_init.add_argument("--force", action="store_true",
                        help="overwrite an existing .ghostslice.json")
    p_init.add_argument("--dry-run", action="store_true",
                        help="print the profile and its justifications; write nothing")
    p_init.add_argument("--budget", type=int, default=None, metavar="N",
                        help="budget_tokens to write (default: current sliced total x 1.25, rounded up)")
    p_init.add_argument("--model", default=None,
                        help="model id from prices.json to pin in the profile (default: omit)")

    p_lint = sub.add_parser("lint", help="lint the default export selection for context waste (rules L001-L010)")
    p_lint.add_argument("path")
    p_lint.add_argument("--json", action="store_true")
    p_lint.add_argument("--strict", action="store_true",
                        help="exit 1 on warnings too (default: exit 1 only on error-severity findings)")

    p_budget = sub.add_parser("check-budget", help="exit non-zero if the selected context exceeds a token budget (CI gate)")
    p_budget.add_argument("path")
    p_budget.add_argument("--max-tokens", type=int, default=None,
                          help="budget in sliced tokens (default: profile budget_tokens)")
    p_budget.add_argument("--mode", choices=MODES, default=None)

    p_check = sub.add_parser("check", help="validate a bundle against its manifest")
    p_check.add_argument("bundle")

    p_hist = sub.add_parser("history", help="savings ledger summary for a project")
    p_hist.add_argument("path")
    p_hist.add_argument("--json", action="store_true")
    p_hist.add_argument("--trend", action="store_true",
                        help="per-run trend table with deltas, aggregates, and ASCII charts")
    p_hist.add_argument("--model", default=None,
                        help="model id from prices.json for estimated $ saved "
                             "(default: profile model or claude-sonnet)")

    p_cal = sub.add_parser("calibrate", help="per-language-family token calibration report (raw vs calibrated estimates)")
    p_cal.add_argument("path")
    p_cal.add_argument("--json", action="store_true")

    p_cache = sub.add_parser("cache", help="inspect or clear the per-project content cache (.ghostslice-cache)")
    cache_sub = p_cache.add_subparsers(dest="cache_cmd", required=True)
    p_cache_stats = cache_sub.add_parser("stats", help="entry counts, bytes, and age of the cache")
    p_cache_stats.add_argument("path")
    p_cache_stats.add_argument("--json", action="store_true")
    p_cache_clear = cache_sub.add_parser("clear", help="delete the whole cache (it is derived data; it rebuilds on demand)")
    p_cache_clear.add_argument("path")

    sub.add_parser("mcp", help="run the stdio MCP server (JSON-RPC)")

    p_serve = sub.add_parser("serve", help="serve the local dashboard")
    p_serve.add_argument("path")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--host", default="127.0.0.1")

    sub.add_parser("prices", help="show the local, dated model price table")

    args = parser.parse_args(argv)
    prices = load_prices()

    if args.cmd == "prices":
        print(f"Local prices.json (as of {prices.get('as_of')}, not live): {prices.get('_path')}")
        for m in models(prices):
            print(f"  {m['id']:<16} input ${m['input_per_mtok_usd']}/Mtok  output ${m['output_per_mtok_usd']}/Mtok  {m['name']}")
        return 0

    if args.cmd == "mcp":
        from .mcp_server import run_stdio
        run_stdio()
        return 0

    if args.cmd == "diff":
        from .bundlediff import diff_bundles
        try:
            d = diff_bundles(args.bundle_a, args.bundle_b)
        except ValueError as exc:
            print(f"diff: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(d, indent=2))
            return 0
        t = d["totals"]
        print(f"Bundle diff: {args.bundle_a} -> {args.bundle_b}")
        print(f"Totals: original {t['original_from']:,} -> {t['original_to']:,} ({t['original_delta']:+,}); "
              f"sliced {t['sliced_from']:,} -> {t['sliced_to']:,} ({t['sliced_delta']:+,}) estimated tokens")
        for f in d["added"]:
            print(f"  added    {f['path']}  ({f['mode']}, {f['sliced_tokens']:,} sliced)")
        for f in d["removed"]:
            print(f"  removed  {f['path']}  ({f['mode']}, {f['sliced_tokens']:,} sliced)")
        for f in d["changed"]:
            mode_note = f"{f['mode_from']}->{f['mode_to']}" if f["mode_from"] != f["mode_to"] else f["mode_from"]
            print(f"  changed  {f['path']}  ({mode_note}; original {f['original_delta']:+,}, sliced {f['sliced_delta']:+,})")
        if not (d["added"] or d["removed"] or d["changed"]):
            print("  no changes")
        print(f"Unchanged files: {d['unchanged_count']}")
        return 0

    if args.cmd == "init":
        # Handled before the generic profile load: init must analyse
        # the project WITHOUT any existing profile's ignores/modes,
        # and it decides about overwriting that file itself.
        if args.budget is not None and args.budget <= 0:
            print("init: --budget must be > 0", file=sys.stderr)
            return 2
        if args.model is not None:
            try:
                get_model(prices, args.model)
            except KeyError:
                print(f"init: unknown model id: {args.model} "
                      f"(see `ghostslice prices`)", file=sys.stderr)
                return 2
        interactive = sys.stdin.isatty() and not args.yes
        if not args.yes and not interactive:
            print("init: stdin is not a terminal; running "
                  "non-interactively with the analysis defaults "
                  "(same as --yes).")
        from .init_wizard import run_init
        try:
            code, _payload = run_init(
                args.path, yes=args.yes, force=args.force,
                dry_run=args.dry_run, budget=args.budget,
                model_id=args.model, interactive=interactive)
        except FileNotFoundError:
            print(f"init: no such project: {args.path}", file=sys.stderr)
            return 2
        return code

    if args.cmd == "cache":
        # Handled before the generic profile load: the cache is
        # derived data and must be inspectable even for a project
        # whose profile is broken or absent.
        if not Path(args.path).is_dir():
            print(f"cache: no such project: {args.path}", file=sys.stderr)
            return 2
        if args.cache_cmd == "stats":
            stats = _cache_stats(args.path)
            if args.json:
                print(json.dumps(stats, indent=2))
                return 0
            if not stats["entries"]:
                print(f"Cache for {args.path}: empty (no .ghostslice-cache)")
                return 0
            print(f"Cache for {args.path}: {stats['entries']} entr(ies), "
                  f"{stats['bytes']:,} bytes in {stats['dir']}")
            for kind, info in stats["by_kind"].items():
                print(f"  {kind:<9} {info['entries']:>6} entr(ies), "
                      f"{info['bytes']:,} bytes")
            print(f"  oldest: {stats['oldest']}  newest: {stats['newest']}")
            return 0
        if args.cache_cmd == "clear":
            gone = clear_cache(args.path)
            if gone["existed"]:
                print(f"Cleared cache for {args.path}: "
                      f"{gone['removed_entries']} entr(ies), "
                      f"{gone['removed_bytes']:,} bytes removed")
            else:
                print(f"Cache for {args.path}: nothing to clear")
            return 0
        return 2

    # All remaining commands target a project path (or a bundle for check).
    target = getattr(args, "path", None) or getattr(args, "bundle", None)
    try:
        profile = load_profile(target) if target else load_profile(".")
    except ValueError as exc:
        if args.cmd == "lint":
            print(f"lint: invalid profile: {exc}", file=sys.stderr)
            return 2
        raise

    if profile.path:
        print(f"Profile: {profile.path}", file=sys.stderr)

    if args.cmd == "lint":
        from .lint import lint_exit_code, lint_project
        try:
            payload = lint_project(args.path, profile=profile)
        except FileNotFoundError:
            print(f"lint: no such project: {args.path}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(f"lint: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            _print_lint(payload)
        return lint_exit_code(payload, strict=args.strict)

    if args.cmd == "secrets":
        result = _scan_with_profile(args.path, profile)
        findings = scan_scan_result(result)
        if args.json:
            print(json.dumps({"findings": findings, "count": len(findings)}, indent=2))
        elif findings:
            print(f"Possible secrets in {args.path} ({len(findings)} finding(s), values redacted):")
            for f in findings:
                print(f"  {f['path']}:{f['line']}  {f['type']}  ({f['redacted']})")
        else:
            print("No likely secrets found.")
        return 1 if findings else 0

    if args.cmd == "calibrate":
        from .calibration import calibrate_project
        data = calibrate_project(args.path, profile)
        if args.json:
            print(json.dumps(data, indent=2))
            return 0
        print(f"Calibration for {data['root']} ({data['token_method']})")
        print(f"{'family':<12} {'files':>5} {'chars':>10} {'raw est.':>10} "
              f"{'calibrated':>11} {'chars/token':>11} {'factor':>6} {'target':>6}")
        for r in data["families"]:
            tgt = f"{r['target_chars_per_token']:.2f}" if r["target_chars_per_token"] else "-"
            print(f"{r['family']:<12} {r['files']:>5} {r['chars']:>10,} {r['raw_tokens']:>10,} "
                  f"{r['calibrated_tokens']:>11,} {r['implied_chars_per_token']:>11.2f} "
                  f"{r['factor']:>6.2f} {tgt:>6}")
        t = data["totals"]
        print(f"{'TOTAL':<12} {t['files']:>5} {t['chars']:>10,} {t['raw_tokens']:>10,} "
              f"{t['calibrated_tokens']:>11,} {t['implied_chars_per_token']:>11.2f}")
        print("Factors and targets are documented in src/ghostslice/tokens.py; "
              "implied chars/token = chars / calibrated estimate. All counts are estimates.")
        return 0

    if args.cmd == "report":
        from .report import write_report
        out = write_report(args.path, args.out, model_id=args.model or profile.model or "claude-sonnet")
        print(f"Report: {out}")
        return 0

    if args.cmd == "explain":
        from .duplicates import find_duplicates
        from .exporter import default_mode_for
        from .graph import importers_of as _imp_of
        result = _scan_with_profile(args.path, profile)
        rel = args.file.replace("\\", "/").lstrip("./")
        by_path = {f.path: f for f in result.files}
        entry = by_path.get(rel)
        if entry is None:
            print(f"{rel}: NOT included in the scan")
            from .scanner import Gitignore
            root_p = Path(args.path)
            if profile.path and profile.is_ignored(rel):
                print("  reason: excluded by .ghostslice.json profile ignore rule")
            elif root_p.is_dir() and Gitignore(root_p).ignored(rel):
                print("  reason: excluded by .gitignore")
            elif not (root_p / rel).exists():
                print("  reason: file does not exist under the project root")
            else:
                print("  reason: skipped by scanner defaults (binary, ignored directory, or unknown type)")
            return 0
        if args.mode:
            mode, why = args.mode, "explicit --mode override"
        else:
            pmode = profile.mode_for(rel) if profile.path else None
            if pmode:
                mode, why = pmode, "profile .ghostslice.json per-glob mode"
            else:
                mode = default_mode_for(entry)
                if entry.is_test:
                    why = "default: test file -> strip-tests"
                elif entry.is_lockfile:
                    why = "default: lockfile -> exclude"
                elif entry.language in SLICABLE:
                    why = f"default: {entry.language} code -> signatures"
                else:
                    why = "default: non-code file stays full"
        source = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
        sliced = slice_text(rel, source, mode)
        graph = build_graph(result)
        rev = _imp_of(graph)
        dups = find_duplicates(result)
        dup_notes = []
        for g in dups["exact"]:
            if rel in g["files"]:
                dup_notes.append(f"exact duplicate of {', '.join(p for p in g['files'] if p != rel)}")
        for pair in dups["near"]:
            if rel in pair["files"]:
                other = pair["files"][0] if pair["files"][1] == rel else pair["files"][1]
                dup_notes.append(f"near-duplicate of {other} (similarity {pair['similarity']})")
        file_secrets = scan_text(rel, source)
        print(f"{rel}: included")
        print(f"  language: {entry.language}  test: {entry.is_test}  lockfile: {entry.is_lockfile}")
        if entry.detect_evidence:
            det = "; ".join(f"{kind} ({ev})" for kind, ev in
                            sorted(entry.detect_evidence.items()))
            print(f"  detection: {det}")
        else:
            print("  detection: none")
        print(f"  mode: {mode}  ({why})")
        print(f"  tokens (estimated): {sliced.original_tokens:,} -> {sliced.sliced_tokens:,} (saved {sliced.saved_tokens:,})")
        print(f"  imports: {', '.join(graph.get(rel, {}).get('imports', [])) or '(none in project)'}")
        print(f"  imported by: {', '.join(rev.get(rel, [])) or '(nothing)'}")
        print(f"  duplicates: {'; '.join(dup_notes) or 'none'}")
        if file_secrets:
            print(f"  secrets: {len(file_secrets)} finding(s) (redacted):")
            for f in file_secrets:
                print(f"    line {f['line']}  {f['type']}  ({f['redacted']})")
        else:
            print("  secrets: none")
        return 0

    if args.cmd == "scan":
        from .duplicates import find_duplicates
        _t0 = time.perf_counter()
        _scan_cache = None if args.no_cache else open_cache(args.path)
        result = _scan_with_profile(args.path, profile, cache=_scan_cache)
        _t1 = time.perf_counter()
        graph = build_graph(result)
        recs = _with_dead_symbol_recs(result, graph, profile,
                                      recommendations(result, graph, profile))
        findings = scan_scan_result(result)
        dups = find_duplicates(result)
        if args.json:
            payload = result.to_dict()
            payload["token_method"] = TOKEN_METHOD
            payload["recommendations"] = recs
            payload["secrets"] = findings
            payload["duplicates"] = dups
            payload["profile"] = profile.to_dict()
            payload["history"] = ledger_summary(args.path)
            print(json.dumps(payload, indent=2))
            if args.timing:
                _print_scan_timing(_t0, _t1, _scan_cache, stream=sys.stderr)
            return 0
        model = get_model(prices, args.model or profile.model) if (args.model or profile.model) else None
        from .workspaces import summarize_packages
        ws = result.workspaces
        _print_scan(result, model=model, prices=prices, recs=recs, secrets=findings,
                    dups=dups, packages=summarize_packages(result),
                    ws_missing=ws.missing if ws else None,
                    ws_warnings=ws.warnings if ws else None)
        if args.timing:
            _print_scan_timing(_t0, _t1, _scan_cache)
        return 0

    if args.cmd == "graph":
        result = _scan_with_profile(args.path, profile)
        graph = build_graph(result)
        recs = _with_dead_symbol_recs(result, graph, profile,
                                      recommendations(result, graph, profile))
        if args.json:
            from .duplicates import find_duplicates
            print(json.dumps({
                "graph": graph,
                "importers": importers_of(graph),
                "recommendations": recs,
                "duplicates": find_duplicates(result),
            }, indent=2))
            return 0
        print(f"Import graph for {result.root} ({len(graph)} files)")
        for path in sorted(graph):
            deps = graph[path]["imports"]
            if deps:
                print(f"  {path} -> {', '.join(deps)}")
        if recs:
            total = sum(r["potential_savings"] for r in recs)
            print(f"\nPrune recommendations ({len(recs)}, up to {total:,} estimated tokens):")
            for r in recs:
                print(f"  {r['tokens']:>9,}  {r['path']}  ({r['reason']}; {r['detail']})")
        else:
            print("\nNo prune recommendations.")
        from .duplicates import find_duplicates
        dups = find_duplicates(result)
        if dups["exact"] or dups["near"]:
            print("\nDuplicates:")
            for g in dups["exact"]:
                print(f"  exact: {', '.join(g['files'])}")
            for pair in dups["near"]:
                print(f"  near ({pair['similarity']}): {' <-> '.join(pair['files'])}")
        return 0

    if args.cmd == "slice":
        src = Path(args.path)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            text = src.read_text(encoding="utf-8", errors="replace")
            r = slice_text(src.name, text, args.mode)
            (out / src.name).write_text(r.text, encoding="utf-8")
            print(f"{src.name}: {r.original_tokens:,} -> {r.sliced_tokens:,} estimated tokens ({args.mode})")
            return 0
        _slice_cache = None if args.no_cache else open_cache(src)
        result = _scan_with_profile(src, profile, cache=_slice_cache)
        before = after = 0
        for entry in result.files:
            text = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
            mode = args.mode if entry.language in SLICABLE or entry.language == "markdown" \
                or entry.language in CONFIG_LANGUAGES else "full"
            r = cached_slice_text(_slice_cache, entry.path, text, mode)
            before += r.original_tokens
            after += r.sliced_tokens
            if r.text:
                dest = out / entry.path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(r.text, encoding="utf-8")
        print(f"Sliced {len(result.files)} files ({args.mode} for code): {before:,} -> {after:,} estimated tokens")
        print(f"Output: {out}")
        return 0

    if args.cmd == "symbols":
        from .symslice import OUTLINE_LANGUAGES, outline_source
        from .tokens import estimate_tokens as _estimate_tokens
        try:
            result = _scan_with_profile(args.path, profile)
        except FileNotFoundError:
            print(f"symbols: no such project: {args.path}", file=sys.stderr)
            return 2
        entries = sorted(result.files, key=lambda e: e.path)
        single = None
        if args.file:
            rel = args.file.replace("\\", "/").lstrip("./")
            entries = [e for e in entries if e.path == rel]
            if not entries:
                print(f"symbols: {rel}: not in the scan", file=sys.stderr)
                return 2
            single = rel
        files_payload: list[dict] = []
        no_outline: list[str] = []
        total_symbols = 0
        for e in entries:
            if e.language not in OUTLINE_LANGUAGES:
                no_outline.append(e.path)
                files_payload.append({"path": e.path, "language": e.language,
                                      "symbols": None})
                continue
            source = Path(e.abspath).read_text(encoding="utf-8",
                                               errors="replace")
            found = outline_source(source, e.language, e.path) or []
            lines = source.splitlines()
            rows = []
            for s in found:
                if not s.selectable:
                    continue
                rows.append({
                    "name": s.name, "qualified": s.qualified, "kind": s.kind,
                    "start_line": s.start + 1, "end_line": s.end + 1,
                    "tokens": _estimate_tokens(s.span_text(lines), e.language),
                })
            total_symbols += len(rows)
            files_payload.append({"path": e.path, "language": e.language,
                                  "symbols": rows})
        if args.json:
            print(json.dumps({
                "root": result.root, "files": files_payload,
                "no_outline_files": no_outline,
                "token_method": TOKEN_METHOD,
            }, indent=2))
            return 0
        shown = 0
        for fp in files_payload:
            if fp["symbols"] is None:
                if single:
                    print(f"{fp['path']} ({fp['language']}): no symbol "
                          "outline for this language")
                continue
            if not fp["symbols"] and not single:
                continue
            shown += 1
            print(f"{fp['path']} ({fp['language']})")
            for r in fp["symbols"]:
                print(f"  {r['qualified']:<32} {r['kind']:<9} "
                      f"lines {r['start_line']:>4}-{r['end_line']:<4} "
                      f"~{r['tokens']:,} tokens")
            if not fp["symbols"]:
                print("  (no symbols found)")
        print(f"{total_symbols} symbol(s) in {shown} file(s); "
              "token counts are estimates.")
        if no_outline and not single:
            print(f"{len(no_outline)} file(s) have no symbol outline "
                  "(notebook, markdown, config/data, or plain text).")
        return 0

    if args.cmd == "calls":
        from .callgraph import build_call_graph
        try:
            result = _scan_with_profile(args.path, profile)
        except FileNotFoundError:
            print(f"calls: no such project: {args.path}", file=sys.stderr)
            return 2
        graph = build_graph(result)
        payload = build_call_graph(result, profile, graph)
        single = None
        if args.file:
            single = args.file.replace("\\", "/").lstrip("./")
            if single not in {e.path for e in result.files}:
                print(f"calls: {single}: not in the scan", file=sys.stderr)
                return 2
        if args.json:
            if single:
                payload = dict(payload)
                payload["symbols"] = [s for s in payload["symbols"]
                                       if s["path"] == single]
                keep = {s["id"] for s in payload["symbols"]}
                payload["edges"] = [e for e in payload["edges"]
                                     if e["caller"] in keep
                                     or e["callee"] in keep
                                     or e["caller"] == f"{single}:<module>"]
                payload["dead"] = [d for d in payload["dead"]
                                    if d["path"] == single]
            print(json.dumps(payload, indent=2))
            return 0
        _print_calls(payload, single=single, dead=args.dead)
        return 0

    if args.cmd == "task":
        if bool(args.task) == bool(args.diff):
            print("task: give exactly one of --task or --diff", file=sys.stderr)
            return 2
        task_scores = None
        if args.diff:
            result, selections, chosen, changed = select_for_diff(args.path, profile)
            print(f"Changed files: {len(changed)}; with direct dependencies: {len(chosen)}")
            include = set(chosen)
        else:
            result, selections, chosen, breakdown = select_for_task_breakdown(
                args.path, args.task, budget=args.budget, profile=profile)
            print(f"Selected {len(chosen)} files for task: {args.task!r}")
            for rel in chosen:
                bd = breakdown.get(rel, {})
                print(f"  score {bd.get('total', 0):>8.2f}  "
                      f"(tfidf {bd.get('tfidf', 0):.2f}, symbol {bd.get('symbol', 0):.2f}, "
                      f"graph {bd.get('graph', 0):.2f})  {rel}  ({selections[rel]})")
            include = set(chosen)
            task_scores = {rel: breakdown[rel] for rel in chosen if rel in breakdown}
        _warn_secrets([f for f in scan_scan_result(result) if f["path"] in include],
                      heading="WARNING: possible secrets in selected files")
        try:
            manifest = build_bundle(args.path, args.out, selections=selections,
                                    include=include, profile=profile, preset=args.preset,
                                    fit=args.fit, fit_protect_selections=False,
                                    redact=args.redact,
                                    task_scores=task_scores, model=args.model)
        except RedactionError as exc:
            print(f"task: {exc}", file=sys.stderr)
            return 1
        model = get_model(prices, args.model)
        pf = preflight(manifest["total_original_tokens"], manifest["total_sliced_tokens"], model, prices)
        print(f"Bundle: {args.out} (preset: {manifest.get('preset')})")
        print(f"Estimated tokens (whole project -> selection): {pf['before_tokens']:,} -> {pf['after_tokens']:,}")
        _print_wrapper(manifest)
        _print_redaction(manifest)
        fitted = _print_fit(manifest.get("fit"))
        check = validate_bundle(args.out)
        print(f"Validation: {'OK' if check['ok'] else 'FAILED: ' + '; '.join(check['errors'])}")
        return 0 if check["ok"] and fitted else 1

    if args.cmd == "export":
        _export_scan = _scan_with_profile(
            args.path, profile,
            cache=None if args.no_cache else open_cache(args.path))
        _warn_secrets(scan_scan_result(_export_scan))
        model_id = args.model or profile.model or "claude-sonnet"
        _timing: dict = {}
        try:
            manifest = build_bundle(args.path, args.out, default_mode=args.mode,
                                    profile=profile, preset=args.preset,
                                    exclude_secrets=args.exclude_secrets,
                                    redact=args.redact,
                                    auto_shrink=True if args.auto_shrink else None,
                                    fit=args.fit, model=model_id,
                                    symbols=args.symbols,
                                    use_cache=not args.no_cache,
                                    workers=args.workers,
                                    timing=_timing if args.timing else None)
        except RedactionError as exc:
            print(f"export: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"export: {exc}", file=sys.stderr)
            return 2
        model = get_model(prices, model_id)
        pf = preflight(manifest["total_original_tokens"], manifest["total_sliced_tokens"], model, prices)
        print(f"Bundle: {args.out} (preset: {manifest.get('preset')})")
        print(f"Files: {len(manifest['files'])}")
        auto = [f for f in manifest["files"] if "mode_reason" in f]
        if auto:
            print(f"Auto-shrink: excluded {len(auto)} detected file(s):")
            for f in auto:
                print(f"  {f['path']}  ({f['mode_reason']})")
        print(f"Estimated tokens: {pf['before_tokens']:,} -> {pf['after_tokens']:,} (saved {pf['saved_tokens']:,})")
        _print_wrapper(manifest)
        _print_redaction(manifest, exclude_secrets_on=args.exclude_secrets)
        _print_symbols(manifest)
        print(f"Pre-flight input cost at {pf['model_name']} (prices as of {pf['prices_as_of']}, local, not live): "
              f"~${pf['before_cost_usd']:.4f} -> ~${pf['after_cost_usd']:.4f}")
        fitted = _print_fit(manifest.get("fit"))
        check = validate_bundle(args.out)
        print(f"Validation: {'OK' if check['ok'] else 'FAILED: ' + '; '.join(check['errors'])}")
        if args.timing:
            _print_timing(_timing)
        return 0 if check["ok"] and fitted else 1

    if args.cmd == "watch":
        if not math.isfinite(args.interval) or args.interval <= 0:
            print("watch: --interval must be a finite number > 0", file=sys.stderr)
            return 2
        if args.debounce is not None and (not math.isfinite(args.debounce) or args.debounce < 0):
            print("watch: --debounce must be a finite number >= 0", file=sys.stderr)
            return 2
        if args.max_events is not None and args.max_events < 1:
            print("watch: --max-events must be >= 1", file=sys.stderr)
            return 2
        if args.fit is not None and args.fit <= 0:
            print("watch: --fit must be > 0", file=sys.stderr)
            return 2
        from .watch import run_watch
        try:
            run_watch(args.path, out=args.out,
                      export=args.export or args.out is not None,
                      interval=args.interval, debounce=args.debounce,
                      once=args.once, max_events=args.max_events,
                      fit=args.fit, preset=args.preset,
                      default_mode=args.mode,
                      exclude_secrets=args.exclude_secrets,
                      redact=args.redact,
                      auto_shrink=args.auto_shrink,
                      profile=profile)
        except FileNotFoundError:
            print(f"watch: no such project: {args.path}", file=sys.stderr)
            return 2
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            pass  # run_watch normally handles this; belt and braces for a clean exit 0
        return 0

    if args.cmd == "check-budget":
        budget = args.max_tokens if args.max_tokens is not None else profile.budget_tokens
        if budget is None:
            print("check-budget: no budget given (use --max-tokens or profile budget_tokens)", file=sys.stderr)
            return 2
        before, after = estimate_context_tokens(
            args.path, profile=profile, default_mode=args.mode,
            cache=open_cache(args.path))
        status = "OK" if after <= budget else "OVER BUDGET"
        print(f"Selected context: {after:,} sliced estimated tokens (full project {before:,}); budget {budget:,}: {status}")
        return 0 if after <= budget else 1

    if args.cmd == "check":
        check = validate_bundle(args.bundle)
        print(json.dumps(check, indent=2))
        return 0 if check["ok"] else 1

    if args.cmd == "history":
        try:
            model = get_model(prices, args.model or profile.model or "claude-sonnet")
        except KeyError as exc:
            print(f"history: {exc}", file=sys.stderr)
            return 2
        data = ledger_analytics(args.path, model=model, prices=prices)
        if args.json:
            print(json.dumps(data, indent=2))
            return 0
        # Default block: the plain summary, unchanged in shape.
        print(f"Savings ledger for {args.path}: {data['runs']} recorded run(s)")
        print(f"  Total before: {data['total_before_tokens']:,}  after: {data['total_after_tokens']:,}  "
              f"saved: {data['total_saved_tokens']:,} estimated tokens")
        if data["corrupt_lines"]:
            print(f"  Warning: skipped {data['corrupt_lines']} corrupt ledger line(s) "
                  "in .ghostslice-history.jsonl (not counted).")
        if data["estimator"]["warning"]:
            print(f"  Warning: {data['estimator']['warning']}")
        if args.model:
            agg = data["aggregates"]
            if agg.get("total_saved_cost_usd") is not None:
                print(f"  Total estimated $ saved at {model.get('name', model['id'])}: "
                      f"~${agg['total_saved_cost_usd']:.4f} "
                      f"({data['model']['prices_note']})")
        if args.trend:
            _print_history_trend(data)
        return 0

    if args.cmd == "serve":
        from .server import serve
        serve(args.path, port=args.port, host=args.host)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
