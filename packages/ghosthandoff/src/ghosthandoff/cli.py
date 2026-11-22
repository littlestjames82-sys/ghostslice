"""GhostHandoff CLI: ``pack`` | ``show`` | ``mcp``.

Usage at a glance::

    ghosthandoff pack <project> [-o <dir>] [--since <when>] [--base <ref>]
    ghosthandoff show <pack-dir>
    ghosthandoff mcp

``pack`` is the main command: it reads repo facts from ``<project>``
and writes ``HANDOFF.md`` + ``handoff.json`` into the output
directory (default ``./handoff-out``). It never writes inside the
project unless ``-o`` points there.

Exit codes: 0 = done, 2 = could not build or read (bad path, pack
exists without ``--force``, pack missing). 1 is never used for a
built pack: a handoff pack is a report, not a verdict.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .pack import write_pack


def _cmd_pack(args) -> int:
    """Run ``pack``: build the pack and print a one-screen summary.

    Returns 0 on success (including a degraded pack, for example a
    non-git project) and 2 when the project path is not a directory
    or the pack cannot be written.
    """
    project = args.project
    if not os.path.isdir(project):
        print(f"ghosthandoff: project path is not a directory: {project}", file=sys.stderr)
        return 2
    out_dir = args.out or os.path.join(os.getcwd(), "handoff-out")
    try:
        data = write_pack(project, out_dir, since=args.since, base=args.base, force=args.force)
    except FileExistsError as exc:
        print(f"ghosthandoff: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ghosthandoff: could not write pack: {exc}", file=sys.stderr)
        return 2
    git = data.get("git") or {}
    summary = {
        "pack_markdown": data["pack"]["markdown"],
        "pack_json": data["pack"]["json"],
        "project": data["project"]["path"],
        "git_available": bool(git.get("available")),
        "commits_in_window": git.get("commit_count", 0) if git.get("available") else 0,
        "files_touched": git.get("files_changed_total", 0) if git.get("available") else 0,
        "markers": (data.get("markers") or {}).get("total", 0),
        "reports_found": len(data.get("reports", [])),
        "open_loops": len(data.get("open_loops", [])),
        "next_steps": len(data.get("next_steps", [])),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Handoff pack written: {summary['pack_markdown']}")
        print(f"Machine copy:         {summary['pack_json']}")
        print(f"Commits in window: {summary['commits_in_window']}, "
              f"files touched: {summary['files_touched']}, "
              f"markers: {summary['markers']}, reports: {summary['reports_found']}, "
              f"open loops: {summary['open_loops']}, next steps: {summary['next_steps']}")
        if not summary["git_available"]:
            print("Note: git section unavailable (not a git work tree). Pack still built.")
    return 0


def _cmd_show(args) -> int:
    """Run ``show``: print ``<pack-dir>/HANDOFF.md`` to stdout.

    Returns 0 when the file was printed, 2 when no ``HANDOFF.md``
    exists in the given directory.
    """
    md_path = os.path.join(args.pack_dir, "HANDOFF.md")
    if not os.path.isfile(md_path):
        print(f"ghosthandoff: no HANDOFF.md in {args.pack_dir}", file=sys.stderr)
        return 2
    with open(md_path, "r", encoding="utf-8", errors="replace") as fh:
        sys.stdout.write(fh.read())
    return 0


def _cmd_mcp(args) -> int:
    """Run ``mcp``: serve the stdio MCP server until stdin closes."""
    from .mcp_server import serve
    serve()
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the three subcommands.

    Kept separate from :func:`main` so tests and help tooling can
    inspect the CLI surface without running a command.
    """
    parser = argparse.ArgumentParser(
        prog="ghosthandoff",
        description="Build a session handoff pack from repo facts only. "
                    "Reads git state, session changes, verification reports "
                    "and TODO markers, then writes HANDOFF.md + handoff.json. "
                    "Propose-only and read-only on the project: never commits, "
                    "never pushes, never sends, never edits the project, "
                    "and never runs project code.",
        epilog="Examples:\n"
               "  ghosthandoff pack .                     # pack the repo in . (last 12h)\n"
               "  ghosthandoff pack ~/proj -o /tmp/out    # choose the output directory\n"
               "  ghosthandoff pack . --since 2h          # narrower session window\n"
               "  ghosthandoff pack . --since main        # session = commits in main..HEAD\n"
               "  ghosthandoff show ./handoff-out         # print a built pack\n"
               "  ghosthandoff mcp                        # stdio MCP server (local only)\n\n"
               "Exit codes: 0 = pack built or shown (a labelled degraded section "
               "still counts), 2 = could not build or read. "
               "See README.md for what each pack section contains and where "
               "each fact comes from.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"ghosthandoff {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "pack",
        help="build HANDOFF.md + handoff.json for a project",
        description="Build a handoff pack for PROJECT from repo facts only. "
                    "Writes HANDOFF.md (readable) and handoff.json (same facts, "
                    "machine readable) into the output directory and nowhere else. "
                    "The project itself is left byte-identical.",
        epilog="Session window (--since): omit it for the last 12 hours, use a "
               "duration (2h, 90m, 3d), an ISO date/time (2026-10-17), or a git "
               "ref (main, HEAD~5; the session is then ref..HEAD). Uncommitted "
               "changes are always included, whatever the window.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("project", help="project directory to describe (read-only; may be a plain folder, not only a git repo)")
    p.add_argument("-o", "--out", default=None,
                   help="output directory for HANDOFF.md + handoff.json "
                        "(default: ./handoff-out under the current directory, never inside the project)")
    p.add_argument("--since", default=None,
                   help="session window: duration (2h, 90m, 3d), ISO date/time, or a git ref "
                        "(default: last 12 hours; uncommitted changes are always included)")
    p.add_argument("--base", default=None,
                   help="also report diff stats against this ref (base...HEAD), e.g. --base main")
    p.add_argument("--force", action="store_true",
                   help="overwrite existing HANDOFF.md / handoff.json in the output directory "
                        "(without it, pack refuses and exits 2 if either file exists)")
    p.add_argument("--json", action="store_true",
                   help="print the run summary (pack paths and counts) as JSON instead of plain text")
    p.set_defaults(func=_cmd_pack)

    s = sub.add_parser(
        "show",
        help="print a built pack's HANDOFF.md",
        description="Print the HANDOFF.md inside PACK_DIR to stdout. "
                    "Exits 2 if PACK_DIR contains no HANDOFF.md.",
    )
    s.add_argument("pack_dir", help="directory containing HANDOFF.md (the -o directory from a pack run)")
    s.set_defaults(func=_cmd_show)

    m = sub.add_parser(
        "mcp",
        help="run the stdio MCP server (local only)",
        description="Run the stdio MCP server (local only, no network). Exposes "
                    "build_handoff (build a pack, returns capped summary counts and "
                    "pack paths) and read_handoff (returns HANDOFF.md, capped at "
                    "8000 characters).",
    )
    m.set_defaults(func=_cmd_mcp)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. ``argv`` defaults to ``sys.argv``; returns an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
