"""GhostRecall command-line interface.

Subcommands: ``scan``, ``recall``, ``explain``, ``bundle``, ``check``,
``panel`` and ``mcp``. Run ``ghostrecall <command> --help`` for the
options of one command. Everything is local: project memory is read
from inside the project directory only and nothing is sent anywhere.
"""
from __future__ import annotations
import argparse, json, sys

from . import __version__
from .bundle import build_bundle, check_bundle
from .dashboard import render_panel
from .profile import load_profile
from .recall import explain, select
from .sources import assert_project_root, collect_items
from .tokens import estimate

def _items(project):
    """Load the profile for *project* and collect all its memory items."""
    root = assert_project_root(project)
    profile = load_profile(root)
    items = collect_items(root, include_git=bool(profile.get("include_git", True)),
                          git_limit=int(profile.get("git_limit", 200)))
    return root, profile, items

def main(argv=None) -> int:
    """Entry point for the ``ghostrecall`` console script.

    Returns a process exit code: 0 on success, 1 when ``check`` finds
    a bundle that does not match its manifest, 2 on a usage or
    project error.
    """
    p = argparse.ArgumentParser(
        prog="ghostrecall",
        description="Project memory slicer paired with GhostSlice: rank a "
                    "project's decisions, notes and git history for a task, "
                    "with estimated token costs, provenance on every item, "
                    "and a verifiable bundle manifest. Local only; token "
                    "counts are estimates, not exact tokenizer counts.",
        epilog="examples:\n"
               "  ghostrecall scan path/to/project\n"
               "  ghostrecall recall path/to/project --task \"How does local storage work?\"\n"
               "  ghostrecall bundle path/to/project --task \"...\" --fit 20000 -o bundle-dir\n"
               "  ghostrecall check bundle-dir\n\n"
               "See README.md for the DECISIONS.md format and the profile keys.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"ghostrecall {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("scan", help="list project memory items by estimated token cost",
                        description="List every memory item found in the project, "
                                    "largest estimated token cost first.")
    sp.add_argument("project", help="path to the project root to read (project-local sources only)")
    sp.add_argument("--json", action="store_true", help="print the list as JSON instead of a table")

    sp = sub.add_parser("recall", help="rank memory items for a task (TF-IDF)",
                        description="Rank memory items for a task with TF-IDF. Standing "
                                    "rules are pinned in even when they do not rank; "
                                    "superseded items are never selected and items with "
                                    "secret findings are blocked from export.")
    sp.add_argument("project", help="path to the project root to read (project-local sources only)")
    sp.add_argument("--task", required=True, help="the task or question to recall memory for")
    sp.add_argument("--explain", action="store_true", help="also list what was NOT selected and why")
    sp.add_argument("--json", action="store_true", help="print the result as JSON instead of text lines")

    sp = sub.add_parser("explain", help="explain why one item was or was not selected for a task",
                        description="Explain one item for a task, as JSON: whether it was "
                                    "selected, its score, and the reason (pinned rule, ranked, "
                                    "superseded, blocked, not ranked, ...).")
    sp.add_argument("project", help="path to the project root to read (project-local sources only)")
    sp.add_argument("item", help="item to explain: its id, its exact title, or its source path")
    sp.add_argument("--task", required=True, help="the task or question to explain the item against")

    sp = sub.add_parser("bundle", help="build a bundle (memory, plus a GhostSlice bundle if given)",
                        description="Build a bundle folder containing PROMPT.md, RECALL.md, "
                                    "manifest.json and the sliced memory items under files/. "
                                    "With --fit, memory is downgraded to decision-only before "
                                    "anything is dropped; pinned rules are never dropped.")
    sp.add_argument("project", help="path to the project root to read (project-local sources only)")
    sp.add_argument("-o", "--out", required=True, help="output folder for the bundle (created if needed)")
    sp.add_argument("--task", default="", help="task to rank memory for (default: empty, meaning no "
                                               "TF-IDF ranking; every eligible item is a candidate)")
    sp.add_argument("--fit", type=int, default=None,
                    help="total token budget (estimate) for the bundle; without --slice-bundle "
                         "the whole budget is memory, with one the profile's "
                         "memory_budget_fraction of it is")
    sp.add_argument("--slice-bundle", default=None,
                    help="path to an existing GhostSlice bundle to merge with (its PROMPT.md "
                         "and manifest are included in the combined bundle)")
    sp.add_argument("--mode", default=None, choices=["full", "decision-only", "headings", "recent", "exclude"],
                    help="slicing mode for memory items (default: the profile's default_mode, "
                         "or 'full'); see README.md 'Modes'")

    sp = sub.add_parser("check", help="verify a bundle against its manifest",
                        description="Verify a bundle folder against its manifest.json: exported "
                                    "files present, sha256 and estimated token counts matching, "
                                    "provenance present, PROMPT.md untampered. Exits 1 on any problem.")
    sp.add_argument("bundle", help="path to the bundle folder to verify")

    sp = sub.add_parser("panel", help="print the dashboard panel HTML for a task",
                        description="Print the GhostRecall dashboard panel as an HTML fragment "
                                    "(selected items, pinned rules first, then what was excluded) "
                                    "for embedding in the GhostSlice dashboard.")
    sp.add_argument("project", help="path to the project root to read (project-local sources only)")
    sp.add_argument("--task", default="", help="task to select memory for (default: empty)")

    sub.add_parser("mcp", help="run the stdio MCP server",
                   description="Run the stdio MCP server (JSON-RPC) exposing recall_search, "
                               "recall_bundle and recall_explain, with capped payloads.")

    args = p.parse_args(argv)
    try:
        if args.cmd == "scan":
            _r, _pf, items = _items(args.project)
            rows = sorted(items, key=lambda i: -estimate(i.text))
            if args.json:
                print(json.dumps([{"id": i.id, "title": i.title, "source_type": i.source_type,
                                   "path": i.provenance.path, "line": i.provenance.line,
                                   "date": i.date, "status": i.status, "blocked": i.blocked,
                                   "tokens_estimate": estimate(i.text)} for i in rows], indent=2))
            else:
                print(f"{'TOKENS(est)':>12}  TYPE         STATUS     SOURCE")
                for i in rows:
                    print(f"{estimate(i.text):>12}  {i.source_type:<12} {i.status:<10} "
                          f"{i.provenance.path}:{i.provenance.line or ''} {i.title[:60]}")
                print(f"\n{len(rows)} items, {sum(estimate(i.text) for i in rows)} estimated tokens total")
            return 0
        if args.cmd == "recall":
            _r, profile, items = _items(args.project)
            selected, not_selected, conflicts = select(items, args.task, profile)
            if args.json:
                print(json.dumps({
                    "selected": [{"id": e["item"].id, "title": e["item"].title,
                                  "score": e["score"], "pinned": e["pinned"],
                                  "tokens_estimate": e.get("tokens", estimate(e["item"].text)),
                                  "provenance": e["item"].provenance.to_dict()} for e in selected],
                    "not_selected": [{"id": e["item"].id, "reason": e["reason"]} for e in not_selected],
                    "conflicts": conflicts}, indent=2))
            else:
                for e in selected:
                    pin = " [pinned rule]" if e["pinned"] else ""
                    print(f"{e.get('tokens', estimate(e['item'].text)):>7} est  score={e['score']:.4f}{pin}  "
                          f"{e['item'].title} ({e['item'].provenance.path})")
                for c in conflicts:
                    other = f" vs {c['other']}" if c.get("other") else ""
                    print(f"CONFLICT: {c['type']}: {c.get('current','')}{other} - {c['note']}")
                if args.explain:
                    print("\nNot selected:")
                    for e in not_selected:
                        print(f"  - {e['item'].title}: {e['reason']}")
            return 0
        if args.cmd == "explain":
            _r, profile, items = _items(args.project)
            print(json.dumps(explain(items, args.task, args.item, profile), indent=2))
            return 0
        if args.cmd == "bundle":
            mf = build_bundle(args.project, args.out, task=args.task, fit=args.fit,
                              slice_bundle=args.slice_bundle, mode=args.mode)
            print(f"bundle written to {args.out}: {mf['totals']}")
            if mf["conflicts"]:
                print(f"conflicts/superseded flagged: {len(mf['conflicts'])} (see RECALL.md)")
            return 0
        if args.cmd == "check":
            ok, problems = check_bundle(args.bundle)
            if ok:
                print(f"OK: {args.bundle} matches its manifest")
                return 0
            for prob in problems:
                print(f"FAIL: {prob}")
            return 1
        if args.cmd == "panel":
            _r, profile, items = _items(args.project)
            selected, not_selected, _c = select(items, args.task, profile)
            total = sum(e.get("tokens", estimate(e["item"].text)) for e in selected)
            print(render_panel(selected, not_selected, total))
            return 0
        if args.cmd == "mcp":
            from .mcp_server import serve
            return serve()
    except (ValueError, OSError) as e:
        # OSError included: filesystem failures (bundle out path is a
        # file, unreadable project, ...) are user errors here, not
        # crashes; report them cleanly instead of dumping a traceback.
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
