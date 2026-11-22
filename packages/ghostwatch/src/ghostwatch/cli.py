"""GhostWatch CLI: snapshot, check, watch. Stdlib only, local only.

Commands:
  snapshot  Record source hashes + symbol outlines at bundle time.
            Run this when (or right after) a bundle is exported.
  check     Compare the live project with the snapshot once and
            print a verdict: fresh, stale, or unknown.
  watch     Poll `check` on an interval and print each settled
            verdict change. A convenience loop, not a daemon.

Exit codes (check, and watch's session summary):
  0 = fresh, 1 = stale, 2 = unknown / could not determine.

Hard rule: GhostWatch reports freshness; it never silently refreshes
a bundle. Re-export delegation: only with an explicit --reexport on
a stale verdict does GhostWatch call the GhostSlice CLI as a
subprocess if available (ghostslice on PATH, else
python -m ghostslice). If unavailable or failing, it reports that
plainly, keeps the stale verdict, and exits 1. It never slices
anything itself.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .core import (check_project, default_snapshot_path, exit_code_for,
                   load_snapshot, render_markdown, save_snapshot,
                   snapshot_project)


def _find_snapshot(root: Path, explicit: str | None) -> tuple[dict | None, Path | None]:
    """Locate the baseline snapshot for a check.

    An explicit --snapshot path wins and is loaded (a corrupt or
    unreadable file raises ValueError, which callers turn into a
    clean exit 2). Without one, the default
    <project>/.ghostwatch/snapshot.json is used if it exists;
    otherwise returns (None, None) and the check falls back to the
    labelled manifest heuristic.
    """
    if explicit:
        p = Path(explicit)
        return load_snapshot(p), p
    p = default_snapshot_path(root)
    if p.exists():
        return load_snapshot(p), p
    return None, None


def try_reexport(root: Path, bundle: Path) -> dict:
    """Attempt one GhostSlice re-export. Never raises.

    Returns a dict with status "ok", "failed", or "unavailable"
    (plus the command and/or a human-readable reason). Callers keep
    the stale verdict either way: a successful re-export only earns
    a fresh snapshot baseline for the *next* check.
    """
    exe = shutil.which("ghostslice")
    if exe:
        cmd = [exe, "export", str(root), "-o", str(bundle)]
    else:
        # Probe the module without side effects.
        try:
            probe = subprocess.run([sys.executable, "-c", "import ghostslice"],
                                   capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "unavailable", "reason": f"ghostslice probe failed: {exc}"}
        if probe.returncode != 0:
            return {"status": "unavailable",
                    "reason": "ghostslice CLI not on PATH and ghostslice module not importable"}
        cmd = [sys.executable, "-m", "ghostslice", "export", str(root), "-o", str(bundle)]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "failed", "command": cmd, "reason": str(exc)}
    if run.returncode != 0:
        return {"status": "failed", "command": cmd, "returncode": run.returncode,
                "reason": (run.stderr or run.stdout or "").strip()[-500:]}
    return {"status": "ok", "command": cmd}


def _write_text_out(path: str, text: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def _write_reports(report: dict, out_json: str | None, out_md: str | None) -> None:
    """Write the report files the caller asked for (either may be None)."""
    if out_json:
        _write_text_out(out_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    if out_md:
        _write_text_out(out_md, render_markdown(report))


def _print_summary(report: dict, flush: bool = False) -> None:
    """Print the human-readable verdict summary to stdout.

    `watch` passes flush=True so a verdict is visible (and survives
    redirection to a file) while the loop is still running; one-shot
    commands exit immediately, so they use the default buffering.
    """
    f = report["findings"]
    print(f"[ghostwatch] verdict: {report['verdict']} (baseline: {report['baseline']})", flush=flush)
    fresh = report.get("freshness")
    if isinstance(fresh, dict):
        score = fresh.get("staleness_score")
        drift = fresh.get("drift") or {}
        print(f"  freshness: score={score if score is not None else 'unknown'} "
              f"severity={fresh.get('severity', 'unknown')} "
              f"drift={drift.get('bundle_files_stale', 0)}/{drift.get('bundle_files_total', 0)} bundled files",
              flush=flush)
        if fresh.get("recommendation"):
            print(f"  recommendation: {fresh['recommendation']}", flush=flush)
    for key in ("changed_in_bundle", "missing_bundle_file", "removed_from_project",
                "stale_symbols", "changed_not_in_bundle", "added_not_in_bundle", "touched_only"):
        if f.get(key):
            print(f"  {key}: {len(f[key])}", flush=flush)
            for it in f[key][:20]:
                label = it["path"]
                detail = it.get("reason") or (f"removed symbols: {it.get('removed')}" if it.get("removed") else "symbols changed")
                print(f"    - {label}: {detail}", flush=flush)
    if report.get("reexport"):
        print(f"  reexport: {report['reexport'].get('status')} {report['reexport'].get('reason', '')}".rstrip(), flush=flush)


def cmd_snapshot(args) -> int:
    """`ghostwatch snapshot`: write a fresh baseline snapshot file.

    Always hashes every file (a baseline must be authoritative; the
    stat pre-filter is a check-time optimisation only). Returns 0 on
    success, 2 if the project cannot be read.
    """
    root = Path(args.project)
    try:
        snap = snapshot_project(root, bundle=args.bundle)
    except ValueError as exc:
        print(f"ghostwatch snapshot: {exc}", file=sys.stderr)
        return 2
    out = Path(args.output) if args.output else default_snapshot_path(root)
    try:
        save_snapshot(snap, out)
    except OSError as exc:
        print(f"ghostwatch snapshot: cannot write snapshot ({exc})", file=sys.stderr)
        return 2
    print(f"[ghostwatch] snapshot: {len(snap['files'])} file(s) hashed -> {out}")
    if snap.get("bundle"):
        print(f"  bundle: {snap['bundle']['path']} (manifest {snap['bundle']['manifest_sha256'][:12]}...)")
    else:
        print("  bundle: none found (snapshot is project-only)")
    return 0


def _run_check(args, root: Path) -> tuple[dict | None, int]:
    """Shared check body for `check` and `watch`.

    Returns (report, exit_code), or (None, 2) when no check could be
    made (missing project, no bundle, corrupt snapshot). Handles the
    opt-in --reexport: only on a stale verdict, and the returned
    verdict stays stale for this run even if the re-export succeeds.
    """
    try:
        snap, _ = _find_snapshot(root, args.snapshot)
        report = check_project(root, bundle=args.bundle, snapshot=snap,
                               strict_added=args.strict_added)
    except ValueError as exc:
        print(f"ghostwatch check: {exc}", file=sys.stderr)
        return None, 2
    if args.reexport and report["verdict"] == "stale":
        bundle_path = Path(report["bundle"])
        result = try_reexport(root, bundle_path)
        report["reexport"] = result
        if result["status"] == "ok":
            # Fresh baseline for the new bundle; verdict stays stale for
            # THIS run (the bundle the caller asked about was stale).
            try:
                save_snapshot(snapshot_project(root, bundle=bundle_path),
                              default_snapshot_path(root))
                report["reexport"]["snapshot_refreshed"] = True
            except ValueError:
                report["reexport"]["snapshot_refreshed"] = False
    return report, exit_code_for(report)


def cmd_check(args) -> int:
    """`ghostwatch check`: one staleness check; exit 0/1/2 by verdict."""
    root = Path(args.project)
    report, code = _run_check(args, root)
    if report is None:
        return code
    try:
        _write_reports(report,
                       args.json_out if args.json_out else None,
                       args.md_out if args.md_out else None)
    except OSError as exc:
        print(f"ghostwatch check: cannot write report ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_summary(report)
    return code


def cmd_watch(args) -> int:
    """`ghostwatch watch`: poll `check` until Ctrl-C or --max-polls.

    A verdict change is printed only after two consecutive polls
    agree, so a mid-save read does not flap the output. Exit code is
    the session summary: 0 if no stale verdict was ever reported,
    else 1 (2 if a check could not be made at all).
    """
    root = Path(args.project)
    if not root.is_dir():
        print(f"ghostwatch watch: project not found: {root}", file=sys.stderr)
        return 2
    print(f"[ghostwatch] watching {root} every {args.interval:g}s "
          f"(two consecutive identical verdicts required; Ctrl-C to stop)", flush=True)
    ever_stale = False
    last_key: str | None = None
    pending_key: str | None = None
    polls = 0
    try:
        while True:
            polls += 1
            report, _code = _run_check(args, root)
            if report is None:
                return 2
            key = json.dumps([report["verdict"], report["findings"]], sort_keys=True)
            if key == pending_key and key != last_key:
                last_key = key
                _print_summary(report, flush=True)
                if args.write_report:
                    try:
                        _write_reports(report, args.json_out, args.md_out)
                    except OSError as exc:
                        print(f"ghostwatch watch: cannot write report ({exc})",
                              file=sys.stderr, flush=True)
                        return 2
            pending_key = key
            if report["verdict"] == "stale":
                ever_stale = True
            if args.max_polls is not None and polls >= args.max_polls:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    print(f"[ghostwatch] stopped: {polls} poll(s), stale seen: {ever_stale}", flush=True)
    return 1 if ever_stale else 0


def _interval_arg(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"interval must be a number: {text!r}")
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("interval must be a finite, non-negative number of seconds")
    return value


def _max_polls_arg(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"max-polls must be an integer: {text!r}")
    if value < 1:
        raise argparse.ArgumentTypeError("max-polls must be at least 1")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for snapshot / check / watch."""
    p = argparse.ArgumentParser(
        prog="ghostwatch",
        description="Standalone staleness checker for saved GhostSlice "
                    "bundles and Packs. Reports whether a saved bundle "
                    "still matches its project: fresh, stale, or unknown. "
                    "It never refreshes a bundle on its own; re-export "
                    "happens only when you pass --reexport.",
        epilog="Exit codes: 0 = fresh, 1 = stale, "
               "2 = unknown / could not determine.\n"
               "Typical flow: ghostwatch snapshot <project> at bundle "
               "time, then ghostwatch check <project> before reusing "
               "the bundle.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"ghostwatch {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, writing_snapshot=False):
        sp.add_argument("project", help="path to the project directory")
        sp.add_argument("--bundle", default=None,
                        help="bundle or Pack directory "
                             "(default: <project>/.claude_context)")
        if writing_snapshot:
            # Accepted for symmetry with check/watch; snapshot writes
            # a baseline, it does not read one. The output path is -o.
            sp.add_argument("--snapshot", default=None,
                            help="ignored by snapshot (it writes the "
                                 "baseline; choose its path with -o)")
        else:
            sp.add_argument("--snapshot", default=None,
                            help="baseline snapshot file to diff against "
                                 "(default: <project>/.ghostwatch/snapshot.json; "
                                 "without one, check falls back to a labelled "
                                 "mtime heuristic and never reports fresh)")

    def report_args(sp, for_watch):
        sp.add_argument("--json-out", default=None, metavar="PATH",
                        help="write the machine-readable JSON report to PATH")
        sp.add_argument("--md-out", default=None, metavar="PATH",
                        help="write the human-readable Markdown report to PATH")
        if for_watch:
            sp.add_argument("--write-report", action="store_true",
                            help="with --json-out/--md-out: rewrite the report "
                                 "files on each settled verdict change")
        else:
            sp.add_argument("--write-report", action="store_true",
                            help="accepted for symmetry with watch; check "
                                 "already writes --json-out/--md-out whenever "
                                 "they are given")

    def stale_args(sp):
        sp.add_argument("--strict-added", action="store_true",
                        help="also report stale when a file listed in the "
                             "bundle manifest was added after the snapshot "
                             "(by default, added files are context only)")
        sp.add_argument("--reexport", action="store_true",
                        help="opt-in: on a stale verdict, try ONE re-export "
                             "by delegating to the GhostSlice CLI, then take "
                             "a fresh snapshot for the next check. This run "
                             "still exits 1 (the bundle you asked about was "
                             "stale). If GhostSlice is unavailable, reports "
                             "'reexport: unavailable' and exits 1. Without "
                             "this flag, GhostWatch never touches the bundle.")

    sp = sub.add_parser(
        "snapshot",
        help="snapshot project source hashes + symbols (run at bundle time)",
        description="Record the baseline: a sha256 and a symbol outline "
                    "for every visible source file, plus the bundle's "
                    "manifest hash if a bundle is found. Hashes and symbol "
                    "names only; file bodies are never stored. Always "
                    "hashes everything: a baseline must be authoritative.")
    common(sp, writing_snapshot=True)
    sp.add_argument("-o", "--output", default=None, metavar="PATH",
                    help="where to write the snapshot "
                         "(default: <project>/.ghostwatch/snapshot.json)")
    sp.set_defaults(fn=cmd_snapshot)

    sp = sub.add_parser(
        "check",
        help="check once: is the saved bundle/Pack still fresh?",
        description="Re-snapshot the project in memory and diff it "
                    "against the baseline snapshot. Prints a verdict "
                    "(fresh / stale / unknown) with every finding "
                    "classified by file and by symbol. Read-only: "
                    "writes nothing unless you pass --json-out, "
                    "--md-out, or --reexport.")
    common(sp)
    stale_args(sp)
    sp.add_argument("--json", action="store_true",
                    help="print the full JSON report to stdout instead "
                         "of the short human summary")
    report_args(sp, for_watch=False)
    sp.set_defaults(fn=cmd_check)

    sp = sub.add_parser(
        "watch",
        help="polling loop over check (convenience only, no daemon)",
        description="Run check repeatedly and print each settled "
                    "verdict change (a change must appear in two "
                    "consecutive polls before it is reported). Runs "
                    "until Ctrl-C unless --max-polls bounds it. "
                    "snapshot + check are the product; watch is a "
                    "convenience loop over check.")
    common(sp)
    sp.add_argument("--interval", type=_interval_arg, default=2.0, metavar="SECONDS",
                    help="seconds to sleep between polls (default: 2)")
    sp.add_argument("--max-polls", type=_max_polls_arg, default=None, metavar="N",
                    help="stop after N polls; mainly for scripts and "
                         "tests (default: run until Ctrl-C)")
    stale_args(sp)
    report_args(sp, for_watch=True)
    sp.set_defaults(fn=cmd_watch)
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse argv and dispatch to the subcommand."""
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
