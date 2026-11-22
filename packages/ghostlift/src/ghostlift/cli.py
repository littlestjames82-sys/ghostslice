"""GhostLift command line: inspect and lift. Static analysis only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import LiftError, inspect_artifact, lift_path


def _print_inspect(info: dict) -> None:
    """Print an inspect report (from :func:`core.inspect_artifact`) as text."""
    print(f"{info['path']}")
    print(f"  kind: {info['kind']}  size: {info['size_bytes']} bytes")
    print(f"  sha256: {info['sha256']}")
    if info.get("liftable"):
        print(f"  tier: {info['tier']} ({info.get('tier_name')})  liftable: yes")
    else:
        print(f"  liftable: no")
    if info["kind"] == "pyc" and info.get("liftable"):
        print(f"  python: {info.get('python_version')}  magic: {info.get('magic')}")
        print(f"  embedded file: {info.get('embedded_filename')}")
        symbols = info.get("top_level_symbols") or []
        print(f"  top-level symbols: {', '.join(symbols) if symbols else '(none)'}")
    if info["kind"] == "sourcemap" and info.get("liftable"):
        print(
            f"  sources: {info.get('sources_recoverable')}/{info.get('sources_total')}"
            " recoverable"
        )
        for missing in info.get("sources_not_recovered") or []:
            print(f"  not recovered (no sourcesContent): {missing}")
    if info["kind"] == "javascript" and info.get("liftable"):
        functions = info.get("function_boundaries") or []
        print(
            f"  functions: {', '.join(functions) if functions else '(none)'}"
        )
    if info.get("note"):
        print(f"  note: {info['note']}")
    if info.get("error"):
        print(f"  error: {info['error']}")


def main(argv: list[str] | None = None) -> int:
    """Run the ``ghostlift`` command line and return its exit code.

    Exit codes: 0 = success (for ``inspect``, the artifact is
    liftable; for ``lift``, at least one file was lifted),
    1 = the artifact was read but is not liftable / nothing lifted,
    2 = missing path or another usage error.
    """
    parser = argparse.ArgumentParser(
        prog="ghostlift",
        description=(
            "Lift compiled / minified artifacts back to readable source "
            "GhostSlice can slice. Static analysis only: GhostLift never "
            "executes an artifact. For code you own or have the right "
            "to inspect."
        ),
        epilog=(
            "examples:\n"
            "  ghostlift inspect bundle.js.map\n"
            "  ghostlift inspect module.pyc --json\n"
            "  ghostlift lift bundle.js.map -o lifted/\n"
            "  ghostlift lift build-output/ -o lifted/\n"
            "\n"
            "Every lift is labelled by tier in the output manifest: "
            "tier 1 = exact recovery, tier 2 = structured "
            "reconstruction, tier 3 = outline (detect/report only)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"ghostlift {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser(
        "inspect",
        help="report what an artifact is and its tier, without lifting it",
        description=(
            "Report an artifact's kind, size, sha256, tier and whether "
            "the core CLI can lift it. Inspect never lifts, imports, or "
            "executes the artifact."
        ),
    )
    p_inspect.add_argument("path", type=Path, metavar="ARTIFACT",
                           help="artifact file to inspect (.pyc, .map, .js, ...)")
    p_inspect.add_argument("--json", action="store_true",
                            help="print the report as JSON instead of text")

    p_lift = sub.add_parser(
        "lift",
        help="lift an artifact (or a folder of them) into readable source",
        description=(
            "Lift an artifact (or every supported artifact in a folder: "
            ".pyc, .map and .js) into an output folder containing files/ "
            "plus a manifest.json that watermarks every file with its "
            "tier and source artifact."
        ),
    )
    p_lift.add_argument("path", type=Path, metavar="ARTIFACT_OR_FOLDER",
                        help="artifact file, or folder to scan for artifacts")
    p_lift.add_argument("-o", "--out", type=Path, required=True, metavar="OUT",
                        help="output folder for files/ + manifest.json")

    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            if not args.path.is_file():
                print(f"ghostlift: no such file: {args.path}", file=sys.stderr)
                return 2
            info = inspect_artifact(args.path)
            if args.json:
                print(json.dumps(info, indent=2))
            else:
                _print_inspect(info)
            return 0 if info.get("liftable") else 1
        if args.command == "lift":
            manifest = lift_path(args.path, args.out)
            totals = manifest["totals"]
            print(
                f"lifted {totals['files']} file(s) from "
                f"{totals['artifacts']} artifact(s) into {args.out}"
            )
            print(f"  manifest: {args.out / 'manifest.json'}")
            print(f"  estimated tokens (chars/4 estimate): {totals['tokens_estimate']}")
            for failure in manifest["failures"]:
                print(f"  not lifted: {failure['artifact']}: {failure['error']}")
            return 0 if manifest["files"] else 1
    except LiftError as exc:
        print(f"ghostlift: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
