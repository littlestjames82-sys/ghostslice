"""GhostShard command-line interface.

Commands
--------
``plan``
    Read a project and a task, then write a plan folder: per-shard
    bundles, ``shards.json``, ``PLAN.md``, and ``bus-manifest.json``.
``check``
    Validate a plan folder written by ``plan``.
``export-bus``
    Re-write the GhostBus-shaped manifest for an existing plan folder.

Planner only: no command runs an agent, contacts a relay, dispatches
a job, approves an action, or merges results. Every job written to
``bus-manifest.json`` carries ``"dispatch": false``. See ``README.md``
for the full output layout and ``PLAN.md`` for the design boundary.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

from .planner import plan_project
from .taskfile import parse_task_file
from .bundles import write_plan, check_plan, write_bus_manifest
from . import __version__

def _positive_int(value, what):
    """Coerce a profile / CLI limit to a positive int, or exit with a
    clean message. Never raises ValueError/TypeError tracebacks, and
    never silently coerces bools or non-numeric values."""
    if isinstance(value, bool):
        raise SystemExit(f"invalid {what}: must be a positive integer, got {value!r}")
    if isinstance(value, int):
        n = value
    elif isinstance(value, float) and value.is_integer():
        n = int(value)
    elif isinstance(value, str):
        try:
            n = int(value.strip())
        except ValueError:
            raise SystemExit(f"invalid {what}: must be a positive integer, got {value!r}")
    else:
        raise SystemExit(f"invalid {what}: must be a positive integer, got {value!r}")
    if n <= 0:
        raise SystemExit(f"invalid {what}: must be a positive integer, got {value!r}")
    return n

def _load_profile(project, args):
    """Merge planning limits from defaults, profile, and CLI flags.

    Precedence, lowest to highest:

    1. Built-in defaults: budget 60000, max shards 12, fan-out 8.
    2. ``<project>/.ghostshard.json``: either a ``"shard"`` section or
       flat top-level keys (``budget_tokens``, ``max_shards``,
       ``max_shared_fanout``).
    3. CLI flags (``--budget``, ``--max-shards``,
       ``--max-shared-fanout``), when given.

    Returns a dict with keys ``budget_tokens``, ``max_shards``, and
    ``max_shared_fanout``. Exits with an error message if the profile
    file exists but is not valid JSON.
    """
    cfg = {"budget_tokens": 60000, "max_shards": 12, "max_shared_fanout": 8}
    cand = Path(project) / ".ghostshard.json"
    if cand.is_file():
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            raise SystemExit(f"invalid profile {cand}: {e}")
        if not isinstance(data, dict):
            raise SystemExit(f"invalid profile {cand}: top level must be a JSON object")
        sect = data.get("shard", data)
        if not isinstance(sect, dict):
            raise SystemExit(f"invalid profile {cand}: 'shard' must be a JSON object")
        for k in cfg:
            if k in sect:
                cfg[k] = _positive_int(sect[k], f"profile {cand}: {k}")
    # CLI overrides: test for None, not truthiness, so an explicit
    # --budget 0 is rejected instead of silently ignored.
    if getattr(args, "budget", None) is not None:
        cfg["budget_tokens"] = _positive_int(args.budget, "--budget")
    if getattr(args, "max_shards", None) is not None:
        cfg["max_shards"] = _positive_int(args.max_shards, "--max-shards")
    if getattr(args, "max_shared_fanout", None) is not None:
        cfg["max_shared_fanout"] = _positive_int(args.max_shared_fanout, "--max-shared-fanout")
    return cfg

def main(argv=None) -> int:
    """Run the GhostShard CLI and return a process exit code.

    Exit codes: ``0`` success (for ``plan``, a complete plan), ``1``
    a partial plan or a failed ``check``, ``2`` a usage error such as
    a missing project directory or an unreadable task file.
    ``argv`` defaults to ``sys.argv[1:]`` via argparse.
    """
    ap = argparse.ArgumentParser(
        prog="ghostshard",
        description="Planner-only task sharder for GhostSlice: plan how a "
                    "large task splits across shards. Files out, no dispatch, "
                    "no execution.",
        epilog="Examples:\n"
               "  ghostshard plan ~/my-project --task \"Add a report\" -o /tmp/shards-out\n"
               "  ghostshard plan ~/my-project --task-file tasks.md -o /tmp/shards-out\n"
               "  ghostshard check /tmp/shards-out\n"
               "  ghostshard export-bus /tmp/shards-out\n\n"
               "Every bus-manifest job carries \"dispatch\": false. GhostShard "
               "never sends the manifest; handing it to GhostBus is a separate step.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"ghostshard {__version__}",
                    help="show the GhostShard version and exit")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="<command>")
    p = sub.add_parser(
        "plan",
        help="plan shards and write bundles + shards.json + PLAN.md",
        description="Plan shards for PROJECT and write the plan folder. "
                    "Use exactly one of --task (auto-clustered) or "
                    "--task-file (user-split). See README.md for the two modes.",
        epilog="Exit codes: 0 = complete plan, 1 = partial plan (a cap was "
               "hit or a shard is unfittable), 2 = usage error.")
    p.add_argument("project", help="path to the project directory to scan")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--task", metavar="TEXT",
                   help="one freeform task string; GhostShard clusters the "
                        "import/call graph to split it (auto-clustered mode)")
    g.add_argument("--task-file", metavar="FILE",
                     help="task file with one '## Heading' per subtask; you "
                          "supply the split (user-split mode)")
    p.add_argument("-o", "--out", default="shards", metavar="DIR",
                   help="output plan folder (default: %(default)s)")
    p.add_argument("--budget", type=int, metavar="TOKENS",
                   help="per-shard estimated-token budget; overrides the profile "
                        "(default: 60000, or the profile value)")
    p.add_argument("--max-shards", type=int, metavar="N",
                   help="maximum number of shards before the plan is marked "
                        "partial; overrides the profile (default: 12)")
    p.add_argument("--max-shared-fanout", type=int, metavar="N",
                   help="maximum shards that may share one file read-only before "
                        "the plan is marked partial; overrides the profile "
                        "(default: 8)")
    p.add_argument("--json", action="store_true",
                   help="print a JSON summary (shards, partial, totals, "
                        "max_parallelism) instead of the text summary")
    c = sub.add_parser(
        "check",
        help="validate a shards folder (bundles, ownership, acyclic)",
        description="Validate a plan folder: bundle manifests against their "
                    "files (sha256 and token totals), unique shard ids, unique "
                    "file ownership, existing depends_on targets, and an "
                    "acyclic dependency graph.",
        epilog="Exit codes: 0 = valid, 1 = invalid (every failure is printed).")
    c.add_argument("folder", help="path to the plan folder containing shards.json")
    c.add_argument("--json", action="store_true",
                   help="print the check result as JSON instead of text")
    e = sub.add_parser(
        "export-bus",
        help="write the GhostBus-shaped manifest FILE (sends nothing)",
        description="Re-write bus-manifest.json for an existing plan folder. "
                    "Writes a file only: nothing is sent and no relay is "
                    "contacted. Every job carries \"dispatch\": false.",
        epilog="Exit codes: 0 = manifest written, 2 = shards.json not found.")
    e.add_argument("folder", help="path to the plan folder containing shards.json")
    e.add_argument("-o", "--out", metavar="FILE",
                   help="write the manifest to FILE instead of "
                        "<folder>/bus-manifest.json")
    args = ap.parse_args(argv)

    if args.cmd == "plan":
        if not Path(args.project).is_dir():
            print(f"error: project not a directory: {args.project}", file=sys.stderr); return 2
        cfg = _load_profile(args.project, args)
        subtasks = None
        if args.task_file:
            try:
                subtasks = parse_task_file(Path(args.task_file).read_text(encoding="utf-8"))
            except (OSError, ValueError) as ex:
                print(f"error: {ex}", file=sys.stderr); return 2
        plan = plan_project(args.project, task=args.task, subtasks=subtasks, **cfg)
        summary, code = write_plan(plan, args.project, args.out)
        if args.json:
            print(json.dumps({"shards": summary["shards"], "partial": summary["partial"],
                              "totals": summary["totals"], "max_parallelism": summary["max_parallelism"],
                              "analytics": summary.get("analytics")}, indent=2))
        else:
            print(f"mode: {summary['mode']} (partial: {summary['partial']})")
            for s in summary["shards"]:
                print(f"  {s['id']}: owns {len(s['owns_files'])} file(s), est {s['estimated_tokens']} tokens, "
                      f"depends_on {s['depends_on'] or '-'}, group {s['parallel_group']}")
            print(f"max useful parallelism: {summary['max_parallelism']}")
            a = summary.get("analytics") or {}
            if a.get("critical_path"):
                print(f"critical path: {' -> '.join(a['critical_path'])} "
                      f"({a['critical_path_tokens']} est. tokens, speedup {a['parallel_speedup']}x)")
            print(f"wrote {args.out}/shards.json, PLAN.md, bus-manifest.json + per-shard bundles")
            if summary["partial"]:
                print("plan is PARTIAL (cap or unfittable shard) - see conflicts in shards.json", file=sys.stderr)
        return code
    if args.cmd == "check":
        res = check_plan(args.folder)
        if args.json:
            print(json.dumps(res, indent=2))
        elif res["ok"]:
            print(f"check OK: {res['shards_checked']} shard bundle(s), ownership unique, acyclic")
        else:
            for e_ in res["errors"]: print(f"check FAIL: {e_}")
        return 0 if res["ok"] else 1
    if args.cmd == "export-bus":
        sj = Path(args.folder) / "shards.json"
        if not sj.is_file():
            print(f"error: shards.json not found in {args.folder}", file=sys.stderr); return 2
        try:
            plan_out = json.loads(sj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as ex:
            print(f"error: shards.json is not valid JSON: {ex}", file=sys.stderr); return 2
        if (not isinstance(plan_out, dict)
                or not isinstance(plan_out.get("shards"), list)
                or any(not isinstance(s, dict)
                       or not all(k in s for k in ("id", "bundle", "task", "depends_on"))
                       for s in plan_out["shards"])):
            print("error: shards.json has no valid shards list", file=sys.stderr); return 2
        dest = Path(args.out) if args.out else Path(args.folder) / "bus-manifest.json"
        try:
            written = write_bus_manifest(Path(args.folder), plan_out)
            if args.out:
                import shutil
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.resolve() != written.resolve():
                    shutil.copyfile(written, dest)
        except OSError as ex:
            print(f"error: could not write bus manifest: {ex}", file=sys.stderr); return 2
        print(f"wrote bus manifest file only (nothing sent): {dest}")
        return 0
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
