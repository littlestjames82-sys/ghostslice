"""GhostLedger command-line interface.

Subcommands:

  ghostledger add    --project P [--model M] [--agent A] [--task T]
                     [--kind K] [--input-tokens N] [--output-tokens N]
                     [--total-tokens N] [--estimated-tokens N]
                     [--at ISO] [--note TEXT]
  ghostledger import [--slice-history F ...] [--proxy-report F ...]
                     [--bench-report F ...] [--source-file F ...]
                     [--project P]
  ghostledger report [--by project|model|agent|day] [--since D]
                     [--until D] [--project P] [--out-dir DIR] [--json]
  ghostledger summary [--since D] [--until D] [--project P] [--json]
  ghostledger verify [--json]

Global flags (``--ledger`` and ``--prices``) come *before* the
subcommand, for example::

  ghostledger --ledger ./books.jsonl summary

Ledger file: ``--ledger PATH``, else ``$GHOSTLEDGER_FILE``, else
``./.ghostledger.jsonl``. Prices: ``--prices PATH``, else
``$GHOSTLEDGER_PRICES``, else a sibling GhostSlice table, else the
bundled dated snapshot. All costs are ESTIMATES from that dated
table, never billed amounts. GhostLedger is local only: it makes
no network calls, ever.

Exit codes: ``0`` ok, ``1`` loop warning present (``report`` /
``summary``) or audit problems found (``verify``), ``2`` error.
Exit ``1`` is a warning to look at, not a failure; exit ``2`` means
nothing was booked or written for that invocation.
"""
from __future__ import annotations
import argparse, json, sys
from datetime import date, datetime
from pathlib import Path

def _is_iso_datetime(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
        return True
    except ValueError:
        return False

def _is_iso_date(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value.strip())
        return True
    except ValueError:
        return False

from . import __version__
from .ingest import import_bench_report, import_proxy_report, import_slice_history, import_source_file
from .ledger import append_entries, append_entry, default_ledger_path, filter_entries, load_entries, make_entry, summarise
from .prices import load_price_table
from .report import write_reports
from .verify import verify_ledger

_EPILOG = """\
examples:
  ghostledger add --project ghostbus --model claude-sonnet \\
    --agent builder-a --task "review pass" \\
    --input-tokens 10000 --output-tokens 2000 --estimated-tokens 12000
  ghostledger import --slice-history .ghostslice-history.jsonl
  ghostledger import --source-file mystery.json   # auto-detects the shape
  ghostledger summary
  ghostledger summary --since 2026-10-01 --project ghostbus --json
  ghostledger report --by day --out-dir ./ledger-out
  ghostledger verify   # audit the ledger file itself (read-only)

notes:
  Global flags --ledger / --prices go before the subcommand.
  Costs are ESTIMATES from a local dated price table, never billed
  amounts. Unknown models book cost as unknown, never as $0.
  A loop warning means one entry exceeded 3x its estimate. It is a
  warning, not a verdict. Local only: no network calls, ever.

exit codes:
  0  ok
  1  loop warning present (report / summary) or audit problems found (verify)
  2  error (nothing booked or written for that invocation)
"""

def _print_summary(summary, by=None):
    """Print the human-readable summary for ``report`` / ``summary``.

    Shows the headline totals, the cost-estimate disclaimer, the
    estimate-vs-actual line (entries with an estimate only), one
    line per group for the chosen grouping, every loop warning,
    and any unknown models.
    """
    t = summary["totals"]
    print(f"ghostledger: {t['entries']} entries, {t['total_tokens']:,} total tokens, "
          f"${t['cost_estimate_usd']:,.4f} estimated cost")
    print(f"  {summary['cost_note']}")
    print(f"  estimate vs actual (entries with an estimate only): estimated {t['estimated_tokens']:,} "
          f"vs actual {t.get('actual_tokens_with_estimate', t['total_tokens']):,} "
          f"(ratio {t.get('estimate_vs_actual_ratio')})")
    groups = summary[{"project": "by_project", "model": "by_model", "agent": "by_agent", "day": "by_day"}[by or "project"]]
    for key, g in groups.items():
        print(f"  {key}: {g['entries']} entries, {g['total_tokens']:,} tokens, ${g['cost_estimate_usd']:,.4f} est.")
    for e in summary["loop_warnings"]:
        print(f"  WARNING exceeded 3x estimate: {e.get('at')} project={e.get('project')} "
              f"total={e.get('total_tokens')} estimated={e.get('estimated_tokens')} ratio={e.get('ratio')}")
    if summary.get("unknown_models"):
        print(f"  unknown models (no cost estimate): {', '.join(summary['unknown_models'])}")

def _filtered(args, ledger_path):
    """Load the ledger and apply the ``--since`` / ``--until`` / ``--project`` filters."""
    entries = load_entries(ledger_path)
    return filter_entries(entries, since=getattr(args, "since", None),
                          until=getattr(args, "until", None), project=getattr(args, "project_filter", None))

def main(argv=None) -> int:
    """Run the GhostLedger CLI and return the process exit code.

    ``argv`` defaults to ``sys.argv`` (the usual console-script and
    ``python -m ghostledger`` path). See the module docstring for
    the exit-code contract.
    """
    parser = argparse.ArgumentParser(
        prog="ghostledger",
        description="Local token and cost ledger for GhostSlice: what agent work "
                    "cost, per project, per model, per agent, per day. Local only, "
                    "no network. Costs are estimates from a dated local price table, "
                    "never billed amounts.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"ghostledger {__version__}")
    parser.add_argument("--ledger", metavar="PATH",
                        help="ledger file (default: $GHOSTLEDGER_FILE or ./.ghostledger.jsonl)")
    parser.add_argument("--prices", metavar="PATH",
                        help="local prices.json (default: $GHOSTLEDGER_PRICES, a sibling "
                             "GhostSlice table, or the bundled dated snapshot)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser(
        "add", help="append one manual entry to the ledger",
        description="Append one manual entry to the ledger. The cost estimate is "
                    "computed from the local price table when the model is known; "
                    "an unknown model books cost as unknown, never guessed. Adding "
                    "the identical entry twice does not double-book.")
    p_add.add_argument("--project", required=True, metavar="P",
                       help="project label (required; a grouping key in reports)")
    p_add.add_argument("--model", metavar="M",
                       help="model label, matched to the price table case-insensitively "
                            "(e.g. claude-sonnet); omit for a token-only entry")
    p_add.add_argument("--agent", metavar="A",
                       help="agent label (a grouping key in reports)")
    p_add.add_argument("--task", default="", metavar="T",
                       help="short task label, e.g. \"review pass\" (default: empty)")
    p_add.add_argument("--kind", default="run", metavar="K",
                       help="entry kind: run, export, request, bench-task, ... (default: run)")
    p_add.add_argument("--input-tokens", type=int, default=0, metavar="N",
                       help="input tokens booked (default: 0; must not be negative)")
    p_add.add_argument("--output-tokens", type=int, default=0, metavar="N",
                       help="output tokens booked (default: 0; must not be negative)")
    p_add.add_argument("--total-tokens", type=int, metavar="N",
                       help="total tokens; when given alone it is booked as input "
                            "so totals reconcile")
    p_add.add_argument("--estimated-tokens", type=int, metavar="N",
                       help="pre-run estimate the actual is compared against; an "
                            "actual over 3x this value raises a loop warning")
    p_add.add_argument("--at", metavar="ISO",
                       help="entry timestamp in ISO format, e.g. 2026-10-14T10:00:00+00:00 "
                            "(default: now, UTC); its date is the by-day grouping key")
    p_add.add_argument("--note", default="", metavar="TEXT",
                       help="free-text note stored with the entry (default: empty)")

    p_imp = sub.add_parser(
        "import", help="import Slice history / Proxy / Bench reports (idempotent)",
        description="Import entries recorded by the other Ghost tools. Each flag "
                    "may be repeated. Imports are idempotent: re-importing the same "
                    "file adds zero entries and never double-books. Malformed "
                    "records are counted as skipped, never silently swallowed.")
    p_imp.add_argument("--slice-history", action="append", default=[], metavar="F",
                       help="GhostSlice .ghostslice-history.jsonl file; repeatable")
    p_imp.add_argument("--proxy-report", action="append", default=[], metavar="F",
                       help="GhostProxy report JSON file; repeatable")
    p_imp.add_argument("--bench-report", action="append", default=[], metavar="F",
                       help="GhostBench bench-report.json file; repeatable")
    p_imp.add_argument("--source-file", action="append", default=[], metavar="F",
                       help="any importable file; the shape is auto-detected "
                            "(.jsonl = Slice, tasks[] = Bench, otherwise Proxy); repeatable")
    p_imp.add_argument("--project", metavar="P",
                       help="override the project label for imported entries")

    for name, short_help, desc in (
        ("report", "write ledger-report.json + LEDGER.md and print a summary",
         "Write ledger-report.json and LEDGER.md (all four groupings, "
         "estimate-vs-actual per group, loop warnings, unknown models, price "
         "table date) and print the summary. With --json, print the summary "
         "JSON instead and write no files. Exits 1 when a loop warning is present."),
        ("summary", "print a quick summary (writes no files)",
         "Print a quick view: entries, total tokens, estimated cost, the "
         "estimate-vs-actual headline, and the warning count. Writes no files. "
         "Exits 1 when a loop warning is present."),
    ):
        p = sub.add_parser(name, help=short_help, description=desc)
        p.add_argument("--since", metavar="D",
                       help="only entries on or after this day, YYYY-MM-DD (inclusive)")
        p.add_argument("--until", metavar="D",
                       help="only entries on or before this day, YYYY-MM-DD (inclusive)")
        p.add_argument("--project", dest="project_filter", metavar="P",
                       help="only entries for this project")
        p.add_argument("--json", action="store_true",
                       help="print the summary as JSON instead of text")
        if name == "report":
            p.add_argument("--by", choices=["project", "model", "agent", "day"], default="project",
                           help="grouping printed in the text summary (default: project); "
                                "the JSON report always carries all four groupings")
            p.add_argument("--out-dir", default=".", metavar="DIR",
                           help="directory for ledger-report.json and LEDGER.md (default: .)")

    p_verify = sub.add_parser(
        "verify", help="audit the ledger file against its own booking rules (read-only)",
        description="Audit the ledger file itself, line by line, and modify "
                    "nothing: re-derive each entry's id, day, total, ratio, "
                    "loop flag, and (for entries booked under the same price "
                    "date) cost; flag malformed lines, duplicate ids, missing "
                    "fields, bad counts, and credential-named fields.")
    p_verify.add_argument("--json", action="store_true",
                          help="print the audit result as JSON instead of text")

    args = parser.parse_args(argv)
    ledger_path = default_ledger_path(args.ledger)
    try:
        table = load_price_table(args.prices)
    except Exception as exc:
        print(f"error: could not load price table: {exc}", file=sys.stderr)
        return 2

    if args.cmd == "add":
        if args.at is not None and not _is_iso_datetime(args.at):
            # A garbage or impossible --at (2026-02-30) used to book
            # verbatim, polluting the by-day grouping with a day that
            # does not exist and defeating --since/--until filtering.
            print(f"error: --at must be an ISO date/time (got {args.at!r})", file=sys.stderr)
            return 2
        try:
            entry = make_entry(project=args.project, model=args.model, agent=args.agent,
                               source="manual", kind=args.kind, task=args.task, at=args.at,
                               input_tokens=args.input_tokens, output_tokens=args.output_tokens,
                               total_tokens=args.total_tokens, estimated_tokens=args.estimated_tokens,
                               note=args.note, table=table)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        try:
            added = append_entry(ledger_path, entry)
        except OSError as exc:
            print(f"error: could not write ledger {ledger_path}: {exc}", file=sys.stderr)
            return 2
        print(f"added entry {entry['id']} to {ledger_path}" if added else
              f"duplicate entry {entry['id']} already in {ledger_path}, not re-booked")
        if entry["loop_warning"]:
            print(f"  WARNING: total {entry['total_tokens']} exceeded 3x estimate {entry['estimated_tokens']} (ratio {entry['ratio']})")
        if entry["cost_estimate_usd"] is None and args.model:
            print(f"  note: model {args.model!r} not in price table (as of {table.get('as_of')}); cost unknown, not guessed")
        return 0

    if args.cmd == "import":
        total_added, total_skipped, total_seen = 0, 0, 0
        jobs = []
        for f in args.slice_history:
            jobs.append((f, import_slice_history))
        for f in args.proxy_report:
            jobs.append((f, import_proxy_report))
        for f in args.bench_report:
            jobs.append((f, import_bench_report))
        for f, fn in jobs:
            try:
                entries, skipped = fn(f, table, args.project)
            except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError, OverflowError) as exc:
                print(f"error: {f}: {exc}", file=sys.stderr)
                return 2
            try:
                added = append_entries(ledger_path, entries)
            except OSError as exc:
                print(f"error: could not write ledger {ledger_path}: {exc}", file=sys.stderr)
                return 2
            total_added += added; total_skipped += skipped; total_seen += len(entries)
            print(f"{f}: {len(entries)} entries parsed, {added} added, {skipped} skipped")
        for f in args.source_file:
            try:
                entries, skipped, detected = import_source_file(f, table, args.project)
            except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError, OverflowError) as exc:
                print(f"error: {f}: {exc}", file=sys.stderr)
                return 2
            try:
                added = append_entries(ledger_path, entries)
            except OSError as exc:
                print(f"error: could not write ledger {ledger_path}: {exc}", file=sys.stderr)
                return 2
            total_added += added; total_skipped += skipped; total_seen += len(entries)
            print(f"{f}: detected {detected}, {len(entries)} entries parsed, {added} added, {skipped} skipped")
        if not jobs and not args.source_file:
            print("error: nothing to import (give --slice-history, --proxy-report, --bench-report, or --source-file)", file=sys.stderr)
            return 2
        print(f"import complete: {total_added} added ({total_seen} parsed, {total_skipped} skipped) into {ledger_path}")
        return 0

    if args.cmd == "verify":
        if not Path(ledger_path).is_file():
            print(f"error: ledger file not found: {ledger_path}", file=sys.stderr)
            return 2
        result = verify_ledger(ledger_path, table)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"ghostledger verify: {result['entries']} entries from "
                  f"{result['lines']} lines in {ledger_path}")
            print(f"  costs re-checked against the local price table (as of "
                  f"{result['price_table_as_of']}): {result['cost_checked']}; "
                  f"not re-checked (booked under a different price date, "
                  f"stated not guessed): {result['cost_unchecked']}")
            for p in result["problems"]:
                print(f"  PROBLEM line {p['line']} id={p['id']}: {p['check']}: {p['detail']}")
            if result["ok"]:
                print("  verify OK: every booked entry re-derives cleanly; nothing was modified")
            else:
                print(f"  verify FAILED: {result['problem_count']} problem(s); "
                      "the ledger was not modified - acting on a problem stays with the human")
        return 0 if result["ok"] else 1

    if args.cmd in ("report", "summary"):
        for flag in ("since", "until"):
            value = getattr(args, flag, None)
            if value is not None and not _is_iso_date(value):
                print(f"error: --{flag} must be a YYYY-MM-DD date (got {value!r})", file=sys.stderr)
                return 2
        try:
            entries = _filtered(args, ledger_path)
        except OSError as exc:
            print(f"error: could not read ledger {ledger_path}: {exc}", file=sys.stderr)
            return 2
        summary = summarise(entries, table)
        if args.cmd == "report" and not args.json:
            try:
                jpath, mpath = write_reports(summary, args.out_dir)
            except OSError as exc:
                print(f"error: could not write report to {args.out_dir}: {exc}", file=sys.stderr)
                return 2
            print(f"wrote {jpath} and {mpath}")
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            _print_summary(summary, by=getattr(args, "by", "project"))
        return 1 if summary["loop_warnings"] else 0

    return 2

if __name__ == "__main__":
    sys.exit(main())
