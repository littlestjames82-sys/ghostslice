"""GhostFixture CLI.

  ghostfixture build <project> <bundle> -o <out-dir>
                     [--task "..." | --task-file f]
                     [--max-bytes N] [--include-flagged] [--json]
  ghostfixture check <fixture-dir> [--json]
  ghostfixture mcp

Exit codes: build 0 = fixture built, 1 = fixture would be empty,
2 = could not build. check 0 = clean, 1 = mismatch, 2 = could not
check. The source project is only ever read, never written.

Run ``ghostfixture --help``, ``ghostfixture build --help`` or
``ghostfixture check --help`` for the per-argument reference.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .build import (DEFAULT_MAX_BYTES, CheckError, FixtureError,
                    build_fixture, check_fixture)
from .bundle import BundleError


def _task_from(args) -> str:
    """Return the task text for a build.

    ``--task-file`` wins when both options are given: its contents
    are read as UTF-8 (undecodable bytes are replaced). Otherwise
    the ``--task`` string is used, defaulting to empty.
    """
    if getattr(args, "task_file", None):
        return Path(args.task_file).read_text(encoding="utf-8", errors="replace")
    return getattr(args, "task", "") or ""


def _cmd_build(args) -> int:
    """Run ``build`` and print a human summary (or the manifest with --json).

    Returns 0 when a fixture was built, 1 when nothing could be
    copied (empty fixture), and 2 when the build could not run at
    all (bad bundle, bad project, or a refused output location).
    """
    try:
        manifest = build_fixture(
            args.project, args.bundle, args.out,
            task=_task_from(args),
            max_bytes=args.max_bytes,
            include_flagged=args.include_flagged,
        )
    except (FixtureError, BundleError, OSError) as exc:
        print(f"ghostfixture: could not build: {exc}", file=sys.stderr)
        return 2
    t = manifest["totals"]
    if args.json:
        print(json.dumps(manifest, indent=2))
    else:
        print(f"GhostFixture built: {args.out}")
        print(f"  Size cap: {manifest['max_bytes']} bytes (total copied content)")
        print(f"  Included: {t['files_included']} files, {t['bytes_copied']} bytes "
              f"(bundle-referenced first, then static import closure)")
        if t.get("files_drifted"):
            print(f"  drift warning: {t['files_drifted']} copied file(s) differ from the "
                  "bundle's recorded content (project changed after export? see FIXTURE.md)")
        if t.get("files_upstream_disagreements"):
            print(f"  upstream disagreement: {t['files_upstream_disagreements']} copied "
                  "file(s) were flagged by the bundle's guard but not confirmed by the "
                  "shape scan (the flag and the disagreement are recorded; see FIXTURE.md)")
        for e in manifest["excluded_flagged"]:
            note = " (included by --include-flagged override)" if e.get("included_by_override") else ""
            print(f"  excluded-flagged: {e['path']} [{', '.join(e['types'])}]{note}")
        for e in manifest["left_out"]:
            print(f"  left out: {e['path']} ({e['reason']})")
        print(f"  Record: fixture-manifest.json + FIXTURE.md in {args.out}")
    if t["files_included"] == 0:
        print("ghostfixture: fixture is empty (nothing could be copied)", file=sys.stderr)
        return 1
    return 0


def _cmd_check(args) -> int:
    """Run ``check`` against a fixture directory.

    Returns 0 when the tree matches its manifest, 1 on any
    mismatch, and 2 when the fixture cannot be checked at all
    (for example, its manifest is missing or unreadable).
    """
    try:
        result = check_fixture(args.fixture)
    except CheckError as exc:
        print(f"ghostfixture: could not check: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    elif result["ok"]:
        extra = ""
        if result.get("ignored_runtime_byproducts"):
            extra = f", {len(result['ignored_runtime_byproducts'])} runtime byproducts ignored (__pycache__)"
        print(f"GhostFixture check: OK ({result['files_checked']} files verified{extra})")
    else:
        print("GhostFixture check: MISMATCH")
        for p in result["problems"]:
            print(f"  {p}")
    return 0 if result["ok"] else 1


def main(argv=None) -> int:
    """Parse arguments, dispatch to a subcommand, and return its exit code.

    With no subcommand, prints the top-level help and returns 2.
    ``mcp`` serves until its stdin closes and then returns 0.
    """
    parser = argparse.ArgumentParser(
        prog="ghostfixture",
        description="Minimal repro project generator for GhostSlice bundles: "
                    "turn a bundle back into a small, real directory tree. "
                    "Flagged secrets are excluded by default, and everything "
                    "left out is named with a reason.",
        epilog="Exit codes: build 0 = built, 1 = fixture would be empty, "
               "2 = could not build. check 0 = clean, 1 = mismatch, "
               "2 = could not check. The source project is only ever read.")
    parser.add_argument("--version", action="version", version=f"ghostfixture {__version__}")
    sub = parser.add_subparsers(dest="command")

    b = sub.add_parser(
        "build", help="build a fixture tree from a project + GhostSlice bundle",
        description="Build a fixture tree: copy every file the bundle "
                    "references, plus the static local import closure of "
                    "those files, from the original project into a new "
                    "output tree. The project is only read, never written.",
        epilog="Exit codes: 0 = fixture built, 1 = fixture would be empty, "
               "2 = could not build.")
    b.add_argument("project", help="path to the original project the bundle was cut from (read only)")
    b.add_argument("bundle", help="path to the GhostSlice bundle (its manifest.json selects the files)")
    b.add_argument("-o", "--out", required=True,
                   help="new output directory for the fixture; must not be inside "
                        "the project, must not contain the project, and an existing "
                        "non-empty directory is refused")
    b.add_argument("--task", default="",
                   help="short task description recorded in the manifest and "
                        "FIXTURE.md (default: none)")
    b.add_argument("--task-file", default=None, metavar="FILE",
                   help="read the task description from FILE instead of --task; "
                        "takes precedence when both are given")
    b.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, metavar="N",
                   help=f"cap on total copied content in bytes "
                        f"(default: {DEFAULT_MAX_BYTES}, 2 MiB); bundle-referenced "
                        f"files are kept first, files that do not fit are left out "
                        f"with reason 'size-cap'")
    b.add_argument("--include-flagged", action="store_true",
                   help="include secret-flagged files anyway (flags stay on record "
                        "in the manifest; there is no quiet override)")
    b.add_argument("--json", action="store_true",
                   help="print the full fixture manifest as JSON instead of the "
                        "human summary")
    b.set_defaults(func=_cmd_build)

    c = sub.add_parser(
        "check", help="re-verify a fixture tree against its manifest",
        description="Re-verify a fixture tree against its fixture-manifest.json: "
                    "every included file present with a matching sha256, no "
                    "unexplained extra files, no excluded file present.",
        epilog="Exit codes: 0 = clean, 1 = mismatch, 2 = could not check.")
    c.add_argument("fixture", help="path to a fixture directory built by 'ghostfixture build'")
    c.add_argument("--json", action="store_true",
                   help="print the check result as JSON instead of the human summary")
    c.set_defaults(func=_cmd_check)

    sub.add_parser("mcp", help="run the stdio MCP server (local only)",
                   description="Run the stdio MCP server (local only, no network). "
                               "Exposes build_fixture and check_fixture with capped "
                               "summary payloads and no file bodies.")

    args = parser.parse_args(argv)
    if args.command == "mcp":
        from .mcp_server import serve
        serve()
        return 0
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
