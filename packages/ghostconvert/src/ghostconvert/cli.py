"""GhostConvert CLI: convert | inspect | targets | verify.

Examples:
    ghostconvert inspect path/to/.claude_context
    ghostconvert convert path/to/.claude_context --to agents -o out/agents
    ghostconvert convert path/to/.claude_context --to all -o out/all
    ghostconvert targets

Exit codes: 0 = done (losses recorded in LOSSES.md are not failures),
1 = verify found a converted output that does not match its bundle,
2 = bad bundle or bad arguments, source bundle never modified.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from . import __version__
from .bundle import BundleError, load_bundle
from .convert import TARGETS, TARGET_ARTIFACTS, convert
from .verify import verify_target


def _cmd_targets(_args) -> int:
    """Print the four conversion targets and the artifact each writes."""
    print("GhostConvert targets:")
    for t in TARGETS:
        print(f"  {t:8} -> {TARGET_ARTIFACTS[t]}")
    print("Every target also writes LOSSES.md next to its artifact(s).")
    return 0


def _cmd_inspect(args) -> int:
    """Print a bundle summary (project, file census by slice mode,
    token totals, emptied/missing/skipped files) and write nothing."""
    try:
        bundle = load_bundle(args.bundle)
    except BundleError as exc:
        print(f"ghostconvert: {exc}", file=sys.stderr)
        return 2
    m = bundle.manifest
    modes = Counter(f.mode for f in bundle.files)
    print(f"Bundle: {bundle.root}")
    print(f"Project: {bundle.project_name}")
    print(f"Sliced by: {m.get('tool', 'unknown')} {m.get('version', '')} "
          f"(preset: {m.get('preset', 'unknown')})")
    with_bodies = sum(1 for f in bundle.included if f.body is not None)
    emptied_n = sum(1 for f in bundle.included if f.emptied_by_design)
    missing_n = sum(1 for f in bundle.included if f.missing_body)
    census = [f"{with_bodies} with bodies"]
    if emptied_n:
        census.append(f"{emptied_n} emptied by GhostSlice")
    if missing_n:
        census.append(f"{missing_n} missing bodies")
    census.append(f"{len(bundle.excluded)} excluded")
    print(f"Files: {len(bundle.files)} ({', '.join(census)})")
    for mode, n in sorted(modes.items()):
        note = ""
        if any(f.unknown_mode for f in bundle.files if f.mode == mode):
            note = " (unrecognized mode, carried verbatim)"
        print(f"  mode {mode}: {n}{note}")
    total_sliced = m.get("total_sliced_tokens")
    total_original = m.get("total_original_tokens")
    if total_sliced is None or total_original is None:
        print("Totals: not recorded in the manifest")
    else:
        print(f"Totals: {total_sliced} sliced of "
              f"{total_original} original estimated tokens "
              f"(method: {m.get('token_method', 'unknown')})")
    unknown_modes = sorted({f.mode for f in bundle.files if f.unknown_mode})
    if unknown_modes:
        print(f"Unrecognized mode(s): {', '.join(unknown_modes)} "
              f"(not a mode GhostConvert knows; labels are carried "
              f"verbatim, never relabelled)")
    emptied = [f for f in bundle.included if f.emptied_by_design]
    if emptied:
        print("Emptied by GhostSlice (no body by design): "
              + ", ".join(f"{f.path} (mode: {f.mode})" for f in emptied))
    missing = [f.path for f in bundle.included if f.missing_body]
    if missing:
        print(f"Missing bodies: {', '.join(missing)}")
    if bundle.skipped_paths:
        print(f"Skipped (paths escape bundle): {', '.join(bundle.skipped_paths)}")
    return 0


def _write_artifacts(outdir: Path, artifacts: dict[str, str],
                     force: bool) -> list[str] | None:
    """Write all artifacts or none. Returns written paths, or None after
    printing the collision that blocked the run."""
    collisions = [str(outdir / rel) for rel in artifacts
                  if (outdir / rel).exists()]
    if collisions and not force:
        print("ghostconvert: refusing to overwrite existing file(s) "
              "(use --force to replace):", file=sys.stderr)
        for c in collisions:
            print(f"  {c}", file=sys.stderr)
        return None
    written = []
    for rel, text in artifacts.items():
        dest = outdir / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"ghostconvert: could not write {dest}: {exc}",
                  file=sys.stderr)
            return None
        written.append(rel)
    return written


def _cmd_convert(args) -> int:
    """Convert a bundle to one target (or all four, one subdirectory
    per target), refusing output inside the bundle and refusing to
    overwrite existing artifacts without --force."""
    try:
        bundle = load_bundle(args.bundle)
    except BundleError as exc:
        print(f"ghostconvert: {exc}", file=sys.stderr)
        return 2
    out_base = Path(args.out).resolve()
    if out_base == bundle.root or bundle.root in out_base.parents:
        print("ghostconvert: output directory must not be the bundle "
              "directory or inside it; the source bundle is read-only.",
              file=sys.stderr)
        return 2
    targets = list(TARGETS) if args.to == "all" else [args.to]
    # Plan every target before writing any of them: with --to all, a
    # collision (or any other refusal) in a later target must not leave
    # earlier targets already written behind a failed exit code.
    plans = []
    for target in targets:
        outdir = out_base / target if args.to == "all" else out_base
        artifacts, losses = convert(bundle, target)
        plans.append((target, outdir, artifacts, losses))
    if not args.force:
        collisions = [str(outdir / rel)
                      for _t, outdir, artifacts, _l in plans
                      for rel in artifacts if (outdir / rel).exists()]
        if collisions:
            print("ghostconvert: refusing to overwrite existing file(s) "
                  "(use --force to replace):", file=sys.stderr)
            for c in collisions:
                print(f"  {c}", file=sys.stderr)
            return 2
    for target, outdir, artifacts, losses in plans:
        written = _write_artifacts(outdir, artifacts, args.force)
        if written is None:
            return 2
        bodies = sum(1 for f in bundle.included if f.body is not None)
        print(f"[{target}] {bodies} file(s) converted -> {outdir}")
        for rel in written:
            print(f"  wrote {rel}")
        if losses:
            print(f"  losses: {len(losses)} named in LOSSES.md "
                  f"({', '.join(name for name, _ in losses)})")
        else:
            print("  losses: none recorded")
    return 0


def _cmd_verify(args) -> int:
    try:
        bundle = load_bundle(args.bundle)
    except BundleError as exc:
        print(f"ghostconvert: {exc}", file=sys.stderr)
        return 2
    out_base = Path(args.output)
    targets = list(TARGETS) if args.to == "all" else [args.to]
    failed = False
    for target in targets:
        outdir = out_base / target if args.to == "all" else out_base
        issues = verify_target(bundle, target, outdir)
        if issues:
            failed = True
            print(f"[{target}] FAILED: {len(issues)} issue(s) in {outdir}")
            for issue in issues:
                print(f"  {issue}")
        else:
            n_artifacts = len(convert(bundle, target)[0])
            bodies = sum(1 for f in bundle.included if f.body is not None)
            print(f"[{target}] OK: {n_artifacts} artifact(s) match a fresh "
                  f"conversion of this bundle ({bodies} file(s) with "
                  f"bodies, manifest order, mode labels, bodies verbatim, "
                  f"LOSSES.md current)")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the chosen subcommand.

    Returns the process exit code: 0 on success, 1 when verify
    finds an output that does not match its bundle, 2 on a bad
    bundle or bad arguments (argparse itself also exits 2 on bad
    usage).
    """
    parser = argparse.ArgumentParser(
        prog="ghostconvert",
        description="Convert a GhostSlice bundle (a .claude_context "
                    "directory with manifest.json, PROMPT.md, and "
                    "files/) into other agent instruction formats, "
                    "naming what each format loses in LOSSES.md. The "
                    "source bundle is read only, never modified.",
        epilog="examples:\n"
               "  ghostconvert inspect path/to/.claude_context\n"
               "  ghostconvert convert path/to/.claude_context "
               "--to agents -o out/agents\n"
               "  ghostconvert convert path/to/.claude_context "
               "--to all -o out/all\n"
               "  ghostconvert targets\n"
               "\n"
               "exit codes: 0 = converted (losses, if any, are listed "
               "in LOSSES.md and are not failures); 1 = verify found "
               "an output that does not match its bundle; 2 = bad "
               "bundle or bad arguments.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version",
                        version=f"ghostconvert {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_targets = sub.add_parser(
        "targets",
        help="list conversion targets",
        description="List the four conversion targets and the "
                    "artifact path each one writes. Every target also "
                    "writes a LOSSES.md next to its artifact(s).")
    p_targets.set_defaults(func=_cmd_targets)

    p_inspect = sub.add_parser(
        "inspect",
        help="summarise a bundle, write nothing",
        description="Summarise a GhostSlice bundle: project, file "
                    "census by slice mode, token totals, and any "
                    "emptied, missing, or skipped files. Writes "
                    "nothing and never modifies the bundle.")
    p_inspect.add_argument(
        "bundle",
        help="path to the GhostSlice bundle directory "
             "(the folder containing manifest.json)")
    p_inspect.set_defaults(func=_cmd_inspect)

    p_convert = sub.add_parser(
        "convert",
        help="convert a bundle to a target format",
        description="Convert a GhostSlice bundle to a target format. "
                    "The output also contains LOSSES.md, naming "
                    "everything the target format could not carry "
                    "from the manifest. Nothing is written into the "
                    "source bundle.",
        epilog="The output directory must not be the bundle directory "
               "or inside it. Existing artifacts are overwritten only "
               "with --force; without it the run refuses, names the "
               "collision, and writes nothing.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p_convert.add_argument(
        "bundle",
        help="path to the GhostSlice bundle directory "
             "(the folder containing manifest.json)")
    p_convert.add_argument("--to", required=True,
                           choices=[*TARGETS, "all"],
                           metavar="TARGET",
                           help="target format: agents, cursor, copilot, "
                                "or generic (all = every target, one "
                                "subdirectory per target)")
    p_convert.add_argument("-o", "--out", required=True,
                           help="output directory (created if needed; "
                                "must not be the bundle or inside it)")
    p_convert.add_argument("--force", action="store_true",
                           help="overwrite artifact files that already "
                                "exist in the output directory")
    p_convert.set_defaults(func=_cmd_convert)

    p_verify = sub.add_parser(
        "verify",
        help="check a converted output against its bundle, write nothing")
    p_verify.add_argument("bundle", help="path to the GhostSlice bundle directory")
    p_verify.add_argument("output",
                          help="converted output directory (for --to all, "
                               "the directory holding one subdirectory per target)")
    p_verify.add_argument("--to", required=True,
                          choices=[*TARGETS, "all"],
                          help="target format the output was converted to")
    p_verify.set_defaults(func=_cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
