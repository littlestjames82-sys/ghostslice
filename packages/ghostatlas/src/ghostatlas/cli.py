"""GhostAtlas command-line interface.

Usage:

  ghostatlas build <project> [-o atlas.html] [--brief ATLAS.md]
                             [--audience onboarding|diligence]
                             [--top N] [--json-out atlas.json]
  ghostatlas scan  <project> [--audience onboarding|diligence]

``build`` writes a self-contained ``atlas.html`` module map and an
``ATLAS.md`` architecture brief from a single run, so their numbers
always agree. ``scan`` prints the same assembled run data as JSON to
stdout and writes no artifacts, which is handy for piping or for a
quick look at a project.

Building never modifies the project's source files.

Exit codes: 0 ok, 1 runtime failure, 2 usage/config errors (the
GhostSlice convention: a malformed atlas section in .ghostslice.json
is exit 2 and names the offending key).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .brief import build_brief
from .data import build_atlas_data
from .render import build_html


def _parser():
    """Build the argument parser for the ``ghostatlas`` command.

    Kept separate from :func:`main` so the help text can be rendered
    (and tested) without running a build.
    """
    p = argparse.ArgumentParser(
        prog="ghostatlas",
        description="Human codebase map built on GhostSlice data "
                    "(stdlib only, offline, no network calls).",
        epilog="Examples:\n"
               "  ghostatlas build ~/my-project\n"
               "  ghostatlas build ~/my-project -o ~/atlas.html --audience diligence\n"
               "  ghostatlas scan ~/my-project\n\n"
               "Exit codes: 0 ok, 1 runtime failure, 2 usage/config error.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"ghostatlas {__version__}")
    sub = p.add_subparsers(dest="cmd")
    b = sub.add_parser(
        "build", help="build atlas.html + ATLAS.md for a project",
        description="Build a self-contained atlas.html module map and an "
                    "ATLAS.md architecture brief for a project, from one run.",
        epilog="Example:\n"
               "  ghostatlas build ~/my-project -o ~/atlas.html --top 15",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    b.add_argument("project",
                   help="path to the project directory to map (read only; "
                        "the project is never modified)")
    b.add_argument("-o", "--out", default=None,
                   help="HTML output path (default: <project>/atlas.html)")
    b.add_argument("--brief", default=None,
                   help="brief output path (default: next to the HTML as ATLAS.md; "
                        "'none' skips the brief)")
    b.add_argument("--audience", choices=("onboarding", "diligence"),
                   default="onboarding",
                   help="brief ordering: onboarding (default) leads with layout "
                        "and the reading order; diligence leads with size, tests, "
                        "secrets counts, dependencies, and licences")
    b.add_argument("--top", type=int, default=10,
                   help="reading-order length (default: 10)")
    b.add_argument("--json-out", default=None,
                   help="also write the assembled atlas data as JSON to this path")
    s = sub.add_parser(
        "scan", help="print atlas data as JSON (no artifacts written)",
        description="Assemble the atlas data for a project and print it "
                    "as JSON to stdout. Writes no files.",
        epilog="Example:\n"
               "  ghostatlas scan ~/my-project > atlas.json",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    s.add_argument("project",
                   help="path to the project directory to scan (read only)")
    s.add_argument("--audience", choices=("onboarding", "diligence"),
                   default="onboarding",
                   help="audience recorded in the data (default: onboarding)")
    return p


def main(argv=None) -> int:
    """Run the CLI and return its exit code (see the module docstring).

    ``argv`` defaults to ``sys.argv`` via argparse; tests and other
    callers can pass an explicit argument list instead.
    """
    args = _parser().parse_args(argv)
    if not args.cmd:
        _parser().print_help()
        return 2
    try:
        data = build_atlas_data(args.project, audience=args.audience)
    except ValueError as exc:
        print(f"ghostatlas: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # runtime failure, named, no traceback dump
        print(f"ghostatlas: failed: {exc}", file=sys.stderr)
        return 1

    if args.cmd == "scan":
        print(json.dumps(data.to_dict(), indent=2))
        return 0

    top_n = max(1, args.top)
    out = Path(args.out) if args.out else Path(args.project) / "atlas.html"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(build_html(data, top_n=top_n), encoding="utf-8")
        brief_path = None
        if (args.brief or "").lower() != "none":
            brief_path = Path(args.brief) if args.brief else out.with_name("ATLAS.md")
            brief_path.parent.mkdir(parents=True, exist_ok=True)
            brief_path.write_text(build_brief(data, top_n=top_n), encoding="utf-8")
        if args.json_out:
            json_path = Path(args.json_out)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(data.to_dict(), indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"ghostatlas: cannot write output: {exc}", file=sys.stderr)
        return 1
    print(f"GhostAtlas: {data.title}")
    print(f"  files: {len(data.files)}  estimated tokens: {data.total_tokens}  "
          f"engine: {data.engine}  audience: {data.audience}")
    print(f"  html:  {out}")
    if brief_path:
        print(f"  brief: {brief_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
