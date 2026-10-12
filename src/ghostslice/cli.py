"""GhostSlice command line.

Commands:
  ghostslice scan         <path> [--json] [--model ID]
  ghostslice graph        <path> [--json]
  ghostslice slice        <path> --mode MODE -o <dir>
  ghostslice task         <path> (--task "words" | --diff) [--budget N] -o <bundle> [--preset P]
  ghostslice export       <path> -o <bundle> [--mode MODE] [--model ID] [--preset P]
  ghostslice check-budget <path> [--max-tokens N]
  ghostslice check        <bundle>
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
import sys
from pathlib import Path

from . import __version__
from .exporter import build_bundle, estimate_context_tokens, validate_bundle
from .graph import build_graph, importers_of, recommendations
from .ledger import summary as ledger_summary
from .pricing import estimate_cost, get_model, load_prices, models, preflight
from .profile import PRESETS, load_profile
from .scanner import scan
from .selection import select_for_diff, select_for_task
from .slicer import MODES, slice_text


def _scan_with_profile(path, profile):
    matcher = profile.is_ignored if profile.path else None
    return scan(path, ignore_matcher=matcher)


def _print_scan(result, model=None, prices=None, recs=None) -> None:
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

    # All remaining commands target a project path (or a bundle for check).
    target = getattr(args, "path", None) or getattr(args, "bundle", None)
    profile = load_profile(target) if target else load_profile(".")

    if profile.path:
        print(f"Profile: {profile.path}", file=sys.stderr)

    if args.cmd == "scan":
        result = _scan_with_profile(args.path, profile)
        graph = build_graph(result)
        recs = recommendations(result, graph, profile)
        if args.json:
            payload = result.to_dict()
            payload["token_method"] = "estimates (BPE-like split, not exact tokenizer counts)"
            payload["recommendations"] = recs
            payload["profile"] = profile.to_dict()
            payload["history"] = ledger_summary(args.path)
            print(json.dumps(payload, indent=2))
            return 0
        model = get_model(prices, args.model or profile.model) if (args.model or profile.model) else None
        _print_scan(result, model=model, prices=prices, recs=recs)
        return 0

    if args.cmd == "graph":
        result = _scan_with_profile(args.path, profile)
        graph = build_graph(result)
        recs = recommendations(result, graph, profile)
        if args.json:
            print(json.dumps({
                "graph": graph,
                "importers": importers_of(graph),
                "recommendations": recs,
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
            mode = args.mode if entry.language in ("python", "typescript", "javascript", "go", "rust", "java", "csharp") else "full"
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
        if args.diff:
            result, selections, chosen, changed = select_for_diff(args.path, profile)
            print(f"Changed files: {len(changed)}; with direct dependencies: {len(chosen)}")
            include = set(chosen)
        else:
            result, selections, chosen, scores = select_for_task(
                args.path, args.task, budget=args.budget, profile=profile)
            print(f"Selected {len(chosen)} files for task: {args.task!r}")
            for rel in chosen:
                print(f"  score {scores.get(rel, 0):>4}  {rel}  ({selections[rel]})")
            include = set(chosen)
        manifest = build_bundle(args.path, args.out, selections=selections,
                                include=include, profile=profile, preset=args.preset)
        model = get_model(prices, args.model)
        pf = preflight(manifest["total_original_tokens"], manifest["total_sliced_tokens"], model, prices)
        print(f"Bundle: {args.out} (preset: {manifest.get('preset')})")
        print(f"Estimated tokens (whole project -> selection): {pf['before_tokens']:,} -> {pf['after_tokens']:,}")
        check = validate_bundle(args.out)
        print(f"Validation: {'OK' if check['ok'] else 'FAILED: ' + '; '.join(check['errors'])}")
        return 0 if check["ok"] else 1

    if args.cmd == "export":
        manifest = build_bundle(args.path, args.out, default_mode=args.mode,
                                profile=profile, preset=args.preset)
        model = get_model(prices, args.model or profile.model or "claude-sonnet")
        pf = preflight(manifest["total_original_tokens"], manifest["total_sliced_tokens"], model, prices)
        print(f"Bundle: {args.out} (preset: {manifest.get('preset')})")
        print(f"Files: {len(manifest['files'])}")
        print(f"Estimated tokens: {pf['before_tokens']:,} -> {pf['after_tokens']:,} (saved {pf['saved_tokens']:,})")
        print(f"Pre-flight input cost at {pf['model_name']} (prices as of {pf['prices_as_of']}, local, not live): "
              f"~${pf['before_cost_usd']:.4f} -> ~${pf['after_cost_usd']:.4f}")
        check = validate_bundle(args.out)
        print(f"Validation: {'OK' if check['ok'] else 'FAILED: ' + '; '.join(check['errors'])}")
        return 0 if check["ok"] else 1

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
