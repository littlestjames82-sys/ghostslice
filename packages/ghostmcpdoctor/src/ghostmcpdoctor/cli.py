"""GhostMCP Doctor CLI.

  ghostmcpdoctor scan [--config <path> ...] [--project <dir>] [--home <dir>]
                      [--out-dir <dir>] [--no-report] [--json] [paths ...]
  ghostmcpdoctor report <mcpdoctor-report.json> [--out-dir <dir>]

Read-only: scan never edits a config, never starts a server, and never
prints env values (key names, present/absent only).
Exit codes: 0 = scanned, no findings above info; 1 = warnings or errors
found; 2 = could not scan (no configs found, explicit path missing).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .reports import (build_report, exit_code_for, render_markdown,
                      write_reports)
from .scanner import expand_inputs, scan_configs


def _print_summary(report: dict) -> None:
    """Print the short human summary: counts, one line per finding, notes."""
    s = report.get("summary", {})
    print(f"ghostmcpdoctor scan: {s.get('servers_found', 0)} server(s) in "
          f"{s.get('configs_scanned', 0)} config(s), "
          f"{s.get('findings', 0)} finding(s) "
          f"(exit {report.get('exit_code', '?')})")
    for f in report.get("findings", []):
        loc = f.get("path") or f.get("config_path")
        print(f"  [{f['severity']}] {f['server'] or '(config)'} - {loc} - "
              f"{f['issue']}: {f['detail']}")
    for note in report.get("notes", []):
        print(f"  note: {note}")


def _cmd_scan(args) -> int:
    """Run ``scan``: resolve inputs, scan read-only, write/print the report.

    Returns 2 before scanning when an explicit path is missing or no
    config files were found at all; otherwise the report's exit code.
    """
    home = Path(args.home).expanduser() if args.home else Path.home()
    project = Path(args.project).expanduser() if args.project else Path.cwd()
    inputs = list(args.config or []) + list(args.paths or [])
    files, missing = expand_inputs(inputs, home, project)
    if missing:
        for m in missing:
            print(f"error: config path not found: {m}", file=sys.stderr)
        return 2
    if not files:
        print("error: no MCP config files found (defaults do not exist and "
              "no paths were supplied)", file=sys.stderr)
        return 2
    scans = scan_configs(files, home)
    report = build_report(scans, home, missing_explicit=missing)
    if not args.no_report:
        write_reports(report, args.out_dir or Path.cwd())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_summary(report)
    return int(report.get("exit_code", 2))


def _report_shape_ok(report) -> bool:
    """Structural check for a stored report before re-rendering.

    A report file is input, not trusted code: valid JSON with the
    right tool tag but findings / configs / servers of the wrong
    type used to crash the re-render with an uncaught AttributeError
    traceback. Anything that is not the documented shape is a
    "cannot render" (exit 2), like an unreadable file.
    """
    if not isinstance(report, dict):
        return False
    findings = report.get("findings", [])
    if not isinstance(findings, list) \
            or not all(isinstance(f, dict) for f in findings):
        return False
    configs = report.get("configs", [])
    if not isinstance(configs, list) \
            or not all(isinstance(c, dict) for c in configs):
        return False
    servers = report.get("servers", [])
    if not isinstance(servers, list) \
            or not all(isinstance(s, dict) for s in servers):
        return False
    if not isinstance(report.get("summary", {}), dict):
        return False
    for key in ("missing_explicit_paths", "notes"):
        if not isinstance(report.get(key, []), list):
            return False
    return True


def _cmd_report(args) -> int:
    """Run ``report``: re-render Markdown + JSON from a stored scan report.

    No config is re-scanned. Returns 2 when the file cannot be read or
    is not a ghostmcpdoctor report; otherwise the exit code recomputed
    from the stored findings.
    """
    src = Path(args.report_json)
    try:
        report = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read report: {exc.__class__.__name__}",
              file=sys.stderr)
        return 2
    if not isinstance(report, dict) \
            or report.get("tool") != "ghostmcpdoctor":
        print("error: not a ghostmcpdoctor report", file=sys.stderr)
        return 2
    if not _report_shape_ok(report):
        print("error: cannot read report: malformed report structure",
              file=sys.stderr)
        return 2
    try:
        # Recompute the exit code from the stored findings under the same
        # rule scan uses, rather than trusting the stored value: reports
        # written before the info-only fix carry a stale code, and the
        # re-render (and its returned code) must follow the current rule.
        report["exit_code"] = exit_code_for(
            report.get("findings", []), len(report.get("configs", [])),
            fallback=report.get("exit_code", 0))
        out_dir = args.out_dir or src.parent
        json_path, md_path = write_reports(report, out_dir)
    except (TypeError, AttributeError, ValueError, KeyError) as exc:
        # Belt and braces alongside the shape check: a rendering
        # failure is a clean exit 2 with the error class only (the
        # existing no-content-echo rule), never a traceback.
        print(f"error: cannot render report: {exc.__class__.__name__}",
              file=sys.stderr)
        return 2
    print(f"wrote {json_path} and {md_path}")
    if args.markdown:
        print(render_markdown(report))
    return int(report.get("exit_code", 0))


def main(argv=None) -> int:
    """Parse arguments and dispatch to the ``scan`` or ``report`` command."""
    parser = argparse.ArgumentParser(
        prog="ghostmcpdoctor",
        description="Read-only auditor for local MCP / agent-client configs. "
                    "Reports duplicates, missing commands/files, broad "
                    "permissions and stale entries. Never edits a config, "
                    "never starts a server, and never prints env values "
                    "(key names only).",
        epilog="exit codes: 0 = scanned, no findings above info; "
               "1 = warnings or errors found; 2 = could not scan "
               "(no configs found, or an explicitly named path is missing). "
               "Examples: 'ghostmcpdoctor scan ~/.claude.json', "
               "'ghostmcpdoctor scan' (default local locations), "
               "'ghostmcpdoctor report mcpdoctor-report.json'.")
    parser.add_argument("--version", action="version",
                        version=f"ghostmcpdoctor {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "scan", help="scan MCP configs (read-only)",
        description="Scan MCP config files or directories, read-only. "
                    "With no paths, the default local locations are used, "
                    "but only the ones that exist on this machine.")
    p.add_argument("paths", nargs="*",
                   help="config files or directories; a directory is "
                        "searched for the known MCP filenames "
                        "(mcp.json, .mcp.json, .claude.json, "
                        ".cursor/mcp.json, .vscode/mcp.json)")
    p.add_argument("--config", action="append",
                   help="explicit config file or directory (repeatable); "
                        "same as a positional path, for scripts that build "
                        "the list separately")
    p.add_argument("--project",
                   help="project root for the default local paths "
                        "(default: current directory); only affects a "
                        "scan with no explicit paths")
    p.add_argument("--home",
                   help="home root for the default local paths "
                        "(default: your home directory); mainly for "
                        "testing against fixture homes")
    p.add_argument("--out-dir", help="where to write mcpdoctor-report.json "
                                     "+ MCPDOCTOR.md (default: cwd)")
    p.add_argument("--no-report", action="store_true",
                   help="write no report files; print only the summary "
                        "(or the JSON report with --json)")
    p.add_argument("--json", action="store_true",
                   help="print the full (redacted) report as JSON to "
                        "stdout instead of the short summary; report "
                        "files are still written unless --no-report")

    p = sub.add_parser(
        "report", help="re-render reports from a scan JSON",
        description="Re-render MCPDOCTOR.md + mcpdoctor-report.json from "
                    "a previous scan's JSON report, without re-scanning "
                    "any config. The input is already redacted, so the "
                    "output is safe to share.")
    p.add_argument("report_json",
                   help="path to a mcpdoctor-report.json written by an "
                        "earlier scan")
    p.add_argument("--out-dir", help="output directory (default: report's dir)")
    p.add_argument("--markdown", action="store_true",
                   help="also print the Markdown report to stdout")

    args = parser.parse_args(argv)
    if args.command == "scan":
        return _cmd_scan(args)
    if args.command == "report":
        return _cmd_report(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
