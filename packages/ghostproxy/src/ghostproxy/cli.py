"""GhostProxy CLI: serve | doctor | report | transform, plus --version.

Client setup (one documented path, Claude Code): set the client's
base-URL environment variable to the local proxy, e.g.
``ANTHROPIC_BASE_URL=http://127.0.0.1:8787``. Undo: unset it (or point
it back at https://api.anthropic.com) and stop the proxy. GhostProxy
never edits a client's config itself.

Every subcommand accepts ``--help``. Flags override the ``proxy``
section of the project's ``.ghostslice.json``, which overrides the
built-in defaults (host 127.0.0.1, port 8787, upstream
https://api.anthropic.com, budget 60000 estimated tokens).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, build_config
from .doctor import doctor_exit_code, run_doctor
from .ledger import Ledger, build_report, render_report_md
from .server import serve
from .transform import transform_request


def _add_common(p: argparse.ArgumentParser) -> None:
    """Shared serve/doctor options; every one overrides the profile."""
    p.add_argument("--project", default=None,
                   help="project dir whose .ghostslice.json proxy section is read")
    p.add_argument("--host", default=None,
                   help="interface to bind; loopback only in v0.1 "
                        "(profile or built-in default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=None,
                   help="port to listen on (profile or built-in default: 8787)")
    p.add_argument("--upstream", default=None,
                   help="upstream API base URL (profile or built-in default: "
                        "https://api.anthropic.com)")
    p.add_argument("--budget", type=int, default=None,
                   help="per-request context budget in estimated tokens")
    p.add_argument("--ledger", default=None, help="ledger JSONL path")


def _config_from(args) -> object:
    """Build the effective config: CLI flags > profile > defaults."""
    overrides = {
        "host": getattr(args, "host", None),
        "port": getattr(args, "port", None),
        "upstream": getattr(args, "upstream", None),
        "budget_tokens": getattr(args, "budget", None),
        "ledger_path": getattr(args, "ledger", None),
        "log_bodies": getattr(args, "log_bodies", None),
    }
    return build_config(getattr(args, "project", None), overrides)


def main(argv=None) -> int:
    """Entry point. Returns 0 on success, 2 on usage/config errors."""
    parser = argparse.ArgumentParser(
        prog="ghostproxy",
        description="Local, fail-open context proxy for GhostSlice "
                    "(Anthropic Messages shape, localhost only).",
        epilog="examples:\n"
               "  ghostproxy serve --project ~/my-project\n"
               "  ghostproxy doctor --project ~/my-project --check-upstream\n"
               "  ghostproxy report --project ~/my-project\n"
               "  ghostproxy transform request.json --budget 20000\n"
               "\n"
               "Run 'ghostproxy <command> --help' for a command's options. "
               "GhostProxy never stores or logs your API key.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version",
                        version=f"ghostproxy {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser(
        "serve", help="run the localhost proxy",
        description="Run the localhost proxy. Fail-open: any request the "
                    "proxy cannot transform is forwarded untouched.")
    _add_common(p_serve)
    p_serve.add_argument("--log-bodies", action="store_true", default=None,
                         help="EXPLICIT opt-in: allow body-aware diagnostics. "
                              "The ledger still stores no bodies in v0.1.")

    p_doctor = sub.add_parser(
        "doctor", help="health check (no paid calls)",
        description="Health check: loopback host rule, port free, profile "
                    "valid, GhostSlice importable, ledger writable. "
                    "Makes no paid calls.")
    _add_common(p_doctor)
    p_doctor.add_argument("--check-upstream", action="store_true",
                          help="send a bare HEAD probe to the upstream "
                               "(no auth, no billable request)")

    p_report = sub.add_parser(
        "report", help="roll the ledger into a report",
        description="Roll the request ledger up into a summary report "
                    "(Markdown by default).")
    p_report.add_argument("--ledger", default=None,
                          help="ledger JSONL path (overrides --project)")
    p_report.add_argument("--project", default=None,
                          help="project dir; reads <project>/.ghostproxy-ledger.jsonl")
    p_report.add_argument("-o", "--out", default=None,
                          help="write the JSON report to this file")
    p_report.add_argument("--json", action="store_true",
                          help="print the report as JSON instead of Markdown")

    p_transform = sub.add_parser(
        "transform", help="transform one Messages JSON file (debug/demo)",
        description="Transform one Anthropic Messages JSON file: the "
                    "transformed request goes to stdout (or --out) and "
                    "the transform map goes to stderr.")
    p_transform.add_argument("file", help="JSON file, or - for stdin")
    p_transform.add_argument("--budget", type=int, default=60_000,
                             help="context budget in estimated tokens "
                                  "(default: 60000)")
    p_transform.add_argument("-o", "--out", default=None,
                             help="write the transformed request to this "
                                  "file instead of stdout")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    try:
        if args.command == "serve":
            config = _config_from(args)
            serve(config)
            return 0
        if args.command == "doctor":
            config = _config_from(args)
            checks = run_doctor(config, check_upstream=args.check_upstream)
            for c in checks:
                print(c.line())
            return doctor_exit_code(checks)
        if args.command == "report":
            if args.ledger:
                path = Path(args.ledger)
            elif args.project:
                path = Path(args.project) / ".ghostproxy-ledger.jsonl"
            else:
                path = Path.cwd() / ".ghostproxy-ledger.jsonl"
            report = build_report(Ledger(path).entries())
            if args.out:
                Path(args.out).write_text(json.dumps(report, indent=2),
                                           encoding="utf-8")
            elif args.json:
                print(json.dumps(report, indent=2))
            else:
                print(render_report_md(report), end="")
            return 0
        if args.command == "transform":
            raw = sys.stdin.read() if args.file == "-" else \
                Path(args.file).read_text(encoding="utf-8")
            result = transform_request(json.loads(raw),
                                       budget_tokens=args.budget)
            payload = json.dumps(result.request)
            if args.out:
                Path(args.out).write_text(payload, encoding="utf-8")
            else:
                print(payload)
            print(json.dumps(result.to_dict(), indent=2), file=sys.stderr)
            return 0
    except ConfigError as exc:
        print(f"ghostproxy: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        # User-facing input problems (missing/unreadable file, malformed
        # JSON for the transform command, unwritable report path) are
        # clean one-line errors with exit 2, never a traceback.
        # ConfigError is a ValueError subclass and is handled above.
        print(f"ghostproxy: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
