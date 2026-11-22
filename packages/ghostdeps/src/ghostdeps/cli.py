"""GhostDeps CLI: pack / doctor.

Evidence only: no command here installs, removes, edits a manifest, or
touches the network. Exit codes: 0 = pack built, no imported-not-declared
findings; 1 = findings present (imported with no declaration found);
2 = could not build (project missing, or no manifest parsed).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .imports_scan import scan_imports
from .manifests import discover_sources
from .xref import build_pack, render_deps_md


def _analyse(project: Path):
    """Discover manifests, scan imports, and build the pack dict.

    Returns ``(sources, parsed, pack)`` where ``parsed`` is the subset
    of sources whose status is ``"parsed"``; callers use it to decide
    the exit code when nothing could be parsed at all.
    """
    sources = discover_sources(project)
    parsed = [s for s in sources if s.status == "parsed"]
    idx = scan_imports(project)
    pack = build_pack(str(project), sources, idx)
    return sources, parsed, pack


def cmd_pack(args) -> int:
    """Run ``ghostdeps pack``: write DEPS.md + deps-manifest.json.

    Returns 0 when there are no imported-not-declared findings, 1 when
    such findings are present, and 2 when the project is missing or no
    manifest or lockfile could be parsed.
    """
    project = Path(args.project)
    if not project.is_dir():
        print(f"ghostdeps: project not found: {project}", file=sys.stderr)
        return 2
    sources, parsed, pack = _analyse(project)
    if not parsed:
        print("ghostdeps: no manifest or lockfile could be parsed in "
              f"{project}; nothing to pack", file=sys.stderr)
        for s in sources:
            print(f"  {s.rel}: {s.status} ({s.note})", file=sys.stderr)
        return 2
    out = Path(args.output) if args.output else project / "deps-pack"
    try:
        out.mkdir(parents=True, exist_ok=True)
        md = render_deps_md(pack)
        (out / "DEPS.md").write_text(md, encoding="utf-8")
        (out / "deps-manifest.json").write_text(
            json.dumps(pack, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    except (OSError, ValueError) as exc:
        # An unwritable output path (or a rendering guard tripping)
        # is a reported failure with the pack's exit-2 contract, not
        # a traceback.
        print(f"ghostdeps: could not write pack to {out}: {exc}",
              file=sys.stderr)
        return 2
    c = pack["counts"]
    print(f"GhostDeps pack: {project}")
    print(f"  declared {c['declared']} | declared and imported "
          f"{c['declared_and_used']} | declared, no import found "
          f"{c['declared_not_imported']} | imported, no declaration found "
          f"{c['imported_not_declared']} | pins recorded {c['pins_recorded']}")
    print(f"  wrote {out / 'DEPS.md'}")
    print(f"  wrote {out / 'deps-manifest.json'}")
    if args.json:
        print(json.dumps(pack, indent=2, sort_keys=True))
    return 1 if c["imported_not_declared"] else 0


def cmd_doctor(args) -> int:
    """Run ``ghostdeps doctor``: report sources found, without writing a pack.

    Prints which manifests and lockfiles were found, which were parsed
    versus detected only, the import-extraction method per ecosystem,
    and the summary counts. Uses the same exit codes as ``pack``.
    """
    project = Path(args.project)
    if not project.is_dir():
        print(f"ghostdeps: project not found: {project}", file=sys.stderr)
        return 2
    sources, parsed, pack = _analyse(project)
    if args.json:
        print(json.dumps({
            "project": str(project),
            "sources": pack["sources"],
            "source_groups": pack.get("source_groups", []),
            "files_scanned": pack["files_scanned"],
            "import_scan": pack.get("import_scan", {}),
            "parser_confidence": pack["parser_confidence"],
            "counts": pack["counts"],
        }, indent=2, sort_keys=True))
    else:
        print(f"GhostDeps doctor: {project}")
        for s in pack["sources"]:
            note = f" - {s['note']}" if s["note"] else ""
            print(f"  {s['file']} ({s['kind']}, {s['ecosystem']}): "
                  f"{s['status']}{note}")
        if not pack["sources"]:
            print("  no manifests or lockfiles found")
        fs = pack["files_scanned"]
        print(f"  files scanned: python {fs['python']}, "
              f"javascript {fs['javascript']}, rust {fs['rust']}")
        import_scan = pack.get("import_scan", {})
        if import_scan.get("ignored_file_count"):
            print(f"  import files ignored by local ignore rules: "
                  f"{import_scan['ignored_file_count']}")
        for warning in import_scan.get("warnings", []):
            print(f"  ignore warning: {warning}")
        for eco, label in pack["parser_confidence"].items():
            print(f"  {eco} import extraction: {label}")
        if pack["python_parse_failures"]:
            print(f"  python files that failed to parse: "
                  f"{len(pack['python_parse_failures'])} "
                  f"({', '.join(pack['python_parse_failures'][:5])})")
        c = pack["counts"]
        print(f"  declared {c['declared']}, imported-not-declared "
              f"{c['imported_not_declared']} (finding), "
              f"declared-not-imported {c['declared_not_imported']} (information)")
    if not parsed:
        return 2
    return 1 if pack["counts"]["imported_not_declared"] else 0


def main(argv=None) -> int:
    """Parse command-line arguments and dispatch to ``pack`` or ``doctor``.

    Exit codes (both subcommands): 0 = pack built, no findings;
    1 = findings present (an import with no declaration found);
    2 = could not build a pack (project missing, or no manifest
    or lockfile could be parsed).
    """
    parser = argparse.ArgumentParser(
        prog="ghostdeps",
        description="Dependency context pack from local manifests, "
                    "lockfiles, and imports. Local evidence only, "
                    "no network, no verdicts.",
        epilog="Examples:\n"
               "  ghostdeps pack path/to/project\n"
               "  ghostdeps pack path/to/project -o out --json\n"
               "  ghostdeps doctor path/to/project\n"
               "\n"
               "Exit codes: 0 = no findings, 1 = imported with no\n"
               "declaration found, 2 = could not build a pack.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version",
                        version=f"ghostdeps {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pack = sub.add_parser(
        "pack", help="build DEPS.md + deps-manifest.json for a project",
        description="Build a dependency pack for PROJECT: write "
                    "DEPS.md (human report) and deps-manifest.json "
                    "(same facts, machine-readable) to the output "
                    "directory. Read-only: nothing in PROJECT is changed.",
        epilog="Example: ghostdeps pack path/to/project -o out",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p_pack.add_argument("project",
                        help="path to the project directory to scan")
    p_pack.add_argument("-o", "--output",
                        help="output directory (default: <project>/deps-pack)")
    p_pack.add_argument("--json", action="store_true",
                        help="also print the manifest JSON to stdout")
    p_pack.set_defaults(func=cmd_pack)

    p_doc = sub.add_parser(
        "doctor", help="report what was found and parsed, without writing a pack",
        description="Report what GhostDeps finds in PROJECT: which "
                    "manifests and lockfiles were found, which were "
                    "parsed versus detected only, how imports were "
                    "extracted per ecosystem, and the summary counts. "
                    "Writes no files.",
        epilog="Example: ghostdeps doctor path/to/project --json",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p_doc.add_argument("project",
                       help="path to the project directory to inspect")
    p_doc.add_argument("--json", action="store_true",
                       help="print the report as JSON instead of text")
    p_doc.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
