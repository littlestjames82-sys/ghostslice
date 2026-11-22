"""Command line: ``ghostworkflow run <project> [--task ...]``.

Exit codes: 0 = the run completed, every step ok or honestly
attention (a gaps_found Verify verdict is a recorded outcome, not a
crash); 1 = a step failed (the workflow report is still written);
2 = usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .orchestrator import DEFAULT_TIMEOUT, run_workflow
from .report import ReportValidationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghostworkflow",
        description="Run the Ghost ecosystem end to end on one project: "
                    "GhostSlice bundle -> GhostVerify pre-flight -> "
                    "GhostBench run -> GhostConsole board, with one "
                    "workflow-report.json as the evidence record.")
    parser.add_argument("--version", action="version",
                        version=f"ghostworkflow {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser(
        "run", help="run the workflow on a project")
    p_run.add_argument("project", help="project directory to work on")
    p_run.add_argument("--task", default=None,
                       help="task text the bundle and checks are for")
    p_run.add_argument("--test-command", default=None,
                       help="test command for the bench starter task; "
                            "when set, the bench run executes tests "
                            "(contained) via --run-tests")
    p_run.add_argument("--out", default=None,
                       help="run output directory (default: "
                            "<project>/.ghostworkflow/<run-id>)")
    p_run.add_argument("--engine-home", default=None,
                       help="directory holding engine checkouts "
                            "(ghostslice/, ghostverify/, ghostbench/, "
                            "ghostconsole/); overrides "
                            "GHOSTWORKFLOW_ENGINE_HOME and the default "
                            "sibling-checkout search")
    p_run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                       help="per-engine timeout in seconds "
                            f"(default: {DEFAULT_TIMEOUT})")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help(sys.stderr)
        return 2

    project = Path(args.project).expanduser()
    if not project.is_dir():
        print(f"ghostworkflow: error: not a directory: {args.project}",
              file=sys.stderr)
        return 2

    try:
        report, exit_code, report_path = run_workflow(
            project, task=args.task, test_command=args.test_command,
            out=args.out, engine_home=args.engine_home,
            timeout=args.timeout)
    except ReportValidationError as exc:
        print("ghostworkflow: error: the workflow report failed its own "
              f"validation and was not written: {exc}", file=sys.stderr)
        return 1

    board = report_path.parent / "board.html"
    print(f"run {report['run_id']}: verdict {report['verdict']} "
          f"(verification level: {report['verification_level']})")
    for step in report["steps"]:
        print(f"  {step['name']:<8} {step['status']:<9} {step['detail']}")
    print(f"board:  {board}")
    print(f"report: {report_path}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
