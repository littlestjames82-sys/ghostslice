"""GhostApprove command line interface.

Usage (the global ``--store`` may also be given after the verb;
``--queue`` is an alias for ``--store`` everywhere):

  ghostapprove [--store DIR] ingest <request.json | ->
  ghostapprove [--store DIR] list [--status pending|approved|denied|all]
                                  [--source NAME] [--json]
  ghostapprove [--store DIR] show <id> [--json]
  ghostapprove [--store DIR] approve <id> --hash <exact-hash>
                                     [--by NAME] [--note TEXT] [--json]
  ghostapprove [--store DIR] deny <id> --hash <exact-hash>
                                  [--by NAME] [--note TEXT | --reason TEXT]
                                  [--json]
  ghostapprove [--store DIR] history [--id ID] [--json]
  ghostapprove [--store DIR] verify [--json]     (alias: audit)

The everyday loop is: ``ingest`` a request file a producer wrote,
``list`` what is waiting, ``show`` one request in full, copy the
exact hash from that view into ``approve`` or ``deny``, and check
``history`` later to audit what was decided. Run any verb with
``--help`` for its own flags. ``examples/WALKTHROUGH.md`` in the
repository shows a complete run.

Exit codes: 0 success, 1 decision refused (hash mismatch, already
decided, unknown or unrecorded id) or verify found integrity
problems, 2 invalid request / store error.

GhostApprove records decisions only. Approving a request does NOT
execute it, and nothing is ever approved automatically.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .model import RequestError, short_hash
from .store import RefusedError, Store, StoreError, default_store_path

NOT_EXECUTED = "decision recorded only - GhostApprove did NOT execute this action"


def _age_text(ingested_at) -> str:
    """Human age of a queued request, from its ingest timestamp.

    Display only: derived from the stored timestamp, never used in
    any decision logic (a request can wait forever; age approves
    nothing). Returns "unknown" when the timestamp is missing or
    unparseable rather than guessing.
    """
    if not isinstance(ingested_at, str) or not ingested_at:
        return "unknown"
    try:
        then = datetime.fromisoformat(ingested_at.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = int((datetime.now(timezone.utc) - then).total_seconds())
    if seconds < 0:
        return "unknown"
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60}m"
    return f"{hours // 24}d {hours % 24}h"


def _store(args) -> Store:
    """Build the Store for a parsed command line.

    A ``--store`` (or ``--queue``) given after the verb wins over the
    global one given before it; with neither, the GHOSTAPPROVE_DIR
    environment variable and then ``./.ghostapprove`` apply (see
    :func:`ghostapprove.store.default_store_path`).
    """
    explicit = (getattr(args, "store_sub", None)
                or getattr(args, "queue_sub", None)
                or getattr(args, "store", None)
                or getattr(args, "queue", None))
    return Store(default_store_path(explicit))


def _print_entry_human(entry: dict) -> None:
    """Print one entry (from ``Store.get_entry``) in the full human
    ``show`` format: identity, status, content, exact hash, and the
    recorded decision when there is one."""
    content = entry.get("content") or {}
    print(f"id:     {entry['id']}")
    print(f"status: {entry['status']}")
    print(f"source: {content.get('source')}")
    print(f"risk:   {content.get('risk')}")
    print(f"action: {content.get('action')}")
    print(f"summary: {content.get('summary')}")
    if content.get("requested_by"):
        print(f"requested_by: {content['requested_by']}")
    print(f"ingested_at: {entry.get('ingested_at')}")
    print(f"age:    {_age_text(entry.get('ingested_at'))}")
    print(f"hash:   {entry['hash']}")
    if content.get("diff"):
        print("diff:")
        print(content["diff"])
    if content.get("payload") is not None:
        print("payload:")
        print(json.dumps(content["payload"], indent=2, ensure_ascii=False))
    dec = entry.get("decision")
    if dec:
        print(f"decision: {dec.get('event')} by {dec.get('by')} at {dec.get('at')}")
        if dec.get("note"):
            print(f"note: {dec['note']}")


def cmd_ingest(args) -> int:
    """``ingest``: read one request JSON document (a file, or stdin
    when the path is ``-``), record it, and print its id and exact
    hash. Returns 2 when the file cannot be read or the request is
    invalid, 1 when ingest is refused (for example a duplicate id)."""
    try:
        if args.file == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError is a ValueError, not an OSError, so a
        # request file that is not valid UTF-8 used to escape as a
        # traceback instead of this clean exit 2.
        print(f"error: cannot read request file: {exc}", file=sys.stderr)
        return 2
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"error: request file is not valid JSON: {exc}", file=sys.stderr)
        return 2
    except RecursionError:
        print("error: request file is nested too deeply to be valid "
              "JSON for this tool", file=sys.stderr)
        return 2
    try:
        entry = _store(args).ingest(raw)
    except RequestError as exc:
        print(f"error: invalid request: {exc}", file=sys.stderr)
        return 2
    except RefusedError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(entry, indent=2, ensure_ascii=False))
    else:
        print(f"ingested: {entry['id']}")
        print(f"  source: {entry['source']}  risk: {entry['risk']}")
        print(f"  action: {entry['action']}")
        print(f"  hash:   {entry['hash']}")
        print("  status: pending (recorded; nothing decided, nothing executed)")
    return 0


def cmd_list(args) -> int:
    """``list``: print the queue, oldest first, one line per request
    (or the full entries as JSON with ``--json``)."""
    entries = _store(args).list_requests(status=args.status, source=args.source)
    if args.json:
        slim = [{k: e[k] for k in ("id", "hash", "source", "risk", "action",
                                   "summary", "requested_by", "ingested_at",
                                   "status", "decision")} for e in entries]
        print(json.dumps(slim, indent=2, ensure_ascii=False))
        return 0
    if not entries:
        print(f"no {args.status} requests")
        return 0
    for e in entries:
        print(f"{e['id']}  [{e['status']}]  {e['source']}  risk={e['risk']}  "
              f"age={_age_text(e.get('ingested_at'))}  "
              f"hash={short_hash(e['hash'])}  {e['action']}")
    return 0


def cmd_show(args) -> int:
    """``show``: print one request in full, including the exact hash
    a decision must name. This is the view to review before deciding."""
    entry = _store(args).get_entry(args.id)
    if args.json:
        print(json.dumps(entry, indent=2, ensure_ascii=False))
    else:
        _print_entry_human(entry)
    return 0


def _decide(args, decision: str) -> int:
    """Shared body of ``approve`` and ``deny``: record the decision
    against the exact ``--hash`` the operator supplied. The store
    refuses (exit 1, nothing appended) when the hash does not match
    or the request was already decided. Recording a decision never
    carries the action out; the success output says so plainly."""
    note = getattr(args, "note", None) or getattr(args, "reason", None)
    event = _store(args).decide(args.id, decision, args.hash,
                                by=args.by, note=note)
    if args.json:
        print(json.dumps(event, indent=2, ensure_ascii=False))
    else:
        print(f"{decision}: {event['id']}")
        print(f"  hash: {event['hash']}")
        print(f"  by:   {event['by']} at {event['at']}")
        if event.get("note"):
            print(f"  note: {event['note']}")
        print(f"  {NOT_EXECUTED}")
    return 0


def cmd_verify(args) -> int:
    """Read-only whole-store integrity audit. Writes nothing, decides
    nothing: exit 0 when records, hashes, and ledger all agree,
    exit 1 with one line per problem when they do not."""
    report = _store(args).verify()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["ok"] else 1
    checked = report["checked"]
    print(f"verify: {'OK' if report['ok'] else 'FAILED'}")
    print(f"  records: {checked['records']}  "
          f"ledger events: {checked['ledger_events']}")
    print(f"  pending: {checked['pending']}  "
          f"approved: {checked['approved']}  denied: {checked['denied']}")
    for prob in report["problems"]:
        where = prob["id"] if prob["id"] else "store"
        print(f"  problem [{prob['check']}] {where}: {prob['detail']}")
    if report["ok"]:
        print("  every record recomputes to its stored hash and "
              "matches its ledger events")
    else:
        print("  nothing was changed; repair the store files by hand "
              "and re-run verify")
    return 0 if report["ok"] else 1


def cmd_history(args) -> int:
    """``history``: print ledger events in append order (ingested,
    approved, denied), optionally only those for one request id."""
    events = _store(args).history(req_id=getattr(args, "id", None))
    if args.json:
        print(json.dumps(events, indent=2, ensure_ascii=False))
        return 0
    if not events:
        print("no history")
        return 0
    for ev in events:
        extra = ""
        if ev.get("event") in ("approved", "denied"):
            extra = f" by {ev.get('by')}"
            if ev.get("note"):
                extra += f" note={ev['note']}"
        print(f"{ev.get('at')}  {ev.get('event')}  {ev.get('id')}  "
              f"hash={short_hash(ev.get('hash', ''))}{extra}")
    return 0


def main(argv=None) -> int:
    """Parse the command line and run one command.

    Returns the exit code: 0 on success, 1 when a decision (or an
    ingest with a duplicate id) is refused or ``verify`` found
    integrity problems, 2 on an invalid request or a store error.
    Refusals and errors are printed to stderr.
    """
    parser = argparse.ArgumentParser(
        prog="ghostapprove",
        description="One local approval queue for the Ghost stack. "
                    "Records decisions only; executes nothing, "
                    "approves nothing automatically.",
        epilog="examples:\n"
               "  ghostapprove --store .ghostapprove ingest examples/ghostbridge-request.json\n"
               "  ghostapprove --store .ghostapprove list\n"
               "  ghostapprove --store .ghostapprove show req-ghostbridge-001\n"
               "  ghostapprove --store .ghostapprove approve req-ghostbridge-001 --hash <exact-hash-from-show> --by ryan\n"
               "  ghostapprove --store .ghostapprove history\n"
               "\n"
               "exit codes: 0 success; 1 decision refused (hash mismatch, "
               "already decided, unknown id); 2 invalid request or store error.\n"
               "A recorded decision is never carried out by GhostApprove; "
               "the tool that asked reads the record and acts, or not, itself.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version",
                        version=f"ghostapprove {__version__}")
    parser.add_argument("--store", metavar="DIR",
                        help="store directory "
                             "(default: $GHOSTAPPROVE_DIR or ./.ghostapprove)")
    parser.add_argument("--queue", metavar="DIR",
                        help="alias for --store (queue directory)")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", dest="store_sub", default=None, metavar="DIR",
                        help="store directory (same as the global --store; "
                             "this one wins if both are given)")
    common.add_argument("--queue", dest="queue_sub", default=None, metavar="DIR",
                        help="alias for --store (queue directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", parents=[common],
                       help="ingest a local JSON request file into the queue",
                       description="Ingest one request JSON file into the "
                                   "queue and print its id and exact hash. "
                                   "The request starts out pending: nothing "
                                   "is decided and nothing is carried out.")
    p.add_argument("file", help="path to the request JSON file, or - to read it from stdin")
    p.add_argument("--json", action="store_true",
                   help="print the ingested record as JSON")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("list", parents=[common],
                       help="list queued requests (default: pending, oldest first)",
                       description="List the queue, oldest first. Each row "
                                   "shows the id, status, source, risk, age, "
                                   "short hash, and action.")
    p.add_argument("--status", default="pending",
                   choices=["pending", "approved", "denied", "all"],
                   help="which requests to show (default: pending)")
    p.add_argument("--source", metavar="NAME",
                   help="only show requests from this source (producer name)")
    p.add_argument("--json", action="store_true",
                   help="print as JSON, with the full hash for each request")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", parents=[common],
                       help="show one request in full: summary, diff, risk, exact hash",
                       description="Show one request in full. Review this "
                                   "view before deciding: it carries the "
                                   "exact hash a decision must name.")
    p.add_argument("id", help="request id, as printed by ingest or list")
    p.add_argument("--json", action="store_true",
                   help="print the full record as JSON")
    p.set_defaults(func=cmd_show)

    for name, helptext in (("approve", "record an approval against the exact hash"),
                           ("deny", "record a denial against the exact hash")):
        noun = "an approval" if name == "approve" else "a denial"
        p = sub.add_parser(name, parents=[common], help=helptext,
                           description=f"Record {noun} in the ledger, bound "
                                       "to the exact hash. Recording a "
                                       "decision does NOT carry the action out.")
        p.add_argument("id", help="request id, as printed by ingest or list")
        p.add_argument("--hash", required=True, metavar="HASH",
                       help="REQUIRED: the exact hash shown by 'show' for "
                            "this request; the decision is refused if it "
                            "does not match the hash on record")
        p.add_argument("--by", default="local-operator", metavar="NAME",
                       help="decider label recorded in the ledger "
                            "(default: local-operator; a label, not "
                            "an authentication)")
        p.add_argument("--note", metavar="TEXT",
                       help="optional note recorded with the decision")
        if name == "deny":
            p.add_argument("--reason", metavar="TEXT",
                           help="alias for --note (deny only)")
        p.add_argument("--json", action="store_true",
                       help="print the recorded ledger event as JSON")
        p.set_defaults(func=lambda a, d=name + "d" if name == "approve" else "denied": _decide(a, d))

    p = sub.add_parser("verify", parents=[common], aliases=["audit"],
                       help="audit the whole store read-only: every record "
                            "hash, ingested event, and decision event "
                            "must agree (records nothing, decides nothing)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("history", parents=[common],
                       help="show the append-only ledger in order",
                       description="Show the append-only ledger in order: "
                                   "every ingested, approved, and denied "
                                   "event, exactly as recorded.")
    p.add_argument("--id", metavar="ID", help="only show events for this request id")
    p.add_argument("--json", action="store_true",
                   help="print the events as JSON")
    p.set_defaults(func=cmd_history)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RefusedError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except (StoreError, RequestError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RecursionError:
        # Last-resort guard: a pathologically nested request file,
        # record, or ledger line must fail closed with a clean
        # error, never a traceback.
        print("error: input is nested too deeply", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
