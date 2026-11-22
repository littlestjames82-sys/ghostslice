"""GhostLogs command line: `pack` and `doctor`.

`pack` builds an incident pack (INCIDENT.md + manifest.json) from
one local log file; `doctor` reports the version, the token
estimator in use, and the pattern set that would be loaded, which
makes it the way to validate a pattern or config file before a run.

Exit codes: 0 = pack written within budget (or doctor clean),
1 = pack written but over budget, 2 = could not run (missing
input, bad pattern file, bad config). A pack is never written on a
2. Nothing here touches the network or modifies the source log.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analyze import analyze
from .pack import build_pack
from .patterns import (compile_cli_patterns, default_patterns,
                       load_pattern_file)
from .tokens import METHOD, SOURCE

CONFIG_KEYS = {"budget", "window_before", "window_after",
               "patterns_file", "no_redact"}


def _load_config(path) -> dict:
    """Read and validate a JSON config file.

    The top level must be an object using only CONFIG_KEYS; an
    unknown key is an error, not a warning. Raises ValueError with a
    message naming the file (and the offending keys) on any problem.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"config {path}: cannot read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"config {path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"config {path}: top level must be an object")
    unknown = sorted(set(data) - CONFIG_KEYS)
    if unknown:
        raise ValueError(
            f"config {path}: unknown keys {unknown}; "
            f"allowed keys are {sorted(CONFIG_KEYS)}")
    # Type-check values: a wrong-typed value must fail loudly here
    # (exit 2), not crash later with a traceback or, worse, coerce
    # silently. The dangerous case was no_redact: the string "false"
    # is truthy, so bool() coercion turned redaction OFF for a
    # config that said the opposite.
    for key in ("budget", "window_before", "window_after"):
        if key in data and (isinstance(data[key], bool)
                            or not isinstance(data[key], int)):
            raise ValueError(
                f"config {path}: {key} must be an integer, "
                f"got {type(data[key]).__name__}")
    if "no_redact" in data and not isinstance(data["no_redact"], bool):
        raise ValueError(
            f"config {path}: no_redact must be true or false, "
            f"got {type(data['no_redact']).__name__}")
    if "patterns_file" in data \
            and not isinstance(data["patterns_file"], str):
        raise ValueError(
            f"config {path}: patterns_file must be a string path")
    return data


def _resolve_settings(args) -> dict:
    """Merge CLI flags, config file, and defaults into one settings dict.

    Precedence per setting: CLI value first, then the config file,
    then the built-in default. Patterns are the exception: built-in,
    pattern-file, and --pattern patterns are combined, in that order.
    """
    config = _load_config(args.config) if getattr(args, "config", None) else {}

    def pick(cli_value, key, default):
        if cli_value is not None:
            return cli_value
        if key in config:
            return config[key]
        return default

    settings = {
        "budget": pick(args.budget, "budget", 8000),
        "window_before": pick(args.window_before, "window_before", 3),
        "window_after": pick(args.window_after, "window_after", 5),
        "no_redact": bool(pick(True if args.no_redact else None,
                               "no_redact", False)),
    }
    patterns_file = getattr(args, "patterns", None) or config.get("patterns_file")
    patterns = default_patterns()
    if patterns_file:
        patterns = patterns + load_pattern_file(patterns_file)
    patterns = patterns + compile_cli_patterns(
        getattr(args, "pattern", None))
    settings["patterns"] = patterns
    return settings


def _cmd_pack(args) -> int:
    """Run `pack`: analyse the log, build the pack, print the summary.

    Returns 0 when the pack fits its budget, 1 when it was written
    but is over budget, and 2 when the run could not start.
    """
    source = Path(args.logfile)
    if not source.is_file():
        print(f"ghostlogs: no such log file: {source}", file=sys.stderr)
        return 2
    try:
        settings = _resolve_settings(args)
    except ValueError as exc:
        print(f"ghostlogs: {exc}", file=sys.stderr)
        return 2
    if settings["budget"] <= 0 or settings["window_before"] < 0 \
            or settings["window_after"] < 0:
        print("ghostlogs: budget must be positive and window sizes "
              "must be zero or more", file=sys.stderr)
        return 2
    # Fail cleanly (exit 2, no traceback) when the pack directory
    # cannot be created - for example when the output path is an
    # existing file - before doing the analysis work.
    try:
        Path(args.output).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ghostlogs: cannot create pack directory "
              f"{args.output}: {exc}", file=sys.stderr)
        return 2
    try:
        analysis = analyze(source, settings["patterns"],
                           window_before=settings["window_before"],
                           window_after=settings["window_after"])
        result = build_pack(analysis, args.output, settings["budget"],
                            settings["patterns"],
                            redact=not settings["no_redact"])
    except OSError as exc:
        print(f"ghostlogs: cannot build pack: {exc}", file=sys.stderr)
        return 2
    m = result.manifest
    c = m["counts"]
    print(f"Packed {source} -> {result.out_dir}")
    print(f"  lines {c['total_lines']} = kept {c['kept']} + collapsed "
          f"{c['collapsed']} + dropped {c['dropped']} "
          f"(reconciles: {c['reconciles']})")
    print(f"  windows: {m['windows']['emitted']} emitted of "
          f"{m['windows']['matched']} matched; duplicate groups: "
          f"{m['duplicates']['emitted_groups']} emitted of "
          f"{m['duplicates']['groups']}")
    s = m["summary"]
    print(f"  overview: {s['matched_lines']} matched lines "
          f"(by severity {s['by_severity']}); "
          f"{s['timeline']['buckets']} hour buckets")
    print(f"  pack estimate {m['pack_estimated_tokens']} tokens "
          f"against budget {m['budget_tokens']} "
          f"(estimator: {METHOD})")
    print(f"  budget tier: {m['budget_tier']} - "
          f"{m['budget_tier_meaning']}")
    if m["redaction"]["enabled"]:
        print(f"  redactions: {m['redaction']['total']} "
              f"{m['redaction']['counts']}")
    else:
        print("  WARNING: redaction disabled for this run "
              "(--no-redact); recorded in the manifest.")
    if result.over_budget:
        print("  OVER BUDGET: mandatory content alone exceeded the "
              "budget; pack written and marked over_budget.")
        return 1
    return 0


def _cmd_doctor(args) -> int:
    """Run `doctor`: print version, estimator, and every loaded pattern.

    Loading the settings is the validation: a bad pattern or config
    file returns 2 here instead of failing partway through a pack.
    """
    try:
        settings = _resolve_settings(args)
    except ValueError as exc:
        print(f"ghostlogs: {exc}", file=sys.stderr)
        return 2
    print(f"ghostlogs {__version__}")
    print(f"estimator: {METHOD} (source: {SOURCE})")
    print(f"patterns loaded: {len(settings['patterns'])}")
    for p in settings["patterns"]:
        print(f"  {p.id} (severity {p.severity}, kind {p.kind}): "
              f"{p.regex.pattern}")
    print("source handling: local files only, read line by line, "
          "never modified")
    return 0


def main(argv=None) -> int:
    """Entry point. Parses argv (default: sys.argv) and returns an exit code.

    Exit codes: 0 = ok, 1 = pack written but over budget,
    2 = could not run. See the module docstring for the full contract.
    """
    parser = argparse.ArgumentParser(
        prog="ghostlogs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Slice a large local log file into a "
                    "token-budgeted incident pack (INCIDENT.md + "
                    "manifest.json). The pack is evidence, not a "
                    "diagnosis. Source logs are never modified.",
        epilog="examples:\n"
               "  ghostlogs pack app.log -o incident-pack\n"
               "  ghostlogs pack app.log -o incident-pack --budget 4000\n"
               "  ghostlogs doctor\n"
               "\n"
               "exit codes:\n"
               "  0  pack written within budget (or doctor clean)\n"
               "  1  pack written but over budget; pack and manifest say so\n"
               "  2  could not run (missing input, bad pattern or config "
               "file);\n"
               "     no pack is written")
    parser.add_argument("--version", action="version",
                        version=f"ghostlogs {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pack = sub.add_parser(
        "pack", help="build an incident pack from a log file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Build an incident pack from one local log file: "
                    "error windows, duplicate lines shown once with "
                    "exact counts, and timeline anchors, fitted to a "
                    "token budget. Line counts in the pack reconcile "
                    "exactly, and secret-shaped literals are redacted "
                    "by default.",
        epilog="examples:\n"
               "  ghostlogs pack app.log -o incident-pack\n"
               "  ghostlogs pack app.log -o incident-pack --budget 4000 "
               "--window-after 10\n"
               "  ghostlogs pack app.log -o incident-pack "
               "--patterns extra-patterns.txt --pattern 'connection refused'\n"
               "\n"
               "A value given here wins over --config, which wins over "
               "the\n"
               "default shown in each option's help.")
    p_pack.add_argument("logfile",
                        help="path to the local log file (read only, "
                             "never modified)")
    p_pack.add_argument("-o", "--output", required=True,
                        help="pack output directory (created if missing); "
                             "receives INCIDENT.md and manifest.json")
    p_pack.add_argument("--budget", type=int, default=None,
                        help="token budget for the pack; must be positive "
                             "(default 8000)")
    p_pack.add_argument("--window-before", type=int, default=None,
                        help="context lines before a match; zero or more "
                             "(default 3)")
    p_pack.add_argument("--window-after", type=int, default=None,
                        help="context lines after a match; zero or more "
                             "(default 5)")
    p_pack.add_argument("--patterns", default=None,
                        help="file of extra patterns, one per line: "
                             "id = regex, or a bare regex; blank lines "
                             "and # comments are ignored")
    p_pack.add_argument("--pattern", action="append", default=None,
                        help="one extra regex; may be repeated. Custom "
                             "patterns are severity 2")
    p_pack.add_argument("--config", default=None,
                        help="JSON config file (keys: budget, "
                             "window_before, window_after, "
                             "patterns_file, no_redact); unknown keys "
                             "are an error")
    p_pack.add_argument("--no-redact", action="store_true",
                        help="disable secret-shape redaction for this run "
                             "(for local debugging; recorded in the "
                             "manifest)")
    p_pack.set_defaults(func=_cmd_pack)

    p_doc = sub.add_parser(
        "doctor", help="report estimator, patterns, version",
        description="Report the version, the token estimator in use, "
                    "and every pattern that would be loaded. Use the "
                    "options below to validate a pattern or config "
                    "file before a pack run: a bad one fails here "
                    "with exit code 2.")
    p_doc.add_argument("--patterns", default=None,
                       help="also load and validate this pattern file")
    p_doc.add_argument("--pattern", action="append", default=None,
                       help="one extra regex to validate; may be repeated")
    p_doc.add_argument("--config", default=None,
                       help="also load and validate this config file")
    p_doc.set_defaults(func=_cmd_doctor, budget=None, window_before=None,
                    window_after=None, no_redact=False)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
