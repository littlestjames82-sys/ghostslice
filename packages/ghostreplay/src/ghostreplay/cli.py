"""GhostReplay command-line interface.

GhostReplay is propose-only: it learns from recorded agent session
transcripts you already have on disk and proposes GhostSlice profile
improvements with evidence. It never applies a change on its own.
The only command that writes a profile is ``apply``, and only after
it prints the diff and you type ``yes`` in the terminal.

Typical workflow (see ``README.md`` for the full quickstart)::

    ghostreplay ingest  <project> <transcript>
    ghostreplay analyse <project> <session-or-transcript> [--bundle <dir>]
    ghostreplay propose <project> <session...> [--bundle <dir>]
    ghostreplay apply   <project> [--proposal <file>]
    ghostreplay restore <project>     # undo an apply
    ghostreplay trend   <project>     # waste over time

Commands:
  ingest
      Parse the ONE documented format (Claude Code session
      JSON/JSONL, see :mod:`ghostreplay.transcript`) into a
      canonical session at ``<dir>/<session-id>.json``
      (default ``<project>/.ghostreplay/``). Run this once per
      transcript if you want a stable file to pass to ``analyse``
      and ``propose``; those commands also accept a raw transcript
      directly, so ``ingest`` is optional.
  analyse (alias: analyze)
      Analyse one session against its GhostSlice bundle, write
      ``REPLAY.md`` + ``replay-report.json`` (default
      ``<project>/.ghostreplay/reports/<session-id>/``), and append
      one record to the trend ledger
      (``<project>/.ghostreplay-history.jsonl``).
  propose
      Aggregate at least ``min_sessions`` sessions (default 3) into
      a profile proposal (``ghostreplay-proposal.json`` +
      ``PROPOSAL.md``). Proposal only: nothing is applied.
  apply
      Print the proposal diff, require an explicit ``yes`` typed
      in the terminal, back the profile up to
      ``.ghostslice.json.bak``, then apply. There is deliberately
      NO ``--yes`` flag: the yes must be typed interactively.
  restore
      Undo an ``apply`` from ``.ghostslice.json.bak`` (or remove a
      profile GhostReplay created when none existed before).
  trend
      Print session cost and waste over time from the ledger.

Exit codes:
  0  ok. Note: answering anything other than ``yes`` at the
     ``apply`` prompt also exits 0: a human said no, that is not
     an error.
  1  findings-level refusal (for example, no terminal input was
     available for the ``apply`` prompt, so nothing was applied).
  2  user error (bad input, unrecognised transcript format,
     invalid profile or proposal).

Local files only; no network anywhere. Run
``ghostreplay <command> --help`` for per-command arguments,
defaults, and examples.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import __version__
from .analysis import analyse_session
from .bundle import BundleError, find_bundle
from .ledger import append_record, read_records, trend_summary
from .profile import (apply_changes, load_replay_config,
                      read_profile_data, restore_profile)
from .propose import build_proposal, load_proposal, write_proposal
from .report import write_reports
from .transcript import TranscriptError, load_session, parse_transcript, dump_canonical


def _err(msg: str) -> int:
    print(f"ghostreplay: {msg}", file=sys.stderr)
    return 2


def _safe_session_component(session_id) -> str:
    """A sessionId comes from the transcript, i.e. untrusted data.
    Used as a filename / directory component it must never contain
    a path separator or '..': '../../x' would otherwise write the
    canonical session (ingest) or reports (analyse) outside the
    directory the user pointed --out / the project at."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "-",
                  str(session_id or "")).lstrip(".")
    return safe or "session"


def _load(project: Path, session_path: str, bundle_arg):
    session = load_session(session_path)
    bundle = find_bundle(project, bundle_arg)
    return session, bundle


def cmd_ingest(args) -> int:
    """Implement ``ingest``: parse one transcript to a canonical file."""
    project = Path(args.project)
    try:
        session = parse_transcript(args.transcript)
    except TranscriptError as exc:
        return _err(str(exc))
    out_dir = Path(args.out) if args.out else project / ".ghostreplay"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{_safe_session_component(session['session_id'])}.json"
    out.write_text(dump_canonical(session), encoding="utf-8")
    print(f"ingested session {session['session_id']}: "
          f"{session['entry_count']} entries, "
          f"{session['turn_count']} turns -> {out}")
    if session["secret_findings"]:
        print(f"secret-shaped findings (values never stored): "
              f"{len(session['secret_findings'])} - see canonical "
              "file's secret_findings (source + line + type only)")
    return 0


def cmd_analyse(args) -> int:
    """Implement ``analyse``/``analyze``: one session, reports + ledger."""
    project = Path(args.project)
    try:
        session, bundle = _load(project, args.session, args.bundle)
        report = analyse_session(session, bundle, project)
    except (TranscriptError, BundleError, ValueError) as exc:
        return _err(str(exc))
    out_dir = Path(args.out) if args.out else (
        project / ".ghostreplay" / "reports"
        / _safe_session_component(session["session_id"]))
    json_path, md_path = write_reports(report, out_dir)
    append_record(project, report)
    t = report["totals"]
    print(f"session {report['session_id']}: {report['turn_count']} turns")
    if bundle:
        print(f"sent (est.): {t['sent_sliced_estimated_tokens']} tokens; "
              f"not referenced in transcript (est.): "
              f"{t['not_referenced_estimated_tokens']}; re-read waste "
              f"(est.): {t['reread_waste_estimated_tokens']}; mode "
              f"friction files: {len(report['mode_friction']['files'])}")
    else:
        print("no bundle manifest joined: sent-vs-referenced, "
              "re-read cost and friction unavailable")
    print(f"reports -> {md_path} , {json_path}")
    print(f"ledger -> {project / '.ghostreplay-history.jsonl'}")
    return 0


def cmd_propose(args) -> int:
    """Implement ``propose``: aggregate sessions, write a proposal only."""
    project = Path(args.project)
    try:
        cfg = load_replay_config(project)
        reports = []
        blocks: list[dict] = []
        for session_path in args.sessions:
            session, bundle = _load(project, session_path, args.bundle)
            reports.append(analyse_session(session, bundle, project))
            for turn in session.get("turns", []):
                for block in turn.get("instruction_blocks", []):
                    blocks.append({"session_id": session["session_id"],
                                   "turn": turn["turn"], "text": block})
        data, _ = read_profile_data(project)
    except (TranscriptError, BundleError, ValueError) as exc:
        return _err(str(exc))
    proposal = build_proposal(
        str(project), reports, blocks, cfg,
        current_modes=data.get("modes") or {},
        current_entry_points=data.get("entry_points") or [])
    out_dir = Path(args.out) if args.out else project / ".ghostreplay"
    json_path, md_path = write_proposal(proposal, out_dir)
    print(f"sessions analysed: {proposal['sessions_analysed']} "
          f"(minimum {proposal['min_sessions_required']}); status: "
          f"{proposal['status']}; profile changes proposed: "
          f"{len(proposal['changes'])}; recall candidates: "
          f"{len(proposal['recall_candidates'])}; re-read hotspots: "
          f"{len(proposal.get('reread_hotspots') or [])}")
    print(f"proposal -> {md_path} , {json_path}")
    print("nothing applied: run `ghostreplay apply` and type yes "
          "to apply")
    return 0


def cmd_apply(args) -> int:
    """Implement ``apply``: show the diff, require a typed ``yes``, apply."""
    project = Path(args.project)
    proposal_path = Path(args.proposal) if args.proposal else (
        project / ".ghostreplay" / "ghostreplay-proposal.json")
    try:
        proposal = load_proposal(proposal_path)
    except ValueError as exc:
        return _err(str(exc))
    changes = [c for c in proposal["changes"]
               if c.get("kind") in ("mode", "entry_point")]
    print(f"Proposal from {proposal_path}: "
          f"{len(proposal['changes'])} change(s) "
          f"({proposal['sessions_analysed']} sessions analysed)")
    for c in proposal["changes"]:
        print(f"  - {c['kind']}: {c['target']}: {c['current']} -> "
              f"{c['proposed']}")
        print(f"    evidence: {c['evidence']}")
    if not changes:
        print("proposal has no profile changes; nothing to apply")
        return 0
    try:
        answer = input("Apply these changes to .ghostslice.json? "
                       "Type yes to apply: ")
    except EOFError:
        print("no input available; not applied")
        return 1
    if answer.strip().lower() not in ("yes", "y"):
        print("not applied (explicit yes not given)")
        return 0
    try:
        result = apply_changes(project, proposal["changes"])
    except ValueError as exc:
        return _err(str(exc))
    backup = result["backup"] or "(no prior profile existed)"
    print(f"applied {result['applied']} change(s) to "
          f"{project / '.ghostslice.json'}; backup: {backup}")
    print(f"undo any time with: ghostreplay restore {project}")
    return 0


def cmd_restore(args) -> int:
    """Implement ``restore``: undo the most recent ``apply``."""
    project = Path(args.project)
    try:
        msg = restore_profile(project)
    except ValueError as exc:
        return _err(str(exc))
    print(msg)
    return 0


def cmd_trend(args) -> int:
    """Implement ``trend``: summarise the ledger, one row per session."""
    project = Path(args.project)
    summary = trend_summary(read_records(project))
    if summary["records"] == 0:
        print("no GhostReplay history yet "
              f"({project / '.ghostreplay-history.jsonl'} is empty "
              "or missing); run analyse first")
        return 0
    print(f"sessions: {summary['sessions']} "
          f"(ledger records: {summary['records']})")
    print(f"{'recorded at':<28} {'session':<22} {'sent est.':>10} "
          f"{'waste est.':>11} {'waste %':>8}")
    for row in summary["rows"]:
        print(f"{(row.get('ts') or '')[:27]:<28} "
              f"{(row.get('session_id') or '')[:21]:<22} "
              f"{row.get('sent_sliced_estimated_tokens', 0):>10} "
              f"{row.get('estimated_waste_tokens', 0):>11} "
              f"{row.get('estimated_waste_percent', 0.0):>8}")
    print(f"mean waste: {summary['mean_waste_percent']}% "
          f"(first {summary['first_waste_percent']}%, "
          f"last {summary['last_waste_percent']}%); "
          f"total re-read waste (est.): "
          f"{summary['total_reread_waste_estimated_tokens']} tokens")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Help text only: argument names, defaults, and destinations here
    are the CLI contract (see ``tests/test_cli_contract.py``) and
    must not change without updating the contract.
    """
    ap = argparse.ArgumentParser(
        prog="ghostreplay",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="GhostReplay: learn from local agent session "
                    "transcripts, propose GhostSlice profile "
                    "improvements with evidence (propose-only).",
        epilog="Workflow:\n"
               "  1. ingest   (optional) register a transcript\n"
               "  2. analyse  report on one session\n"
               "  3. propose  draft profile changes from 3+ sessions\n"
               "  4. apply    apply a proposal after a typed yes\n"
               "     restore  undo an apply; trend shows waste over time\n"
               "\n"
               "Examples:\n"
               "  ghostreplay analyse ./my-project ./session.jsonl "
               "--bundle ./my-project-context\n"
               "  ghostreplay propose ./my-project s1.jsonl s2.jsonl "
               "s3.jsonl --bundle ./my-project-context\n"
               "\n"
               "Local files only; no network. Token figures are "
               "estimates. Run 'ghostreplay <command> --help' for "
               "per-command help.")
    ap.add_argument("--version", action="version",
                    version=f"ghostreplay {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "ingest",
        help="parse a transcript into a canonical session",
        description="Parse one transcript in the documented Claude "
                    "Code JSONL / JSON format into a canonical "
                    "session file. Optional: 'analyse' and "
                    "'propose' also accept a raw transcript "
                    "directly.",
        epilog="Example:\n"
               "  ghostreplay ingest ./my-project "
               "~/sessions/session.jsonl\n"
               "  # writes ./my-project/.ghostreplay/<session-id>.json")
    p.add_argument("project",
                   help="project directory (used for the default "
                        "output location)")
    p.add_argument("transcript",
                   help="path to a Claude Code transcript "
                        "(.jsonl, one JSON object per line, or a "
                        "single JSON document; see README)")
    p.add_argument("-o", "--out",
                   help="output directory "
                        "(default: <project>/.ghostreplay/)")
    p.set_defaults(fn=cmd_ingest)

    for name in ("analyse", "analyze"):
        p = sub.add_parser(
            name,
            help="analyse one session",
            description="Analyse one session against the "
                        "GhostSlice bundle that produced it. Writes "
                        "REPLAY.md and replay-report.json and "
                        "appends one record to the trend ledger.",
            epilog="Example:\n"
                   "  ghostreplay analyse ./my-project "
                   "./session.jsonl --bundle ./my-project-context "
                   "--out /tmp/replay-out")
        p.add_argument("project",
                       help="project directory the session ran in")
        p.add_argument("session",
                       help="canonical session file from 'ingest', "
                            "or a raw transcript (parsed on the fly)")
        p.add_argument("--bundle", help="GhostSlice bundle dir or "
                                        "manifest.json (default: "
                                        "<project>/.claude_context; "
                                        "if none is found, bundle "
                                        "comparisons are reported as "
                                        "unavailable, not guessed)")
        p.add_argument("-o", "--out",
                       help="output directory (default: "
                            "<project>/.ghostreplay/reports/"
                            "<session-id>/)")
        p.set_defaults(fn=cmd_analyse)

    p = sub.add_parser(
        "propose",
        help="aggregate sessions into a profile proposal",
        description="Aggregate sessions into a proposed "
                    ".ghostslice.json profile diff with evidence "
                    "per change. Proposal only: this command never "
                    "modifies your profile. Use 'apply' for that.",
        epilog="Example:\n"
               "  ghostreplay propose ./my-project s1.jsonl "
               "s2.jsonl s3.jsonl --bundle ./my-project-context\n"
               "  # writes ghostreplay-proposal.json + PROPOSAL.md")
    p.add_argument("project",
                   help="project directory containing (or to "
                        "contain) .ghostslice.json")
    p.add_argument("sessions", nargs="+",
                   help="session or transcript files, one per "
                        "recorded session; at least 3 by default "
                        "(tunable via the profile's 'replay' "
                        "section) or the proposal is marked "
                        "insufficient-sessions with no changes")
    p.add_argument("--bundle",
                   help="GhostSlice bundle dir or manifest.json "
                        "(default: <project>/.claude_context)")
    p.add_argument("-o", "--out",
                   help="output directory "
                        "(default: <project>/.ghostreplay/)")
    p.set_defaults(fn=cmd_propose)

    p = sub.add_parser(
        "apply",
        help="apply a proposal after an explicit terminal yes",
        description="Print a proposal's diff, ask for an explicit "
                    "'yes' typed in the terminal, back the current "
                    "profile up to .ghostslice.json.bak, then apply. "
                    "There is deliberately no --yes flag.",
        epilog="Example:\n"
               "  ghostreplay apply ./my-project "
               "--proposal /tmp/replay-prop/ghostreplay-proposal.json\n"
               "Undo with: ghostreplay restore ./my-project")
    p.add_argument("project",
                   help="project directory whose .ghostslice.json "
                        "will be updated (after your typed yes)")
    p.add_argument("--proposal",
                   help="proposal JSON file (default: "
                        "<project>/.ghostreplay/"
                        "ghostreplay-proposal.json)")
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser(
        "restore",
        help="undo an apply",
        description="Undo an 'apply': restore .ghostslice.json "
                    "from .ghostslice.json.bak, or remove a profile "
                    "GhostReplay created when none existed before.")
    p.add_argument("project",
                   help="project directory to restore")
    p.set_defaults(fn=cmd_restore)

    p = sub.add_parser(
        "trend",
        help="session trend from the ledger",
        description="Show estimated cost and waste per session "
                    "over time, read from "
                    "<project>/.ghostreplay-history.jsonl. Run "
                    "'analyse' at least once first so the ledger "
                    "has records.")
    p.add_argument("project",
                   help="project directory whose ledger to read")
    p.set_defaults(fn=cmd_trend)
    return ap


def main(argv=None) -> int:
    """Entry point: parse ``argv`` (default: ``sys.argv``) and dispatch."""
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
