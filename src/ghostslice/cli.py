"""GhostSlice command line.

Commands:
  ghostslice scan   <path> [--json] [--model ID]
  ghostslice slice  <path> --mode MODE -o <dir>
  ghostslice export <path> -o <bundle> [--mode MODE] [--model ID]
  ghostslice check  <bundle>
  ghostslice serve  <path> --port 8765
  ghostslice prices
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .exporter import build_bundle, validate_bundle
from .pricing import estimate_cost, get_model, load_prices, models, preflight
from .scanner import scan
from .slicer import MODES, slice_text


def _print_scan(result, model=None, prices=None) -> None:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostslice", description="GhostSlice: agent context & prompt optimizer (token counts are estimates)")
    parser.add_argument("--version", action="version", version=f"ghostslice {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="scan a project and rank files by estimated token cost")
    p_scan.add_argument("path")
    p_scan.add_argument("--json", action="store_true")
    p_scan.add_argument("--model", default=None, help="model id from prices.json, for a cost line")

    p_slice = sub.add_parser("slice", help="slice one file or a whole tree into an output dir")
    p_slice.add_argument("path")
    p_slice.add_argument("--mode", choices=MODES, default="signatures")
    p_slice.add_argument("-o", "--out", required=True)

    p_export = sub.add_parser("export", help="write a .claude_context bundle")
    p_export.add_argument("path")
    p_export.add_argument("-o", "--out", required=True)
    p_export.add_argument("--mode", choices=MODES, default=None,
                          help="apply this mode to slicable files (default: signatures, tests stripped, lockfiles excluded)")
    p_export.add_argument("--model", default="claude-sonnet")

    p_check = sub.add_parser("check", help="validate a bundle against its manifest")
    p_check.add_argument("bundle")

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

    if args.cmd == "scan":
        result = scan(args.path)
        if args.json:
            payload = result.to_dict()
            payload["token_method"] = "estimates (BPE-like split, not exact tokenizer counts)"
            print(json.dumps(payload, indent=2))
            return 0
        model = get_model(prices, args.model) if args.model else None
        _print_scan(result, model=model, prices=prices)
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
        result = scan(src)
        before = after = 0
        for entry in result.files:
            text = Path(entry.abspath).read_text(encoding="utf-8", errors="replace")
            mode = args.mode if entry.language in ("python", "typescript", "javascript") else "full"
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

    if args.cmd == "export":
        manifest = build_bundle(args.path, args.out, default_mode=args.mode)
        model = get_model(prices, args.model)
        pf = preflight(manifest["total_original_tokens"], manifest["total_sliced_tokens"], model, prices)
        print(f"Bundle: {args.out}")
        print(f"Files: {len(manifest['files'])}")
        print(f"Estimated tokens: {pf['before_tokens']:,} -> {pf['after_tokens']:,} (saved {pf['saved_tokens']:,})")
        print(f"Pre-flight input cost at {pf['model_name']} (prices as of {pf['prices_as_of']}, local, not live): "
              f"~${pf['before_cost_usd']:.4f} -> ~${pf['after_cost_usd']:.4f}")
        check = validate_bundle(args.out)
        print(f"Validation: {'OK' if check['ok'] else 'FAILED: ' + '; '.join(check['errors'])}")
        return 0 if check["ok"] else 1

    if args.cmd == "check":
        check = validate_bundle(args.bundle)
        print(json.dumps(check, indent=2))
        return 0 if check["ok"] else 1

    if args.cmd == "serve":
        from .server import serve
        serve(args.path, port=args.port, host=args.host)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
