"""GhostExposure command-line interface: scan / export / verify / packs.

Commands:
    scan    Preview the in/out decision for every file in a project.
    export  Write a bundle folder (files/, manifest.json, exposure.json,
            EXPOSURE.md, PROMPT.md) for a surface.
    verify  Check a received bundle folder against its manifest and
            partition, naming any discrepancy.
    packs   Print a surface pack's summary and patterns so the definition
            can be read before it is used.

All commands run locally and make no network calls. The tool records
evidence only (decisions, reasons, and hashes); it issues no verdict
about the code in a bundle.

Exit codes:
    0  Success. For scan: no conflicts. For verify: the bundle matches
       its manifest.
    1  Scan found conflicts, or verify found a mismatch.
    2  The command stopped before completing (for example an unresolved
       conflict at export, a non-empty output folder, or an unreadable
       surface pack). The message on stderr says which.

Run ``ghostexposure <command> --help`` for per-command options and
examples.
"""
import argparse
import json
import sys
from pathlib import Path

from . import CANNOT_PROVE_STATEMENT, COVERAGE_STATEMENT, __version__
from .exporter import ExportError, export_bundle, verify_bundle
from .inventory import build_inventory, inventory_hash
from .partition import (
    build_partition,
    load_profile_pins,
    partition_counts,
    pattern_coverage,
)
from .surface import SurfaceError, load_pack, pack_summary


def _load(args):
    """Load the surface pack named by ``args.surface`` (starter if None)."""
    return load_pack(getattr(args, "surface", None))


def cmd_scan(args):
    """Run ``scan``: print the proposed partition for a project.

    Prints one line per inventory file with its decision and reason
    codes, followed by counts, the coverage statement, and any pack
    coverage limits. With ``--json``, prints a single JSON document
    with the same information instead.

    Returns 1 when the partition contains conflicts, otherwise 0.
    """
    pack = _load(args)
    project = Path(args.project)
    pins = load_profile_pins(project)
    entries = build_inventory(project)
    partition = build_partition(entries, pack, pins)
    counts = partition_counts(partition)
    coverage = pattern_coverage(partition, pack)
    if args.json:
        print(json.dumps({
            "surface_pack": pack_summary(pack),
            "inventory_hash": inventory_hash(entries),
            "counts": counts, "partition": partition,
            "pattern_coverage": coverage,
            "coverage_statement": COVERAGE_STATEMENT,
            "coverage_limits": pack.get("coverage_limits", []),
        }, indent=2))
    else:
        print(f"GhostExposure scan: {project}")
        print(f"Surface pack: {pack['id']} {pack['version']} ({pack['date']})")
        for d in partition:
            codes = ",".join(r["code"] for r in d["reasons"]) or "-"
            print(f"  {d['decision']:9} {d['path']}  [{codes}]")
            for r in d["reasons"]:
                loc = ""
                if r.get("lines"):
                    loc = " (lines: " + ",".join(
                        str(n) for n in r["lines"]) + ")"
                print(f"              {r['code']}: {r['reason']}{loc}")
        print(f"Counts: {counts}")
        print("Pattern coverage:")
        for cov in coverage:
            if cov["matched_files"]:
                print(f"  {cov['pattern_id']}: "
                      f"{cov['matched_file_count']} file(s): "
                      + ", ".join(cov["matched_files"]))
            else:
                print(f"  {cov['pattern_id']}: no files matched "
                      "(no matches recorded)")
        print(COVERAGE_STATEMENT)
        for item in pack.get("coverage_limits", []):
            print(f"  - {item}")
        if counts["conflict"]:
            print("Conflicts are listed above as 'conflict'. They require a "
                  "human decision: change the pin or the pack. They are not "
                  "resolved by this tool.")
    return 1 if counts["conflict"] else 0


def cmd_export(args):
    """Run ``export``: write a bundle folder for a project.

    Delegates to :func:`ghostexposure.exporter.export_bundle`. Prints
    the bundle location, the surface/context/out/conflict counts, any
    redaction records (path, line, and type only), and the coverage
    statement.

    Returns 0 on success, or 2 when export stops (see ExportError).
    """
    pack = _load(args)
    try:
        result = export_bundle(
            args.project, args.output, pack,
            allow_unredacted=args.allow_unredacted,
            exclude_conflicts=args.exclude_conflicts)
    except ExportError as e:
        print(f"export stopped: {e}", file=sys.stderr)
        return 2
    c = result["counts"]
    print(f"Bundle written to {result['out']}")
    print(f"Files in bundle: {c['surface']} surface + {c['context']} context; "
          f"not in bundle: {c['out']}; conflicts: {c['conflict']}")
    if result["redactions"]:
        print(f"Redactions recorded: {len(result['redactions'])} "
              "(path + line + type in exposure.json, values never recorded)")
        for r in result["redactions"]:
            print(f"  {r['path']}:{r['line']} {r['type']}")
    print(COVERAGE_STATEMENT)
    return 0


def cmd_verify(args):
    """Run ``verify``: check a bundle folder against its manifest.

    Delegates to :func:`ghostexposure.exporter.verify_bundle`. Prints
    whether the bundle matches, one line per problem naming the
    discrepancy, and the limit statements that accompany every
    verification. With ``--json``, prints a single JSON document
    instead.

    Returns 0 when the bundle matches its manifest, otherwise 1.
    """
    ok, problems, notes = verify_bundle(args.bundle)
    if args.json:
        print(json.dumps({"matches_manifest": ok, "problems": problems,
                          "notes": notes}, indent=2))
    else:
        if ok:
            print("Bundle on disk matches its manifest and partition.")
        else:
            print("Bundle does NOT match its manifest:")
            for p in problems:
                print(f"  - {p}")
        for n in notes:
            print(n)
    return 0 if ok else 1


def cmd_packs(args):
    """Run ``packs``: print a surface pack summary and its patterns.

    Use this to read the exact definition a scan or export would apply
    before running it. Returns 0.
    """
    pack = _load(args)
    print(json.dumps(pack_summary(pack), indent=2))
    for p in pack["patterns"]:
        print(f"  {p['id']} | {p['kind']} | {p['pattern']} | {p['reason']}")
    return 0


def main(argv=None):
    """Parse arguments and dispatch to a subcommand.

    ``argv`` defaults to ``sys.argv`` (argparse behaviour when None).
    Returns the subcommand's exit code. An unreadable surface pack or
    an invalid value is reported on stderr and returns 2.
    """
    ap = argparse.ArgumentParser(
        prog="ghostexposure",
        description="Prepare a scoped bundle of a sensitive surface, with a "
                    "recorded partition of what is in the bundle and what is not.",
        epilog="Examples:\n"
               "  ghostexposure scan ./my-project --surface surfaces/starter.json\n"
               "  ghostexposure export ./my-project --surface surfaces/starter.json -o ./my-bundle\n"
               "  ghostexposure verify ./my-bundle\n"
               "  ghostexposure packs --surface surfaces/starter.json\n"
               "\n"
               "All commands run locally; no command makes a network call.\n"
               "Exit codes: 0 = success, 1 = conflicts (scan) or mismatch "
               "(verify), 2 = stopped before completing.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version",
                    version=f"ghostexposure {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "export"):
        if name == "scan":
            p = sub.add_parser(
                name,
                help="preview the in/out decision for every file in a project",
                description="Scan a project against a surface pack and print "
                            "the proposed decision (surface, context, out, or "
                            "conflict) and reason codes for every file, plus "
                            "counts and the pack's coverage limits. Nothing "
                            "is written.",
                epilog="Example:\n"
                       "  ghostexposure scan ./my-project --surface pack.json\n"
                       "  ghostexposure scan ./my-project --surface pack.json --json\n"
                       "\n"
                       "Exit code is 1 when any file is in conflict, "
                       "otherwise 0.",
                formatter_class=argparse.RawDescriptionHelpFormatter)
        else:
            p = sub.add_parser(
                name,
                help="write a bundle folder for a project's sensitive surface",
                description="Export a bundle folder containing the surface "
                            "files in full, direct graph context at "
                            "signatures, manifest.json, exposure.json, "
                            "EXPOSURE.md, and PROMPT.md. The output folder "
                            "must be new or empty. Secret-shaped literals "
                            "are redacted in the exported copies by default. "
                            "The source project is never altered.",
                epilog="Example:\n"
                       "  ghostexposure export ./my-project --surface pack.json -o ./my-bundle\n"
                       "\n"
                       "Export stops (exit code 2) on unresolved conflicts "
                       "unless --exclude-conflicts is given.",
                formatter_class=argparse.RawDescriptionHelpFormatter)
        p.add_argument("project",
                       help="path to the project directory to scan or export")
        p.add_argument("--surface", default=None,
                       help="path to a surface pack JSON "
                            "(default: the built-in starter pack)")
        if name == "scan":
            p.add_argument("--json", action="store_true",
                           help="print a single JSON document instead of "
                                "the human-readable report")
            p.set_defaults(fn=cmd_scan)
        else:
            p.add_argument("-o", "--output", required=True,
                           help="bundle folder to write; must be new or empty")
            p.add_argument("--allow-unredacted", action="store_true",
                           help="export secret-shaped literals as-is; this "
                                "choice is recorded in exposure.json")
            p.add_argument("--exclude-conflicts", action="store_true",
                           help="leave conflicted files out, with the decision "
                                "recorded in exposure.json")
            p.set_defaults(fn=cmd_export)
    p = sub.add_parser(
        "verify",
        help="check a received bundle against its manifest and partition",
        description="Verify a bundle folder: re-check every exported file "
                    "hash, confirm the files on disk are exactly the files "
                    "recorded as in the bundle, and confirm every file in "
                    "the recorded inventory appears exactly once in the "
                    "partition. Each discrepancy is named. Verification "
                    "proves the bundle matches its manifest; it cannot "
                    "prove a sender did not share other files by another "
                    "channel.",
        epilog="Example:\n"
               "  ghostexposure verify ./my-bundle\n"
               "  ghostexposure verify ./my-bundle --json\n"
               "\n"
               "Exit code is 0 when the bundle matches, otherwise 1.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("bundle",
                   help="path to the bundle folder to verify")
    p.add_argument("--json", action="store_true",
                   help="print a single JSON document instead of the "
                        "human-readable report")
    p.set_defaults(fn=cmd_verify)
    p = sub.add_parser(
        "packs",
        help="show a surface pack's summary and patterns",
        description="Print a surface pack's id, version, date, description, "
                    "and pattern count as JSON, followed by one line per "
                    "pattern (id, kind, pattern, reason). Use this to read "
                    "the exact definition a scan or export would apply.",
        epilog="Example:\n"
               "  ghostexposure packs\n"
               "  ghostexposure packs --surface examples/starter-surface.example.json",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--surface", default=None,
                   help="path to a surface pack JSON "
                        "(default: the built-in starter pack)")
    p.set_defaults(fn=cmd_packs)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (SurfaceError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
