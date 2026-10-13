"""GhostSlice command line.

Commands:
  ghostslice scan         <path> [--json] [--model ID]
  ghostslice graph        <path> [--json]
  ghostslice slice        <path> --mode MODE -o <dir>
  ghostslice task         <path> (--task "words" | --diff) [--budget N] [--fit N] -o <bundle> [--preset P]
  ghostslice export       <path> -o <bundle> [--mode MODE] [--model ID] [--preset P] [--fit N]
  ghostslice watch        <path> [--export] [-o <bundle>] [--interval S] [--debounce S] [--once] [--max-events N] [--fit N]
  ghostslice check-budget <path> [--max-tokens N]
  ghostslice check        <bundle>
  ghostslice diff         <bundleA> <bundleB> [--json]
  ghostslice history      <path> [--json]
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
from pathlib import Path

from . import __version__
from .exporter import SLICABLE, build_bundle, estimate_context_tokens, validate_bundle
from .graph import build_graph, importers_of, recommendations
from .ledger import summary as ledger_summary
from .pricing import estimate_cost, get_model, load_prices, models, preflight
from .profile import PRESETS, load_profile
from .scanner import scan
from .secrets_scan import scan_scan_result, scan_text
from .selection import select_for_diff, select_for_task, select_for_task_breakdown
from .configslice import CONFIG_LANGUAGES
from .slicer import MODES, slice_text


def _scan_with_profile(path, profile):
    matcher = profile.is_ignored if profile.path else None
    return scan(path, ignore_matcher=matcher)


def _warn_secrets(findings, heading="WARNING: possible secrets detected") -> None:
    if not findings:
        return
    print(f"\n{heading} ({len(findings)} finding(s), values redacted):", file=sys.stderr)
    for f in findings:
        print(f"  {f['path']}:{f['line']}  {f['type']}  ({f['redacted']})", file=sys.stderr)
    print("  Review these files before sharing the bundle. "
          "Use --exclude-secrets (export) to force-exclude flagged files.", file=sys.stderr)


def _print_fit(fit_report) -> bool:
    """Print the --fit report; return True when the bundle fitted."""
    if not fit_report:
        return True
    steps = fit_report["steps"]
    step_text = ", ".join(f"{k} x{n}" for k, n in steps.items()) if steps else "no downgrades needed"
    print(f"Fit target: {fit_report['fit_tokens']:,} estimated tokens: "
          f"{fit_report['before_tokens']:,} -> {fit_report['after_tokens']:,} "
          f"({'fitted' if fit_report['fitted'] else 'COULD NOT FIT'})")
    print(f"  downgrades: {step_text}")
    if not fit_report["fitted"]:
        print(f"WARNING: could not fit the bundle into {fit_report['fit_tokens']:,} estimated tokens "
              f"(best achievable {fit_report['after_tokens']:,}); the bundle was still written.",
              file=sys.stderr)
    return fit_report["fitted"]


def _print_scan(result, model=None, prices=None, recs=None, secrets=None, dups=None) -> None:
    print(f"Project: {result.root}")
    print(f"Files: {len(result.files)}  Estimated tokens: {result.total_tokens:,}")
    print(f"{'tokens':>9}  {'lines':>6}  file")
    for f in result.files[:200]:
        flags = []
        if f.is_test:
            flags.append("test")
        if f.is_lockfile:
            flags.append("lockfile")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"{f.tokens:>9,}  {f.lines:>6}  {f.path}{suffix}")
    if len(result.files) > 200:
        print(f"... and {len(result.files) - 200} more files")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostslice", description="GhostSlice: agent context & prompt optimizer (token counts are estimates)")
    parser.add_argument("--version", action="version", version=f"ghostslice {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="scan a project and rank files by estimated token cost")
    p_scan.add_argument("path")
    p_scan.add_argument("--json", action="store_true")
    p_scan.add_argument("--model", default=None, help="model id from prices.json, for a cost line")

    p_graph = sub.add_parser("graph", help="import graph + prune recommendations")
    p_graph.add_argument("path")
    p_graph.add_argument("--json", action="store_true")

    p_slice = sub.add_parser("slice", help="slice one file or a whole tree into an output dir")
    p_slice.add_argument("path")
    p_slice.add_argument("--mode", choices=MODES, default="signatures")
    p_slice.add_argument("-o", "--out", required=True)

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

    p_export = sub.add_parser("export", help="write an agent context bundle")
    p_export.add_argument("path")
    p_export.add_argument("-o", "--out", required=True)
    p_export.add_argument("--mode", choices=MODES, default=None,
                          help="apply this mode to slicable files (default: signatures, tests stripped, lockfiles excluded)")
    p_export.add_argument("--preset", choices=PRESETS, default=None)
    p_export.add_argument("--model", default="claude-sonnet")
    p_export.add_argument("--exclude-secrets", action="store_true",
                          help="force-exclude files flagged by the secret guard")
    p_export.add_argument("--fit", type=int, default=None, metavar="N",
                          help="auto-fit: downgrade slice modes until the bundle fits N estimated tokens "
                               "(exit 1 if it cannot fit; the bundle is still written)")

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
    p_watch.add_argument("--fit", type=int, default=None, metavar="N",
                         help="with --export: auto-fit the bundle to N estimated tokens, as in export --fit")

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

    # All remaining commands target a project path (or a bundle for check).
    target = getattr(args, "path", None) or getattr(args, "bundle", None)
    profile = load_profile(target) if target else load_profile(".")

    if profile.path:
        print(f"Profile: {profile.path}", file=sys.stderr)

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
        result = _scan_with_profile(args.path, profile)
        graph = build_graph(result)
        recs = recommendations(result, graph, profile)
        findings = scan_scan_result(result)
        dups = find_duplicates(result)
        if args.json:
            payload = result.to_dict()
            payload["token_method"] = "estimates (BPE-like split, not exact tokenizer counts)"
            payload["recommendations"] = recs
            payload["secrets"] = findings
            payload["duplicates"] = dups
            payload["profile"] = profile.to_dict()
            payload["history"] = ledger_summary(args.path)
            print(json.dumps(payload, indent=2))
            return 0
        model = get_model(prices, args.model or profile.model) if (args.model or profile.model) else None
        _print_scan(result, model=model, prices=prices, recs=recs, secrets=findings, dups=dups)
        return 0

    if args.cmd == "graph":
        result = _scan_with_profile(args.path, profile)
        graph = build_graph(result)
        recs = recommendations(result, graph, profile)
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
        result = _scan_with_profile(src, profile)
        before = after = 0
        for entry in result.files:
            text = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
            mode = args.mode if entry.language in SLICABLE or entry.language == "markdown" \
                or entry.language in CONFIG_LANGUAGES else "full"
            r = slice_text(entry.path, text, mode)
            before += r.original_tokens
            after += r.sliced_tokens
            if r.text:
                dest = out / entry.path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(r.text, encoding="utf-8")
        print(f"Sliced {len(result.files)} files ({args.mode} for code): {before:,} -> {after:,} estimated tokens")
        print(f"Output: {out}")
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
        manifest = build_bundle(args.path, args.out, selections=selections,
                                include=include, profile=profile, preset=args.preset,
                                fit=args.fit, fit_protect_selections=False,
                                task_scores=task_scores)
        model = get_model(prices, args.model)
        pf = preflight(manifest["total_original_tokens"], manifest["total_sliced_tokens"], model, prices)
        print(f"Bundle: {args.out} (preset: {manifest.get('preset')})")
        print(f"Estimated tokens (whole project -> selection): {pf['before_tokens']:,} -> {pf['after_tokens']:,}")
        fitted = _print_fit(manifest.get("fit"))
        check = validate_bundle(args.out)
        print(f"Validation: {'OK' if check['ok'] else 'FAILED: ' + '; '.join(check['errors'])}")
        return 0 if check["ok"] and fitted else 1

    if args.cmd == "export":
        _export_scan = _scan_with_profile(args.path, profile)
        _warn_secrets(scan_scan_result(_export_scan))
        manifest = build_bundle(args.path, args.out, default_mode=args.mode,
                                profile=profile, preset=args.preset,
                                exclude_secrets=args.exclude_secrets,
                                fit=args.fit)
        model = get_model(prices, args.model or profile.model or "claude-sonnet")
        pf = preflight(manifest["total_original_tokens"], manifest["total_sliced_tokens"], model, prices)
        print(f"Bundle: {args.out} (preset: {manifest.get('preset')})")
        print(f"Files: {len(manifest['files'])}")
        print(f"Estimated tokens: {pf['before_tokens']:,} -> {pf['after_tokens']:,} (saved {pf['saved_tokens']:,})")
        print(f"Pre-flight input cost at {pf['model_name']} (prices as of {pf['prices_as_of']}, local, not live): "
              f"~${pf['before_cost_usd']:.4f} -> ~${pf['after_cost_usd']:.4f}")
        fitted = _print_fit(manifest.get("fit"))
        check = validate_bundle(args.out)
        print(f"Validation: {'OK' if check['ok'] else 'FAILED: ' + '; '.join(check['errors'])}")
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
        before, after = estimate_context_tokens(args.path, profile=profile, default_mode=args.mode)
        status = "OK" if after <= budget else "OVER BUDGET"
        print(f"Selected context: {after:,} sliced estimated tokens (full project {before:,}); budget {budget:,}: {status}")
        return 0 if after <= budget else 1

    if args.cmd == "check":
        check = validate_bundle(args.bundle)
        print(json.dumps(check, indent=2))
        return 0 if check["ok"] else 1

    if args.cmd == "history":
        summ = ledger_summary(args.path)
        if args.json:
            print(json.dumps(summ, indent=2))
            return 0
        print(f"Savings ledger for {args.path}: {summ['runs']} recorded run(s)")
        print(f"  Total before: {summ['total_before_tokens']:,}  after: {summ['total_after_tokens']:,}  "
              f"saved: {summ['total_saved_tokens']:,} estimated tokens")
        return 0

    if args.cmd == "serve":
        from .server import serve
        serve(args.path, port=args.port, host=args.host)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
