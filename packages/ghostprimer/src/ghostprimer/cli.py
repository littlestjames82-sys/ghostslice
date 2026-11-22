"""GhostPrimer command line: build | check | stale | doctor | mcp.

Quick start
-----------
    ghostprimer doctor <project>          # read-only: what would be found?
    ghostprimer build <project> -o <bundle>
    ghostprimer check <bundle>            # exit 0 pass, 1 fail, 2 cannot check
    ghostprimer stale <bundle>            # exit 0 fresh, 1 stale, 2 cannot check

``build`` writes a starter pack (``PRIMER.md`` + ``manifest.json`` +
``files/``) sized to be read whole. It never modifies the project,
never calls a model, and only reads project-local sources, plus a
GhostRecall bundle or GhostHandoff pack you pass explicitly.
Run ``ghostprimer <command> --help`` for the options of one command.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .bundle import DEFAULT_BUDGET, build_bundle, check_bundle
from .doctor import doctor
from .stale import staleness_report

_EPILOG = """\
examples:
  ghostprimer doctor path/to/project
  ghostprimer build path/to/project -o /tmp/my-primer
  ghostprimer build path/to/project -o /tmp/my-primer --budget 3000
  ghostprimer build path/to/project -o /tmp/my-primer \\
      --recall-bundle path/to/recall-bundle --task "first session"
  ghostprimer check /tmp/my-primer
  ghostprimer stale /tmp/my-primer

The bundle is a plain folder: read PRIMER.md first, use manifest.json
to audit every file, memory item, and omission. Without an installed
entry point, run the same commands as: python -m ghostprimer ...
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ghostprimer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="First-session starter pack for a project: a small "
                    "bundle a new agent session (or a new hire driving "
                    "one) can read whole before there is a task. "
                    "Extractive facts only, project-local sources only, "
                    "with an explicit list of what was left out.",
        epilog=_EPILOG)
    parser.add_argument("--version", action="version",
                        version=f"ghostprimer {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser(
        "build",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="build a starter bundle (PRIMER.md + manifest.json + files/)",
        description="Build a starter bundle for PROJECT. Writes "
                    "PRIMER.md (the pack to read), manifest.json (the "
                    "audit record), and files/ (the sliced code) into "
                    "the folder given with -o. The project itself is "
                    "never modified.",
        epilog="example:\n"
               "  ghostprimer build path/to/project -o /tmp/my-primer "
               "--budget 6000\n")
    p_build.add_argument("project",
                         help="path to the project root to prime from; "
                              "a root that is itself a private memory "
                              "location is refused")
    p_build.add_argument("-o", "--out", required=True,
                         help="output bundle folder to create/write "
                              "(required)")
    p_build.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                         help="total estimated-token budget for the pack "
                              f"(default: {DEFAULT_BUDGET}); memory is "
                              "capped at 40%% of it, the rest is for code; "
                              "if the budget cannot be met, entry points "
                              "are kept at outline depth and the shortfall "
                              "is reported, never hidden")
    p_build.add_argument("--recall-bundle", default=None,
                         metavar="DIR",
                         help="use a GhostRecall bundle directory as the "
                              "memory source (its current items only, "
                              "verbatim) instead of the shallow fallback "
                              "pass over well-known project files")
    p_build.add_argument("--handoff-pack", default=None,
                         metavar="DIR_OR_JSON",
                         help="also carry a previous session forward: a "
                              "GhostHandoff pack directory or its "
                              "handoff.json file; its recorded state, "
                              "open loops, and next steps share the same "
                              "memory budget; a pack for a different "
                              "project is refused")
    p_build.add_argument("--task", default="",
                         help="optional free-text label for this pack, "
                              "recorded verbatim in the manifest "
                              "(default: empty); it does not change "
                              "selection, which is task-free by design")
    p_build.add_argument("--json", action="store_true",
                         help="print a one-object JSON summary instead "
                              "of the human-readable summary lines")

    p_check = sub.add_parser(
        "check",
        help="verify a starter bundle against its manifest",
        description="Verify a bundle built by 'build': recompute file "
                    "hashes and token totals, verify PRIMER.md against "
                    "its recorded hash, confirm every recorded memory "
                    "item's source path resolves inside the project "
                    "root, and confirm no memory item came from a "
                    "private memory location. Prints a JSON report.")
    p_check.add_argument("bundle",
                         help="path to the bundle folder to verify")

    p_stale = sub.add_parser(
        "stale",
        help="report whether a bundle still matches its project",
        description="Report whether a bundle still matches its "
                    "project: the bundle must pass 'check' first, "
                    "then every recorded source is re-read (its path "
                    "re-verified inside the project root before it "
                    "is opened) and re-sliced at the recorded mode "
                    "for comparison against the recorded hash. "
                    "Reports changed, missing, and refused sources, "
                    "facts drift, new entry points, and missing "
                    "memory sources. Prints a JSON report. Exit 0 "
                    "fresh, 1 stale, 2 could not check.")
    p_stale.add_argument("bundle",
                         help="path to the bundle folder to check "
                              "for staleness")
    p_stale.add_argument("--project", default=None,
                         metavar="DIR",
                         help="compare against this project tree "
                              "instead of the root recorded in the "
                              "manifest (for projects that moved)")

    p_doctor = sub.add_parser(
        "doctor",
        help="report what a build would find on a project (read-only)",
        description="Read-only preview for a project: extracted facts, "
                    "entry points found, which memory sources exist or "
                    "are missing, whether a Recall bundle was found, "
                    "and which token estimator is in use. Run this "
                    "first on an unfamiliar project. Prints a JSON "
                    "report; exit 0 if the project can be primed, "
                    "2 otherwise.")
    p_doctor.add_argument("project",
                          help="path to the project root to inspect")

    sub.add_parser(
        "mcp",
        help="run the stdio MCP server (primer_build, primer_check, primer_stale)",
        description="Run the local stdio MCP server (newline-delimited "
                    "JSON-RPC). Tools: primer_build, primer_check, "
                    "and primer_stale. "
                    "Replies are capped summaries with no raw file "
                    "bodies by default. Local only; no network listener "
                    "is opened.")

    args = parser.parse_args(argv)

    if args.command == "build":
        try:
            manifest = build_bundle(args.project, args.out,
                                    budget=args.budget,
                                    recall_bundle=args.recall_bundle,
                                    task=args.task,
                                    handoff_pack=args.handoff_pack)
        except (ValueError, OSError) as exc:
            print(f"ghostprimer: {exc}", file=sys.stderr)
            return 2
        if args.json:
            summary = {k: manifest[k] for k in (
                "root", "budget_tokens", "budget_unmet", "memory_path",
                "total_original_tokens", "total_sliced_tokens",
                "memory_tokens_estimate")}
            if "handoff_input" in manifest:
                summary["handoff_input"] = manifest["handoff_input"]
            print(json.dumps(summary, indent=2))
        else:
            print(f"GhostPrimer bundle: {args.out}")
            print(f"  files: {len(manifest['files'])} "
                  f"({manifest['total_sliced_tokens']} sliced tokens, "
                  f"was {manifest['total_original_tokens']})")
            print(f"  memory: {len(manifest['memory_items'])} items "
                  f"via {manifest['memory_path']} "
                  f"({manifest['memory_tokens_estimate']} tokens)")
            if "handoff_input" in manifest:
                handoff = manifest["handoff_input"]
                print(f"  handoff: {handoff['items_included']} items "
                      f"from {handoff['json_path']} "
                      f"({handoff['estimated_tokens']} tokens)")
            print(f"  not included: {len(manifest['not_included'])}, "
                  f"blocked: {len(manifest['memory_blocked'])}")
            if manifest["budget_unmet"]:
                print(f"  WARNING: budget {args.budget} unmet; entry "
                      "points kept at outline (see PRIMER.md limits)")
        return 0
    if args.command == "check":
        code, report = check_bundle(args.bundle)
        print(json.dumps(report, indent=2))
        return code
    if args.command == "stale":
        code, report = staleness_report(args.bundle, project=args.project)
        print(json.dumps(report, indent=2))
        return code
    if args.command == "doctor":
        report = doctor(args.project)
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2
    if args.command == "mcp":
        from .mcp_server import serve
        return serve()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
