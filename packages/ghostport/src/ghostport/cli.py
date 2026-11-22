"""GhostPort CLI: scan / plan / bundle / claim / verify / status / packs.

Planner only: no command here rewrites project code. `claim` records a
ported-claimed claim. `verify` records verified ONLY from a GhostVerify
post report file. There is no flag to set verified by hand.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .bundle import build_unit_bundle
from .ledger import record_state, record_verified
from .patterns import PackError, load_pack
from .planning import build_plan, write_plan
from .profile import ProfileError
from .scanner import scan_project
from .status import build_status


def _pack(args, project):
    """Load the pattern pack named by ``args.pack`` for ``project``."""
    return load_pack(args.pack, Path(project))


def cmd_scan(args):
    """Run ``ghostport scan``: list pattern hits; write nothing."""
    pack = _pack(args, args.project)
    result = scan_project(Path(args.project), pack)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    p = result["pack"]
    print(f"GhostPort scan: pack {p['id']} v{p['version']} ({p['date']})")
    print(result["note"])
    for hit in result["hits"]:
        print(f"{hit['file']}:{hit['line']} [{hit['pattern_id']}] {hit['description']}")
    print(f"\n{len(result['hits'])} hit(s) in {len(result['files_with_hits'])} file(s); "
          f"{len(result['files_scanned'])} Python file(s) scanned, "
          f"{len(result['files_without_hits'])} with zero hits for this pack.")
    for lang, files in result["not_covered_languages"].items():
        print(f"NOT COVERED by this pack: {lang} ({len(files)} file(s))")
    for err in result["parse_errors"]:
        print(f"parse error: {err['file']}: {err['error']}")
    return 0


def cmd_plan(args):
    """Run ``ghostport plan``: write PORT_PLAN.md + port-plan.json."""
    pack = _pack(args, args.project)
    plan, json_path, md_path = write_plan(Path(args.project), pack, args.out)
    # record planned for every unit
    from .ledger import append_record
    for unit in plan["units"]:
        try:
            record_state(Path(args.project), unit["id"], "planned",
                         pack=pack.id, pack_version=pack.version)
        except Exception as exc:
            # Was a bare silent pass: the plan claimed success while the
            # ledger (and therefore `status`) silently missed the unit.
            print(f"warning: could not record 'planned' for {unit['id']} "
                  f"in the ledger: {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        print(f"Plan written: {md_path} + {json_path}")
        for u in plan["units"]:
            print(f"  {u['order']}. {u['id']}: {u['hit_count']} hit(s), est {u['estimated_tokens']} tokens")
        for b in plan["blockers"]:
            print(f"  BLOCKER cycle combined into {b['unit']}: {', '.join(b['files'])}")
    return 0


def cmd_bundle(args):
    """Run ``ghostport bundle``: export one unit as a bundle folder."""
    pack = _pack(args, args.project)
    plan = build_plan(Path(args.project), pack)
    out = Path(args.out) if args.out else Path(args.project) / ".ghostport" / "bundles" / args.unit
    manifest = build_unit_bundle(Path(args.project), plan, args.unit, out)
    record_state(Path(args.project), args.unit, "bundled",
                 manifest_sha256=manifest["bundle_manifest_sha256"])
    print(f"Bundle written: {out} (manifest sha256 {manifest['bundle_manifest_sha256'][:16]}...)")
    print(f"Files: {len(manifest['files'])}, sliced est tokens: {manifest['total_sliced_tokens']}")
    return 0


def cmd_claim(args):
    """Run ``ghostport claim``: record a ported-claimed claim (not proof)."""
    record_state(Path(args.project), args.unit, "ported-claimed", by=args.by or "unspecified")
    print(f"Recorded CLAIM (not proof): unit {args.unit} ported-claimed")
    return 0


def cmd_verify(args):
    """Run ``ghostport verify``: record verified from a Verify report."""
    rec = record_verified(Path(args.project), args.unit, Path(args.report))
    print(f"Recorded VERIFIED for {args.unit} from GhostVerify report {args.report} "
          f"(report sha256 {rec['verify_report_sha256'][:16]}...)")
    return 0


def cmd_status(args):
    """Run ``ghostport status``: show plan + ledger progress."""
    status = build_status(Path(args.project))
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0
    print(f"GhostPort status: {status['project']}")
    for row in status["units"]:
        print(f"  {row['order']}. {row['unit']}: {row['state']} (est {row['estimated_tokens']} tokens)")
    print(f"Verified units: {status['verified_units']}  Estimated tokens remaining: {status['estimated_tokens_remaining']}")
    print(f"Next unit: {status['next_unit']}")
    print(status["note"])
    return 0


def cmd_packs(args):
    """Run ``ghostport packs``: show pack search paths and pack contents."""
    from .patterns import pack_search_paths
    for p in pack_search_paths(args.pack or "python-upgrade"):
        print(f"{'[found]' if p.is_file() else '[missing]'} {p}")
    if args.pack:
        pack = load_pack(args.pack)
        print(f"{pack.id} v{pack.version} ({pack.date}): {pack.title}")
        for pat in pack.patterns:
            print(f"  {pat.id}: {pat.description} [ref: {pat.reference}, {pat.reference_date}]")
    return 0


def main(argv=None) -> int:
    """Parse arguments and dispatch to a subcommand.

    Returns 0 on success and 2 when no subcommand is given or a pack,
    profile, or value error is reported. ``argv`` defaults to
    ``sys.argv[1:]`` (the usual argparse behaviour when it is None).
    """
    parser = argparse.ArgumentParser(
        prog="ghostport",
        description="GhostPort: migration slicer and workbench. "
                    "Scans a project for migration patterns, orders the "
                    "work leaves-first, and exports one bundle per unit. "
                    "Planner only: it never rewrites code, runs no "
                    "codemods, and runs no tests.",
        epilog="Examples:\n"
               "  ghostport scan ~/my-project\n"
               "  ghostport plan ~/my-project --pack python-upgrade\n"
               "  ghostport bundle ~/my-project --unit unit-legacy-storage -o /tmp/port-unit-001\n"
               "  ghostport status ~/my-project\n"
               "  ghostport packs --pack python-upgrade\n\n"
               "Run 'ghostport <command> --help' for command-specific options.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"ghostport {__version__}",
                        help="show the GhostPort version and exit")
    sub = parser.add_subparsers(dest="cmd", title="commands")
    for name, fn, help_text, desc in (
        ("scan", cmd_scan,
         "list pattern hits in a project (writes nothing)",
         "Scan a project for pattern-pack hits. Prints each hit as "
         "file:line [pattern-id] description, the files scanned with "
         "zero hits, and any languages this pack does not cover. "
         "A scan with no hits means 'no hits for this pack', not "
         "'ready to upgrade'."),
        ("plan", cmd_plan,
         "write PORT_PLAN.md and port-plan.json in dependency order",
         "Build the full plan: scan, form units, order them leaves-first "
         "over the dependency graph (cycles are combined into one unit "
         "and named as blockers), and write PORT_PLAN.md plus "
         "port-plan.json. Also records a 'planned' ledger entry per unit."),
    ):
        sp = sub.add_parser(name, help=help_text, description=desc); sp.set_defaults(fn=fn)
        sp.add_argument("project", help="path to the project directory to scan")
        sp.add_argument("--pack", default="python-upgrade",
                        help="pattern pack id to use (default: %(default)s)")
        sp.add_argument("--json", action="store_true",
                        help="print the full result as JSON instead of text")
        if name == "plan":
            sp.add_argument("-o", "--out",
                            help="directory to write PORT_PLAN.md and port-plan.json "
                                 "into (default: the project directory)")
    sp = sub.add_parser("bundle", help="export one unit as a GhostSlice-style bundle",
                        description="Export one planned unit as a bundle folder: the "
                                    "unit and its covering tests in full, related "
                                    "dependency and caller units as signatures, plus "
                                    "manifest.json, PROMPT.md, and a UNIT.md checklist. "
                                    "The source project is not modified.")
    sp.set_defaults(fn=cmd_bundle)
    sp.add_argument("project", help="path to the project directory")
    sp.add_argument("--unit", required=True,
                    help="unit id to export, as shown by 'ghostport plan' (for example unit-legacy-storage)")
    sp.add_argument("--pack", default="python-upgrade",
                    help="pattern pack id to use (default: %(default)s)")
    sp.add_argument("-o", "--out",
                    help="bundle output directory (default: <project>/.ghostport/bundles/<unit>)")
    sp = sub.add_parser("claim", help="record that a unit is ported (a claim, not proof)",
                        description="Record a 'ported-claimed' claim for a unit in the "
                                    "project ledger (.ghostport-history.jsonl). A claim is "
                                    "a statement by a person or agent, not verification.")
    sp.set_defaults(fn=cmd_claim)
    sp.add_argument("project", help="path to the project directory")
    sp.add_argument("--unit", required=True, help="unit id being claimed")
    sp.add_argument("--by", help="who is making the claim (default: unspecified)")
    sp = sub.add_parser("verify", help="record a unit as verified from a GhostVerify report",
                        description="Record a unit as 'verified' in the ledger. This is the "
                                    "only way to record verified: it requires a GhostVerify "
                                    "post report file, which is validated and hashed. There "
                                    "is no flag to set verified by hand.")
    sp.set_defaults(fn=cmd_verify)
    sp.add_argument("project", help="path to the project directory")
    sp.add_argument("--unit", required=True, help="unit id being verified")
    sp.add_argument("--report", required=True,
                    help="path to the GhostVerify post report (JSON) for this unit")
    sp = sub.add_parser("status", help="show migration progress and the next unit",
                        description="Show the resumption view for a project: each planned "
                                    "unit with its ledger state, the number of verified "
                                    "units, estimated tokens remaining, and the next unit "
                                    "in plan order. Reads port-plan.json and the ledger; "
                                    "writes nothing.")
    sp.set_defaults(fn=cmd_status)
    sp.add_argument("project", help="path to the project directory")
    sp.add_argument("--json", action="store_true",
                    help="print the full status as JSON instead of text")
    sp = sub.add_parser("packs", help="list pattern packs and where they are loaded from",
                        description="Show where a pattern pack is searched for and, when "
                                    "--pack is given, list its patterns with their dated "
                                    "source references.")
    sp.set_defaults(fn=cmd_packs)
    sp.add_argument("--pack", help="pack id to inspect (omit to show the default pack's search paths only)")
    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        parser.print_help()
        return 2
    try:
        return args.fn(args)
    except (PackError, ProfileError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
