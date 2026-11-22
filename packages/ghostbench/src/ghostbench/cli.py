"""GhostBench command-line interface.

Commands:
  ghostbench run <corpus> [--suite slice|verify|recall|proxy]
                          [--out DIR] [--task ID ...] [--run-tests]
                          [--model ID] [--ledger PATH] [--no-ledger]
                          [--strict]
      Tier A static run (default tier): no model, no spend. Writes
      BENCH.md + bench-report.json to the output folder and appends a
      record to the history ledger next to the corpus file.
  ghostbench compare <run-a.json> <run-b.json> [--out FILE]
      Per-task token and status deltas between two run reports (B - A).
      Each argument may be a bench-report.json file or a run folder.
  ghostbench add <corpus> --project PATH --id ID [--name NAME]
      Record a project in a corpus file by tree hash. Copies no code.
  ghostbench live <corpus> [--out DIR] [--task ID ...]
                          [--agent-timeout SECONDS] [--budget TOKENS]
                          [--confirm] [--ledger PATH]
                          [--no-ledger] [--strict]
      Tier B live run: for each task, the agent command configured
      in the GHOSTBENCH_AGENT_CMD environment variable attempts the
      task in a contained copy, then the task's tests run in the
      same copy. Reports carry verification_level "live-agent".
      With no agent configured, live refuses before anything runs.
      With --budget, the run's estimated context tokens are checked
      against the cap before anything runs; over the cap it refuses
      unless --confirm is given. See ghostbench.tierb.
  ghostbench demo-corpus <dir>
      Write the starter adversarial demo corpus into <dir>.
  ghostbench version
      Print the GhostBench version and exit.

Exit codes: 0 on success, 1 when ``run --strict`` finds a failing
task, 2 on usage errors, corpus errors, and Tier B refusals.
Run ``ghostbench <command> --help`` for per-command examples.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .corpus import CorpusError, compute_tree_hash, load_corpus
from .demo import make_demo_corpus
from .report import (compare_reports, render_compare_md,
                     write_bench_md, write_json_report)
from .runner import append_ledger, run_corpus
from .tierb import (AGENT_CMD_ENV, TierBRefusal, agent_argv_from_env,
                    budget_gate, run_live_corpus)


def _cmd_run(args) -> int:
    """Handle ``ghostbench run``: Tier A run, write reports, append ledger."""
    corpus = load_corpus(args.corpus)
    task_filter = set(args.task) if args.task else None
    report = run_corpus(corpus, suite=args.suite,
                        run_tests=args.run_tests,
                        task_filter=task_filter, model=args.model)
    if not report["tasks"]:
        # A report with no rows is invalid by the hard rules, and
        # writing one file before the writer refused left partial
        # artifacts behind. Refuse cleanly, before writing anything.
        print("error: run matched no tasks "
              "(check the --task filter); no report written",
              file=sys.stderr)
        return 2
    out_dir = args.out or os.path.join(corpus.base_dir, "runs",
                                       report["run_id"])
    write_json_report(report, os.path.join(out_dir, "bench-report.json"))
    write_bench_md(report, os.path.join(out_dir, "BENCH.md"))
    ledger_path = None
    if not args.no_ledger:
        ledger_path = args.ledger or os.path.join(
            corpus.base_dir, ".ghostbench-history.jsonl")
        append_ledger(report, ledger_path)
    t = report["totals"]
    sliced = t["variants"].get("sliced", {})
    print(f"run {report['run_id']}: tasks={t['tasks']} "
          f"pass={t['pass']} fail={t['fail']} unknown={t['unknown']} "
          f"full={t['full_tokens']} sliced={sliced.get('tokens')} "
          f"saving={sliced.get('saving_pct_vs_full')}%")
    print(f"wrote {out_dir}/BENCH.md and bench-report.json")
    if ledger_path:
        print(f"ledger appended: {ledger_path}")
    return 1 if t["fail"] and args.strict else 0


def _load_report_arg(value: str) -> dict:
    """Compare accepts a bench-report.json file or a run directory
    containing one."""
    path = value
    if os.path.isdir(path):
        path = os.path.join(path, "bench-report.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise ValueError(f"cannot read report {value}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"report {value} is not valid JSON: {exc}") from exc


def _cmd_compare(args) -> int:
    """Handle ``ghostbench compare``: print or write the B - A comparison."""
    rep_a = _load_report_arg(args.run_a)
    rep_b = _load_report_arg(args.run_b)
    comp = compare_reports(rep_a, rep_b)
    if args.out:
        if args.out.endswith(".json"):
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(comp, fh, indent=2, sort_keys=True)
        else:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(render_compare_md(comp))
        print(f"wrote {args.out}")
    else:
        print(render_compare_md(comp))
    if comp["estimator_mismatch_warning"]:
        print(f"WARNING: {comp['estimator_mismatch_warning']}",
              file=sys.stderr)
    return 0


def _cmd_add(args) -> int:
    """Handle ``ghostbench add``: record a project by tree hash, copy nothing."""
    project_path = os.path.abspath(args.project)
    if not os.path.isdir(project_path):
        print(f"error: not a directory: {args.project}", file=sys.stderr)
        return 2
    tree_hash = compute_tree_hash(project_path)
    entry = {"id": args.id, "path": project_path,
             "tree_hash": tree_hash, "tasks": []}
    corpus_path = args.corpus
    if os.path.isfile(corpus_path):
        with open(corpus_path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or (
                "projects" in data and (
                    not isinstance(data["projects"], list) or not all(
                        isinstance(p, dict) for p in data["projects"]))):
            print(f"error: existing corpus is not in corpus format: "
                  f"{corpus_path}", file=sys.stderr)
            return 2
        ids = {p.get("id") for p in data.get("projects") or []}
        if args.id in ids:
            print(f"error: project id already in corpus: {args.id}",
                  file=sys.stderr)
            return 2
        data.setdefault("projects", []).append(entry)
    else:
        data = {"name": args.name or "my-corpus", "version": "1",
                "projects": [entry]}
    with open(corpus_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    print(f"recorded project {args.id} tree_hash={tree_hash} "
          f"in {corpus_path} (no code copied)")
    return 0


def _cmd_live(args) -> int:
    """Handle ``ghostbench live``: Tier B live-agent run.

    The agent command comes ONLY from GHOSTBENCH_AGENT_CMD and is
    resolved before the corpus is even loaded: with no agent
    configured, the run refuses before anything runs and nothing is
    written.
    """
    try:
        agent_argv = agent_argv_from_env()
    except TierBRefusal as exc:
        print(f"Tier B refused: {exc}", file=sys.stderr)
        return 2
    corpus = load_corpus(args.corpus)
    task_filter = set(args.task) if args.task else None
    # The budget gate runs after the configuration gate and before
    # any agent runs, with the same refusal discipline: exit 2 and
    # nothing written.
    try:
        budget = budget_gate(corpus, budget_cap=args.budget,
                             confirmed=args.confirm,
                             task_filter=task_filter)
    except TierBRefusal as exc:
        print(f"Tier B refused: {exc}", file=sys.stderr)
        invocation = ["ghostbench", "live", str(args.corpus)]
        for task_id in args.task or []:
            invocation += ["--task", str(task_id)]
        invocation += ["--budget", str(args.budget), "--confirm"]
        print("  to run anyway: " + " ".join(invocation),
              file=sys.stderr)
        return 2
    if budget["exceeded"]:
        print(f"budget: estimated {budget['budget_estimate']} "
              f"context tokens exceeds the cap of "
              f"{budget['budget_cap']} tokens; proceeding under "
              "--confirm (the cap bounds Bench's estimate only, "
              "not the agent's own charges)")
    try:
        report = run_live_corpus(corpus, agent_argv=agent_argv,
                                 agent_timeout=args.agent_timeout,
                                 task_filter=task_filter,
                                 budget=budget)
    except TierBRefusal as exc:
        print(f"Tier B refused: {exc}", file=sys.stderr)
        return 2
    if not report["tasks"]:
        print("error: run matched no tasks "
              "(check the --task filter); no report written",
              file=sys.stderr)
        return 2
    out_dir = args.out or os.path.join(corpus.base_dir, "runs",
                                       report["run_id"])
    write_json_report(report, os.path.join(out_dir, "bench-report.json"))
    write_bench_md(report, os.path.join(out_dir, "BENCH.md"))
    ledger_path = None
    if not args.no_ledger:
        ledger_path = args.ledger or os.path.join(
            corpus.base_dir, ".ghostbench-history.jsonl")
        append_ledger(report, ledger_path)
    t = report["totals"]
    print(f"Tier B live run: agent={report['agent']['name']} "
          f"(command from {AGENT_CMD_ENV}; only the first token is "
          "recorded)")
    print(f"run {report['run_id']}: tasks={t['tasks']} "
          f"pass={t['pass']} fail={t['fail']} unknown={t['unknown']} "
          f"verification_level={report['verification_level']}")
    if budget["budget_cap"] is not None:
        print(f"budget: cap {budget['budget_cap']} tokens, "
              f"estimated run context "
              f"{budget['budget_estimate']} tokens"
              + (" (cap exceeded, confirmed)"
                 if budget["exceeded"] else ""))
    print(f"wrote {out_dir}/BENCH.md and bench-report.json")
    if ledger_path:
        print(f"ledger appended: {ledger_path}")
    return 1 if t["fail"] and args.strict else 0


def _cmd_demo(args) -> int:
    """Handle ``ghostbench demo-corpus``: write the starter demo corpus."""
    path = make_demo_corpus(args.dir)
    print(f"demo corpus written: {path}")
    print(f"run it: ghostbench run {path} --out <runs-dir>")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for all GhostBench subcommands."""
    parser = argparse.ArgumentParser(
        prog="ghostbench",
        description="Proof harness for GhostSlice: same tasks, same "
                    "projects, full vs sliced context, scored the same "
                    "way every time. Tier A is static by default; "
                    "Tier B live runs only an agent command the user "
                    "configures in GHOSTBENCH_AGENT_CMD.",
        epilog="Examples:\n"
               "  ghostbench run examples/corpora/adversarial/corpus.json "
               "--out /tmp/bench-adv\n"
               "  ghostbench compare run-a/bench-report.json "
               "run-b/bench-report.json\n"
               "  ghostbench demo-corpus /tmp/ghostbench-demo\n"
               "Token counts are estimates; see README.md for the corpus "
               "and report formats.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_run = sub.add_parser(
        "run", help="Tier A static run (no model, no spend)",
        description="Run Tier A (static) on a corpus: bundle sizes, "
                    "GhostVerify verdicts, and recorded-patch checks. "
                    "Writes BENCH.md and bench-report.json.",
        epilog="Example:\n"
               "  ghostbench run corpus.json --out /tmp/run-1 --strict")
    p_run.add_argument("corpus", help="path to the corpus JSON file")
    p_run.add_argument("--suite", choices=["slice", "verify", "recall", "proxy"],
                       default="slice",
                       help="which variant arm to include besides full "
                            "and sliced (default: slice)")
    p_run.add_argument("--out", metavar="DIR",
                       help="output folder for BENCH.md and "
                            "bench-report.json (default: "
                            "<corpus-dir>/runs/<run-id>)")
    p_run.add_argument("--task", action="append", metavar="ID",
                       help="only this task id (repeatable); run is labelled a subset")
    p_run.add_argument("--run-tests", action="store_true",
                       help="run task test commands in a temp copy (opt-in)")
    p_run.add_argument("--model", metavar="ID",
                       help="model id for cost estimates (price table lookup)")
    p_run.add_argument("--ledger", metavar="PATH",
                       help="history ledger file to append to (default: "
                            ".ghostbench-history.jsonl next to the corpus)")
    p_run.add_argument("--no-ledger", action="store_true",
                       help="do not append this run to the history ledger")
    p_run.add_argument("--strict", action="store_true",
                       help="exit 1 when any task fails")
    p_run.set_defaults(func=_cmd_run)

    p_cmp = sub.add_parser(
        "compare", help="compare two bench-report.json files",
        description="Compare two run reports and show per-task token "
                    "and status deltas (B - A). Each argument may be a "
                    "bench-report.json file or a run folder containing one.",
        epilog="Example:\n"
               "  ghostbench compare examples/runs/sample-tier-a-run-a "
               "examples/runs/sample-tier-a-run-b")
    p_cmp.add_argument("run_a", help="first (baseline) report file or run folder")
    p_cmp.add_argument("run_b", help="second report file or run folder")
    p_cmp.add_argument("--out", metavar="FILE",
                       help="write the comparison to FILE instead of stdout "
                            "(.json writes JSON, anything else writes Markdown)")
    p_cmp.set_defaults(func=_cmd_compare)

    p_add = sub.add_parser(
        "add", help="record a project in a corpus file by tree hash",
        description="Record a project in a corpus file by tree hash. "
                    "Creates the corpus file if it does not exist. "
                    "No project code is copied into the corpus.")
    p_add.add_argument("corpus", help="corpus JSON file to create or update")
    p_add.add_argument("--project", required=True, metavar="PATH",
                       help="path to the project directory to record")
    p_add.add_argument("--id", required=True, metavar="ID",
                       help="unique project id to record it under")
    p_add.add_argument("--name", help="corpus name when creating a new corpus")
    p_add.set_defaults(func=_cmd_add)

    p_live = sub.add_parser(
        "live", help="Tier B live run (agent from GHOSTBENCH_AGENT_CMD)",
        description="Tier B live run. For each task, an agent command "
                    "attempts the task in a contained copy of the "
                    "project, Bench measures the files it changed, and "
                    "the task's test command then runs in the same "
                    "copy. Reports carry verification_level "
                    "\"live-agent\" on the report and every row.\n\n"
                    "The agent command comes ONLY from the environment "
                    "variable GHOSTBENCH_AGENT_CMD (a shell-style "
                    "command line, split with shlex and executed "
                    "directly - no shell, so pipes/redirection in "
                    "the command do not work). Bench hardcodes no "
                    "vendor and has no default agent: if "
                    "GHOSTBENCH_AGENT_CMD is unset or empty, live "
                    "refuses before anything runs and writes nothing. "
                    "Only the command's first token is recorded in "
                    "reports (a command line may carry keys in its "
                    "arguments).\n\n"
                    "Per task the agent runs with the task copy as "
                    "its working directory and receives:\n"
                    "  GHOSTBENCH_TASK_DIR    - path of the task copy\n"
                    "  GHOSTBENCH_TASK_ID     - the task id\n"
                    "  GHOSTBENCH_TASK_PROMPT - the task prompt\n"
                    "and the task copy path appended as the final "
                    "command argument. Its environment is the "
                    "contained runner's scrubbed allowlist plus "
                    "those three variables: parent-process secrets "
                    "never reach it.\n\n"
                    "Containment honesty: the agent runs with your "
                    "permissions outside an OS sandbox. Its working "
                    "directory is the task copy and Bench directs "
                    "its work there, but host writes elsewhere are "
                    "NOT prevented, and network access is NOT "
                    "blocked. POSIX rlimits and the timeout are "
                    "best-effort. Every report's sandbox block states "
                    "exactly this.\n\n"
                    "Budget cap: --budget TOKENS adds a second, "
                    "independent gate. After the agent check and "
                    "before any agent runs, Bench estimates the "
                    "run's context size - the sum of the per-task "
                    "full-context token estimates from Bench's own "
                    "estimator, the same numbers the report later "
                    "shows as full_tokens - and checks it against "
                    "the cap (the check_budget rule: estimated "
                    "tokens <= cap). Over the cap, live refuses "
                    "before anything runs and writes nothing, "
                    "unless --confirm is given; a confirmed run "
                    "records the cap, the estimate, and the "
                    "confirmation in its report. The cap is in "
                    "TOKENS and bounds Bench's estimate only: the "
                    "configured agent's real cost is whatever the "
                    "agent itself charges, inside your own program. "
                    "Bench does not meter the agent, and no cap "
                    "here bounds what it bills.",
        epilog="Example:\n"
               "  GHOSTBENCH_AGENT_CMD='my-agent --non-interactive' "
               "ghostbench live corpus.json --out /tmp/live-1\n"
               "  GHOSTBENCH_AGENT_CMD='my-agent --non-interactive' "
               "ghostbench live corpus.json --budget 200000 --confirm")
    p_live.add_argument("corpus", help="path to the corpus JSON file")
    p_live.add_argument("--out", metavar="DIR",
                        help="output folder for BENCH.md and "
                             "bench-report.json (default: "
                             "<corpus-dir>/runs/<run-id>)")
    p_live.add_argument("--task", action="append", metavar="ID",
                        help="only this task id (repeatable); run is labelled a subset")
    p_live.add_argument("--agent-timeout", type=int, metavar="SECONDS",
                        default=300,
                        help="wall-clock timeout for each task's agent "
                             "attempt (default: 300)")
    p_live.add_argument("--budget", type=int, metavar="TOKENS",
                        help="cap the run's estimated context tokens "
                             "(sum of the per-task full-context "
                             "estimates from Bench's estimator). Over "
                             "the cap, live refuses before anything "
                             "runs unless --confirm is given. The cap "
                             "bounds Bench's estimate only, never "
                             "the agent's own charges")
    p_live.add_argument("--confirm", action="store_true",
                        help="proceed even when the estimated run "
                             "context exceeds --budget; the report "
                             "records the cap, the estimate, and "
                             "that confirmation overrode the cap")
    p_live.add_argument("--ledger", metavar="PATH",
                        help="history ledger file to append to (default: "
                             ".ghostbench-history.jsonl next to the corpus)")
    p_live.add_argument("--no-ledger", action="store_true",
                        help="do not append this run to the history ledger")
    p_live.add_argument("--strict", action="store_true",
                        help="exit 1 when any task fails")
    p_live.set_defaults(func=_cmd_live)

    p_demo = sub.add_parser(
        "demo-corpus", help="write the starter adversarial corpus",
        description="Write the core's starter adversarial demo corpus "
                    "(project, patches, and corpus.json) into a directory "
                    "you choose.")
    p_demo.add_argument("dir", help="target directory to write the demo corpus into")
    p_demo.set_defaults(func=_cmd_demo)

    sub.add_parser("version", help="print version",
                   description="Print the GhostBench version and exit.")
    return parser


def main(argv=None) -> int:
    """CLI entry point. Returns a process exit code (see module docstring)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) == "version":
        print(f"ghostbench {__version__}")
        return 0
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except CorpusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
        # User-input failures (unreadable/invalid report or corpus
        # files, a report the writer refuses) are errors with a
        # message and exit 2, never a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 2
