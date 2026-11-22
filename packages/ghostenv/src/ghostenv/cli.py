"""GhostEnv CLI.

  ghostenv scan    <project> [--json]
  ghostenv check   <project> [--json] [--env-file f] [--example-file f]
  ghostenv example <project> [-o path] [--stdout] [--force]
                             [--env-file f] [--example-file f]

Exit codes: 0 = contract complete / action done, 1 = blocking
findings (names missing with no default, a missing example file,
case mismatches, duplicates, malformed lines; the verdict names
exactly which), 2 = could not scan / refused. Soft and stale
findings never block. ``scan`` and ``check`` never write.
``example`` writes only the file named (or the project example file
with --force when it already exists). Values are never printed,
logged, or stored on any path: names + present/absent only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .doctor import build_report
from .examplegen import names_for_example, render_example
from .reports import render_scan_text, render_text


def _report_or_error(args):
    """Build the doctor report for ``args.project``.

    Returns ``None`` (after printing an error to stderr) when the
    project path is not a directory or the scan itself fails;
    callers turn that into exit 2.
    """
    project = Path(args.project)
    if not project.is_dir():
        print(f"error: project not found: {project}", file=sys.stderr)
        return None
    try:
        return build_report(
            project,
            env_file=getattr(args, "env_file", None),
            example_file=getattr(args, "example_file", None))
    except (OSError, ValueError) as exc:
        # Documented exit 2 is "could not scan": an unreadable env /
        # example file or a file vanishing mid-scan used to surface
        # as an unhandled traceback (exit 1, looking like blocking
        # findings). The message carries a path and errno only -
        # never file content - so the names-only rule still holds.
        print(f"error: could not scan {project}: {exc}",
              file=sys.stderr)
        return None


def cmd_scan(args) -> int:
    """``scan``: list the names used in code. Never writes. Exit 0,
    or 2 when the project cannot be scanned."""
    report = _report_or_error(args)
    if report is None:
        return 2
    if args.json:
        print(json.dumps({
            "tool": report["tool"], "version": report["version"],
            "project": report["project"],
            "names_only_statement": report["names_only_statement"],
            "used_in_code": report["sets"]["used_in_code"],
            "usages": report["usages"],
            "dynamic_sites": report["dynamic_sites"],
            "files_scanned": report["counts"]["files_scanned"],
        }, indent=2))
    else:
        print(render_scan_text(report))
    return 0


def cmd_check(args) -> int:
    """``check``: compare the three name sets. Never writes. The
    exit code is the report's: 0 complete, 1 blocking findings,
    2 could not scan."""
    report = _report_or_error(args)
    if report is None:
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))
    return int(report["exit_code"])


def cmd_example(args) -> int:
    """``example``: generate a names-only example file. Writes only
    the target file; refuses to overwrite any existing file without
    ``--force``, and refuses a real ``.env`` target even with
    ``--force`` (exit 2)."""
    report = _report_or_error(args)
    if report is None:
        return 2
    content = render_example(names_for_example(report))
    if args.stdout:
        print(content, end="")
        return 0
    project = Path(args.project)
    if args.output:
        target = Path(args.output)
    elif args.example_file:
        target = Path(args.example_file)
    else:
        target = project / ".env.example"
    # Never write to a real .env, even with --force or -o: the
    # README promises generation never modifies it, and a target
    # named .env - or resolving to the env file in use (which also
    # catches a symlinked .env.example pointing at .env) - is one.
    env_path = (Path(args.env_file) if getattr(args, "env_file", None)
                else project / ".env")
    try:
        resolves_to_env = target.resolve() == env_path.resolve()
    except (OSError, RuntimeError):
        resolves_to_env = False
    if target.name == ".env" or resolves_to_env:
        print(f"error: refusing to write {target}: that is a real "
              f".env file; choose an example-file path instead",
              file=sys.stderr)
        return 2
    # PLAN: generation refuses to overwrite ANY existing file
    # without --force. The old `and not args.output` exemption made
    # -o silently clobber whatever it pointed at.
    if target.exists() and not args.force:
        print(f"error: {target} already exists; pass --force to "
              f"overwrite or -o <path> to write elsewhere",
              file=sys.stderr)
        return 2
    try:
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {target}: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {target} "
          f"({len(names_for_example(report))} names, values never "
          f"included)")
    return 0


def _add_files(p):
    """Add the shared --env-file / --example-file options."""
    p.add_argument("--env-file", metavar="FILE",
                   help="path to the .env file "
                        "(default: <project>/.env)")
    p.add_argument("--example-file", metavar="FILE",
                   help="path to the example file "
                        "(default: first of "
                        ".env.example/.env.sample/"
                        ".env.template in the project root)")


def main(argv=None) -> int:
    """Parse arguments and dispatch to a subcommand.

    Returns the subcommand's exit code (see the module docstring):
    0 = done / contract complete, 1 = blocking findings,
    2 = could not scan / refused.
    """
    parser = argparse.ArgumentParser(
        prog="ghostenv",
        description="Local .env doctor: env var names used in code vs "
                    "defined in .env vs documented in .env.example. "
                    "Names only - values are never read into output.",
        epilog="examples:\n"
               "  ghostenv scan ~/my-project\n"
               "  ghostenv check ~/my-project\n"
               "  ghostenv check ~/my-project --json\n"
               "  ghostenv example ~/my-project --stdout\n\n"
               "exit codes: 0 = done / contract complete, "
               "1 = blocking findings (check only; the verdict "
               "names them), 2 = could not scan / refused.\n"
               "scan and check never write files. example writes "
               "only the file it names.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version",
                        version=f"ghostenv {__version__}")
    sub = parser.add_subparsers(dest="command", required=True,
                                metavar="{scan,check,example}")

    p = sub.add_parser(
        "scan", help="list env var names used in code",
        description="List the environment variable names the "
                    "project's code reads, with file and line for "
                    "each read site. Names only; writes nothing.")
    p.add_argument("project", help="path to the project directory "
                                   "to scan")
    p.add_argument("--json", action="store_true",
                   help="print the report as JSON instead of text")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser(
        "check", help="compare code / .env / example name sets and "
                      "classify drift",
        description="Compare three name sets - used in code, "
                    "defined in .env, documented in the example "
                    "file - and classify the drift. Names only; "
                    "writes nothing. Exit 0 = contract complete, "
                    "1 = blocking findings (the verdict names "
                    "exactly which), 2 = could not scan.")
    p.add_argument("project", help="path to the project directory "
                                   "to check")
    p.add_argument("--json", action="store_true",
                   help="print the full report as JSON instead of "
                        "text")
    _add_files(p)
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser(
        "example", help="generate a clean, names-only .env.example",
        description="Generate a clean .env.example from names "
                    "only: every name used in code, defined in "
                    ".env, or already documented, each as NAME= "
                    "with an empty value. Your real .env is never "
                    "modified and no value is ever copied.")
    p.add_argument("project", help="path to the project directory")
    p.add_argument("-o", "--output", metavar="FILE",
                   help="write here instead of "
                        "<project>/.env.example")
    p.add_argument("--stdout", action="store_true",
                   help="print to stdout instead of writing a file")
    p.add_argument("--force", action="store_true",
                   help="overwrite an existing example file "
                        "(without this, an existing target "
                        "is refused with exit 2)")
    _add_files(p)
    p.set_defaults(fn=cmd_example)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
