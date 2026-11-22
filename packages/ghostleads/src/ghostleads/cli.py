"""GhostLeads command line interface.

Usage (``ghostleads`` if installed, otherwise
``PYTHONPATH=src python3 -m ghostleads``):

  ghostleads import <file.csv|file.json> [--store leads.json]
  ghostleads score [--store leads.json] [--json]
  ghostleads list [--store leads.json] [--tier N] [--town X]
                  [--trade Y] [--min-score N] [--json]
  ghostleads pack [--store leads.json] [--out packs/]
                  [--lead NAME] [--all]

Start with ``import``: the other three commands read the store file
that ``import`` creates, and they fail with exit code 2 if that file
does not exist yet. Use the same ``--store`` path for every command
in a session.

Exit codes: 0 = ok, 1 = no leads matched, 2 = could not run
(missing store, unreadable import file, invalid data).

Fully offline. There is deliberately no command that contacts a
lead: packs are drafts only, and any outreach stays a manual gate
outside this tool.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .packs import slugify, write_packs
from .scoring import score_lead
from .store import import_file, load_store, save_store

DEFAULT_STORE = "leads.json"


def _require_store(args) -> list:
    """Load the store named by ``args.store``, or report why not.

    Returns the list of leads, or ``None`` after printing a short
    error to stderr (callers then return exit code 2). A missing
    store almost always means ``import`` has not run yet, or a
    different ``--store`` path was used for the import.
    """
    if not Path(args.store).exists():
        print(f"error: store not found: {args.store} (run ghostleads import first)",
              file=sys.stderr)
        return None
    try:
        return load_store(args.store)
    except (OSError, ValueError) as exc:
        print(f"error: cannot read store {args.store}: {exc}", file=sys.stderr)
        return None


def _ranked(leads) -> list:
    """Return leads in display order: highest score, then name."""
    return sorted(leads, key=lambda l: (-l.score, l.name.lower()))


def _print_table(leads) -> None:
    """Print the plain ranked table used by ``score`` and ``list``."""
    print(f"{'Score':>5}  {'Tier':>4}  {'Name':<38} {'Trade':<22} {'Town':<16} Phone")
    for lead in leads:
        print(f"{lead.score:>5}  {lead.tier:>4}  {lead.name[:38]:<38} "
              f"{lead.trade[:22]:<22} {lead.town[:16]:<16} {lead.phone}")


def _cmd_import(args) -> int:
    """Import a CSV/JSON file, then print added/merged/skipped counts."""
    try:
        report = import_file(args.store, args.file)
    except (OSError, ValueError) as exc:
        print(f"error: import failed: {exc}", file=sys.stderr)
        return 2
    print(f"imported rows: {report['imported_rows']}")
    print(f"added: {report['added']}  merged (duplicates): {report['merged']}  "
          f"total in store: {report['total']}")
    for skip in report["skipped"]:
        print(f"  skipped {skip['where']}: {skip['why']}")
    return 0


def _cmd_score(args) -> int:
    """Recompute every score and tier, save them, and show the ranking."""
    leads = _require_store(args)
    if leads is None:
        return 2
    for lead in leads:
        score_lead(lead)
    leads = _ranked(leads)
    try:
        save_store(args.store, leads)
    except OSError as exc:
        print(f"error: cannot write store {args.store}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([l.to_dict() for l in leads], indent=2))
    else:
        _print_table(leads)
    return 0 if leads else 1


def _cmd_list(args) -> int:
    """Show stored leads in ranked order, narrowed by any filters given."""
    leads = _require_store(args)
    if leads is None:
        return 2
    out = _ranked(leads)
    if args.tier is not None:
        out = [l for l in out if l.tier == args.tier]
    if args.town:
        out = [l for l in out if l.town.lower() == args.town.lower()]
    if args.trade:
        out = [l for l in out if l.trade.lower() == args.trade.lower()]
    if args.min_score is not None:
        out = [l for l in out if l.score >= args.min_score]
    if args.json:
        print(json.dumps([l.to_dict() for l in out], indent=2))
    else:
        _print_table(out)
    return 0 if out else 1


def _cmd_pack(args) -> int:
    """Write draft pack Markdown for the selected lead(s).

    Selection: ``--all`` packs every lead, ``--lead NAME`` packs the
    one lead whose name (or slug) matches, and with neither flag only
    the single highest scoring lead is packed.
    """
    leads = _require_store(args)
    if leads is None:
        return 2
    ranked = _ranked(leads)
    if args.all:
        selected = ranked
    elif args.lead:
        wanted = args.lead.lower()
        selected = [l for l in ranked
                    if l.name.lower() == wanted or slugify(l.name) == slugify(args.lead)]
        if not selected:
            print(f"error: no lead matches --lead {args.lead!r}", file=sys.stderr)
            return 1
    else:
        selected = ranked[:1]
    if not selected:
        print("error: store is empty, nothing to pack", file=sys.stderr)
        return 1
    try:
        written = write_packs(selected, args.out)
    except OSError as exc:
        print(f"error: cannot write packs to {args.out}: {exc}", file=sys.stderr)
        return 2
    for path in written:
        print(f"pack: {path}")
    print("DRAFT ONLY. Not sent. Sending is Ryan's manual step.")
    return 0


def main(argv=None) -> int:
    """Parse arguments and dispatch to one of the four commands."""
    parser = argparse.ArgumentParser(
        prog="ghostleads",
        description=(
            "Offline lead manager and scorer for leads you researched "
            "yourself. Import a CSV or JSON list, score and rank it, "
            "and draft pitch packs. Fully offline, drafts only."),
        epilog=(
            "Examples:\n"
            "  ghostleads import my-leads.csv --store leads.json\n"
            "  ghostleads score --store leads.json\n"
            "  ghostleads list --store leads.json --tier 1\n"
            "  ghostleads pack --store leads.json --out packs/ --all\n"
            "\n"
            "Tip: run 'ghostleads <command> --help' for a command's "
            "options. Drafts only: this tool never contacts a lead; "
            "any outreach is a manual step outside the tool."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"ghostleads {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "import",
        help="import a local CSV or JSON lead list into the store",
        description=(
            "Import a CSV or JSON file of leads you researched yourself "
            "into the local store. Rows are validated, duplicates are "
            "merged (first record wins, later rows only fill blanks), "
            "and every lead is scored. Only the 'name' field is required; "
            "blank fields stay unknown and score zero."),
        epilog=(
            "Example:\n"
            "  ghostleads import examples/sample_leads.csv --store leads.json\n"
            "\n"
            "The printed report shows rows read, leads added, duplicates "
            "merged, and each skipped row with its reason."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file",
                   help="path to the .csv or .json file to import")
    p.add_argument("--store", default=DEFAULT_STORE,
                   help="path to the local store file "
                        f"(default: {DEFAULT_STORE})")

    p = sub.add_parser(
        "score",
        help="recompute scores and tiers, print a ranked table",
        description=(
            "Recompute every lead's score (0 to 100) and tier "
            "(Tier 1: 60+, Tier 2: 40 to 59, Tier 3: below 40) from "
            "the stored fields, save them back to the store, and print "
            "the ranked table. Every point carries a reason, visible "
            "in the --json output and in each pack."),
        epilog=(
            "Example:\n"
            "  ghostleads score --store leads.json --json"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", default=DEFAULT_STORE,
                   help="path to the local store file "
                        f"(default: {DEFAULT_STORE})")
    p.add_argument("--json", action="store_true",
                   help="print the full stored records as JSON "
                        "instead of the table")

    p = sub.add_parser(
        "list",
        help="list leads ranked by score, with filters",
        description=(
            "List leads from the store, highest score first. "
            "Filters narrow the list and can be combined; town and "
            "trade matching is exact and case-insensitive."),
        epilog=(
            "Example:\n"
            "  ghostleads list --store leads.json --tier 1 --town Exampleton"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", default=DEFAULT_STORE,
                   help="path to the local store file "
                        f"(default: {DEFAULT_STORE})")
    p.add_argument("--tier", type=int, choices=[1, 2, 3],
                   help="only show leads in this tier (1, 2, or 3)")
    p.add_argument("--town",
                   help="only show leads whose town matches exactly "
                        "(case-insensitive)")
    p.add_argument("--trade",
                   help="only show leads whose trade matches exactly "
                        "(case-insensitive)")
    p.add_argument("--min-score", type=int,
                   help="only show leads scoring at least this many points")
    p.add_argument("--json", action="store_true",
                   help="print the full stored records as JSON "
                        "instead of the table")

    p = sub.add_parser(
        "pack",
        help="generate draft pitch pack markdown (drafts only)",
        description=(
            "Write one Markdown draft pitch pack per selected lead. "
            "Each pack shows the stored snapshot, the score with its "
            "reasons, a suggested angle, a draft pitch built only from "
            "known fields, and a verification checklist."),
        epilog=(
            "Examples:\n"
            "  ghostleads pack --store leads.json --out packs/\n"
            "  ghostleads pack --store leads.json --out packs/ --all\n"
            "  ghostleads pack --store leads.json --lead \"Hilltop Quarry Hauling\"\n"
            "\n"
            "Note: with no selector, only the highest scoring lead "
            "is packed. Drafts only: nothing is ever contacted by "
            "this command."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", default=DEFAULT_STORE,
                   help="path to the local store file "
                        f"(default: {DEFAULT_STORE})")
    p.add_argument("--out", default="packs",
                   help="folder to write pack files into (default: packs)")
    p.add_argument("--lead", help="pack only this lead (full name or slug)")
    p.add_argument("--all", action="store_true", help="pack every lead in the store")

    args = parser.parse_args(argv)
    if args.command == "import":
        return _cmd_import(args)
    if args.command == "score":
        return _cmd_score(args)
    if args.command == "list":
        return _cmd_list(args)
    if args.command == "pack":
        return _cmd_pack(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
