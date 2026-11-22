"""GhostData CLI: pack, schema, check, mcp.

Exit codes: 0 on success (for ``check``, the pack verified), 1 when
``check`` finds a pack inconsistent with its manifest, and 2 when a
command cannot run at all (missing or unsupported input, or bad
arguments). Errors are printed to stderr prefixed with ``ghostdata:``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .core import DEFAULT_SAMPLE, analyze
from .pack import build_pack, check_pack
from .readers import DataError


def main(argv=None) -> int:
    """Run the ghostdata command line; return the process exit code.

    Exit codes: 0 on success (for ``check``, the pack verified), 1
    when ``check`` finds a pack inconsistent with its manifest, 2
    when a command cannot run at all (its error goes to stderr).
    """
    parser = argparse.ArgumentParser(
        prog="ghostdata",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Slice structured data files (CSV, TSV, JSON array, "
                    "top-level JSON object, JSONL) into a schema plus "
                    "bounded sample pack. The source file is only read, "
                    "never modified, and sensitive columns are redacted "
                    "in samples by default.",
        epilog="examples:\n"
               "  ghostdata schema data.csv\n"
               "  ghostdata pack data.csv -o data-pack\n"
               "  ghostdata pack events.jsonl -o events-pack --sample 100\n"
               "  ghostdata check data-pack\n"
               "  ghostdata mcp\n"
               "\n"
               "exit codes: 0 success (check: pack verified), 1 check "
               "failed, 2 the command could not run (reason on stderr).")
    parser.add_argument("--version", action="version",
                        version="ghostdata " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_pack = sub.add_parser(
        "pack", help="build a data pack",
        description="Build a pack from a data file: manifest.json "
                    "(schema, true row counts, redaction record, token "
                    "estimates), PROMPT.md, and a bounded sample file "
                    "under files/. The sample holds head, tail, and "
                    "evenly spaced middle rows.")
    p_pack.add_argument("file",
                        help="data file to slice (CSV, TSV, JSON array, "
                             "top-level JSON object, or JSONL)")
    p_pack.add_argument("-o", "--out", required=True,
                        help="pack output directory (created if needed)")
    p_pack.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                        help="total sample size in rows, an exact bound "
                             "(default %(default)s)")
    p_pack.add_argument("--no-redact", action="store_true",
                        help="disable sensitive-column redaction "
                             "(recorded in the manifest; use only on "
                             "files you own and trust)")
    p_pack.add_argument("--format",
                        choices=["csv", "tsv", "json", "json-object",
                                 "jsonl"],
                        default=None,
                        help="override format detection; plain json "
                             "dispatches on the top-level shape (array "
                             "streams, object is read as one record)")

    p_schema = sub.add_parser(
        "schema", help="print inferred schema as JSON",
        description="Print the inferred schema of a data file as JSON "
                    "on stdout: format, true row counts, and per-column "
                    "inferred types, null rates, distinct counts, and "
                    "ranges. Types are inferred, never declared. Writes "
                    "nothing to disk.")
    p_schema.add_argument("file",
                          help="data file to inspect (CSV, TSV, JSON "
                               "array, top-level JSON object, or JSONL)")
    p_schema.add_argument("--no-redact", action="store_true",
                          help="disable sensitive-column redaction "
                               "marking (by default redacted columns "
                               "are flagged and their ranges suppressed)")
    p_schema.add_argument("--format",
                          choices=["csv", "tsv", "json", "json-object",
                                   "jsonl"],
                          default=None,
                          help="override format detection; plain json "
                               "dispatches on the top-level shape (array "
                               "streams, object is read as one record)")

    p_check = sub.add_parser(
        "check", help="verify a pack against its manifest",
        description="Verify a pack built by the pack command: the "
                    "sample file's sha256 must match the manifest and "
                    "the row counts must be consistent (total = parsed "
                    "+ malformed). Prints a JSON result; exit code 0 "
                    "means ok, 1 means the pack did not verify.")
    p_check.add_argument("pack_dir",
                         help="pack directory containing manifest.json")

    sub.add_parser(
        "mcp", help="run the stdio MCP server",
        description="Run the stdio MCP server (local only, no "
                    "network). Tools: data_schema and data_pack. "
                    "Payloads carry schema and counts, capped in "
                    "size, and never include sample rows by default.")

    args = parser.parse_args(argv)
    try:
        if args.command == "pack":
            manifest = build_pack(
                args.file, args.out, sample_size=args.sample,
                redact=not args.no_redact, fmt=args.format)
            counts = manifest["counts"]
            print("GhostData pack: %s" % os.path.abspath(args.out))
            print("  format %s, rows parsed %d of %d (%d malformed)" % (
                manifest["source"]["format"], counts["rows_parsed"],
                counts["rows_total"], counts["rows_malformed"]))
            print("  sample %d rows, tokens sample %d vs full file %d "
                  "(estimates)" % (
                      manifest["sample"]["rows"],
                      manifest["tokens"]["sample_estimate"],
                      manifest["tokens"]["full_file_estimate"]))
            for col in manifest["redaction"]["columns"]:
                print("  redacted: %s (%s)" % (col["name"], col["reason"]))
            for col in manifest["redaction"].get("nested", []):
                print("  redacted (nested): %s (%s)"
                      % (col["name"], col["reason"]))
            if manifest["sample"].get("truncated"):
                print("  sample truncated to bounds (details in "
                      "manifest)")
            if not manifest["redaction"]["enabled"]:
                print("  redaction disabled by --no-redact (recorded "
                      "in manifest)")
            return 0
        if args.command == "schema":
            result = analyze(args.file, redact=not args.no_redact,
                             fmt=args.format)
            out = {
                "format": result["format"],
                "counts": result["counts"],
                "columns": result["schema"],
                "redacted_columns": result["redacted_columns"],
                "redacted_nested": result["redacted_nested"],
            }
            if result.get("structure") is not None:
                out["structure"] = result["structure"]
            print(json.dumps(out, indent=2))
            return 0
        if args.command == "check":
            result = check_pack(args.pack_dir)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.command == "mcp":
            from .mcp_server import serve
            serve()
            return 0
    except (DataError, ValueError, OSError) as exc:
        print("ghostdata: %s" % exc, file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
