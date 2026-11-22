"""GhostDocs command-line interface: ``scan`` / ``export`` / ``report`` / ``check``.

All commands run locally on a corpus folder (a folder of business
documents). Nothing is uploaded and no network call is made.

Quick reference (run from the GhostDocs folder)::

    PYTHONPATH=src python3 -m ghostdocs scan   <corpus>
    PYTHONPATH=src python3 -m ghostdocs export <corpus> -o <export-folder>
    PYTHONPATH=src python3 -m ghostdocs report <corpus> -o <report.html>
    PYTHONPATH=src python3 -m ghostdocs check  <export-folder>

Exit codes: 0 means success, 1 means the work was done but a check or
a ``--fit`` target failed, and 2 means the command could not run (for
example a missing corpus folder, an invalid ``.ghostdocs.json``, or a
bundle with no ``manifest.json``). See ``ghostdocs <command> --help``
for the options of each command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import __version__
from .export import export_corpus
from .profile import load_profile
from .report import write_report
from .scan import scan_corpus


def _load(args):
    """Load the profile for ``args.corpus`` and scan the corpus.

    Exits with code 2 (after printing the reason to stderr) when the
    corpus folder does not exist or its ``.ghostdocs.json`` is invalid.
    """
    corpus_path = Path(args.corpus)
    if not corpus_path.is_dir():
        print(f"error: corpus folder not found: {corpus_path}", file=sys.stderr)
        raise SystemExit(2)
    try:
        profile = load_profile(corpus_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    return scan_corpus(corpus_path, profile)


def cmd_scan(args) -> int:
    """Print a corpus inventory: sizes, duplicate clusters, hold-outs.

    With ``--json`` the full scan dictionary is printed instead of the
    short human-readable summary.
    """
    corpus = _load(args)
    data = corpus.to_dict()
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    s = data["summary"]
    print(f"Documents: {s['documents']}  Not covered: {s['coverage_gaps']}  "
          f"Held out: {s['held_out_documents']}")
    print(f"Estimated tokens (raw): {s['total_estimated_tokens']}  "
          f"duplicate waste: {s['wasted_estimated_tokens']}  "
          f"deduped: {s['deduped_estimated_tokens']}")
    print("\nHeat (largest first):")
    for d in data["documents"][:args.top]:
        print(f"  {d['tokens']:>8}  {d['heat_pct']:>5}%  {d['path']}"
              + ("  HELD OUT" if d["held_out"] else "")
              + (f"  flags={','.join(d['extraction_flags'])}" if d["extraction_flags"] else ""))
    if corpus.clusters:
        print("\nDuplicate clusters:")
        for c in corpus.clusters:
            print(f"  [{c.kind}] current={c.probable_current} ({c.current_reason}) "
                  f"stale={c.stale} waste={c.wasted_tokens}")
            for m in c.members:
                print(f"    - {m}")
    if corpus.not_covered:
        print("\nNot covered (named, never silently skipped):")
        for n in corpus.not_covered:
            print(f"  - {n.path}: {n.reason}")
    return 0


def cmd_export(args) -> int:
    """Write an export and print what went in, was held, or was skipped.

    Returns 1 when a ``--fit`` target was given and the bundle could
    not be fitted under it; the (partial) bundle is still written.
    """
    corpus = _load(args)
    result = export_corpus(corpus, Path(args.out), task=args.task, fit=args.fit,
                           shape=args.shape, allow_sensitive=args.allow_sensitive)
    print(f"Exported {result.sections_exported} sections to {result.out}")
    print(f"Exported estimated tokens: {result.total_tokens} "
          f"(corpus raw: {result.raw_tokens})")
    if result.held_out:
        print(f"Held out (sensitive): {', '.join(result.held_out)}")
    if result.superseded_skipped:
        print(f"Superseded skipped: {', '.join(result.superseded_skipped)}")
    if result.not_covered:
        print(f"Not covered: {', '.join(result.not_covered)}")
    if args.fit is not None and not result.fitted:
        print(f"WARNING: could not fit under {args.fit} tokens; bundle written anyway.",
              file=sys.stderr)
        return 1
    return 0


def cmd_report(args) -> int:
    """Write a single-file, offline HTML report for the corpus."""
    corpus = _load(args)
    out = write_report(corpus, Path(args.out))
    print(f"Report written: {out}")
    return 0


def cmd_check(args) -> int:
    """Validate an exported bundle against its ``manifest.json``.

    Checks that each exported file exists and matches its recorded
    SHA-256 hash, and that the chunk-pack token total equals the
    manifest total. Returns 0 when the bundle is OK, 1 on a mismatch,
    and 2 when there is no manifest to check against.
    """
    bundle = Path(args.bundle)
    manifest_path = bundle / "manifest.json"
    if not manifest_path.exists():
        print("error: no manifest.json in bundle", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # a corrupt bundle is a failed check with a message, not a traceback
        print(f"error: manifest.json is not readable JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        print("FAIL: manifest.json has no files list")
        return 1
    errors = []
    expected = set()
    for f in manifest["files"]:
        if not isinstance(f, dict) or not isinstance(f.get("path"), str) \
                or not isinstance(f.get("sha256"), str):
            errors.append("manifest file entry is missing path or sha256")
            continue
        expected.add(f["path"] + ".txt")
        target = bundle / "files" / (f["path"] + ".txt")
        if not target.exists():
            chunks = bundle / "chunks.jsonl"
            if not chunks.exists():
                errors.append(f"missing exported file for {f['path']}")
            continue
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != f["sha256"]:
            errors.append(f"hash mismatch for {f['path']}")
    files_dir = bundle / "files"
    if files_dir.is_dir():
        # a file the manifest does not list (e.g. left over from an earlier,
        # different export into the same folder) means the bundle on disk
        # is not the set the manifest describes
        for p in sorted(files_dir.rglob("*")):
            if p.is_file() and p.relative_to(files_dir).as_posix() not in expected:
                errors.append("file in bundle but not in manifest: "
                              f"{p.relative_to(files_dir).as_posix()}")
    chunk_path = bundle / "chunks.jsonl"
    if chunk_path.exists():
        chunk_total = 0
        chunks_ok = True
        try:
            lines = chunk_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"chunks.jsonl is not readable: {exc}")
            lines, chunks_ok = [], False
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                chunk_total += row["estimated_tokens"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                errors.append(f"malformed chunk line in chunks.jsonl: {exc}")
                chunks_ok = False
        totals = manifest.get("totals")
        expected_total = totals.get("chunk_estimated_tokens") \
            if isinstance(totals, dict) else None
        if chunks_ok:
            if expected_total is None:
                errors.append("manifest has no chunk total to compare against")
            elif chunk_total != expected_total:
                errors.append("chunk totals do not equal manifest chunk total")
    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        return 1
    print("Bundle OK: hashes and totals match manifest.")
    return 0


def main(argv=None) -> int:
    """Parse command-line arguments and run the chosen subcommand."""
    parser = argparse.ArgumentParser(
        prog="ghostdocs",
        description=(
            "GhostDocs: prepare local business documents for an AI "
            "assistant. Scans a corpus folder, finds duplicates, holds "
            "back pages with sensitive shapes, and exports a verified, "
            "manifest-backed set. Local only: nothing is uploaded."
        ),
        epilog=(
            "examples:\n"
            "  ghostdocs scan path/to/documents\n"
            "  ghostdocs scan path/to/documents --json\n"
            "  ghostdocs export path/to/documents -o path/to/export\n"
            "  ghostdocs export path/to/documents -o path/to/export "
            "--task \"returns policy\" --fit 4000\n"
            "  ghostdocs report path/to/documents -o report.html\n"
            "  ghostdocs check path/to/export\n"
            "\n"
            "Run 'ghostdocs <command> --help' for that command's options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"ghostdocs {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "scan",
        help="scan a corpus folder (inventory, sizes, duplicates, hold-outs)",
        description="Scan a corpus folder and print its inventory: document "
                    "sizes in estimated tokens, duplicate clusters with a "
                    "probable current version, documents held out for "
                    "sensitive shapes, and files that are not covered.",
    )
    p.add_argument("corpus", help="path to the folder of documents to scan")
    p.add_argument("--json", action="store_true",
                   help="print the full scan as JSON instead of the short summary")
    p.add_argument("--top", type=int, default=20, metavar="N",
                   help="how many documents to show in the heat list, largest "
                        "first (default: 20)")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser(
        "export",
        help="export an agent bundle and/or chunk pack",
        description="Export a deduped set from a corpus folder. By default "
                    "both shapes are written: an agent bundle (PROMPT.md, "
                    "files/, manifest.json) and a chunk pack (chunks.jsonl). "
                    "Superseded duplicates and sensitive-held documents stay "
                    "out unless the profile or flags say otherwise.",
    )
    p.add_argument("corpus", help="path to the folder of documents to export from")
    p.add_argument("-o", "--out", required=True, metavar="FOLDER",
                   help="folder to write the export into (created if needed)")
    p.add_argument("--task", default=None, metavar="TEXT",
                   help="optional topic or question; only sections relevant "
                        "to it are exported (TF-IDF selection, no model call)")
    p.add_argument("--fit", type=int, default=None, metavar="TOKENS",
                   help="optional estimated-token budget; non-authoritative "
                        "documents are downgraded to headings, then the "
                        "lowest-priority sections dropped, to try to fit. "
                        "If it still does not fit, the bundle is written "
                        "anyway and the command exits 1")
    p.add_argument("--shape", choices=["bundle", "chunks", "both"], default="both",
                   help="what to write: the agent bundle, the chunk pack, "
                        "or both (default: both)")
    p.add_argument("--allow-sensitive", action="store_true",
                   help="include sensitive-held documents (explicit opt-in, recorded)")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser(
        "report",
        help="write a single-file HTML corpus report",
        description="Write a single-file HTML report for a corpus folder. "
                    "The report is plain-words first, works offline in any "
                    "browser, and names held-out and not-covered files "
                    "without ever showing sensitive values.",
    )
    p.add_argument("corpus", help="path to the folder of documents to report on")
    p.add_argument("-o", "--out", required=True, metavar="FILE",
                   help="path of the HTML file to write, for example report.html")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser(
        "check",
        help="validate an exported bundle against its manifest",
        description="Validate an exported bundle against its manifest.json: "
                    "exported files must exist and match their recorded "
                    "hashes, and chunk totals must match the manifest.",
    )
    p.add_argument("bundle", help="path to an export folder made by 'ghostdocs export'")
    p.set_defaults(fn=cmd_check)

    args = parser.parse_args(argv)
    if getattr(args, "top", None) is not None and args.top < 0:
        parser.error("--top must be >= 0")
    if getattr(args, "fit", None) is not None and args.fit < 0:
        parser.error("--fit must be >= 0")
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
