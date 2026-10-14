"""Watch mode: poll a project, report token deltas, optionally re-export.

Stdlib polling only (no watchdog dependency). The watcher snapshots the
scanner-visible files (relative path -> (mtime_ns, size, estimated
tokens)) every `interval` seconds. A change is only acted on once the
snapshot has stayed identical for the debounce window (default: the
larger of 1 second and 2 poll cycles), so a burst of writes from an
editor or a build coalesces into a single settled event.

Loop-proofing: the bundle output directory (when it lives inside the
project) is excluded from the watcher's own scan/snapshot view and
from the contents of watch-written bundles (via an augmented export
profile), and the savings ledger `.ghostslice-history.jsonl` is
already scanner-ignored, so the watcher's own exports can never
trigger further events or ingest a previous bundle. Plain one-shot
scans/exports can still see a previous bundle under a custom
in-project name; prefer the default `.claude_context` name (a
scanner-ignored directory) or a path outside the project. A warning
is printed in that case.

With `export=True` a bundle is written once at startup and again after
every settled change, reusing exporter.build_bundle (profile, preset,
--fit, --exclude-secrets and --redact behave exactly as in
`ghostslice export`).
Each settled export appends at most one savings-ledger record, because
build_bundle appends exactly one record per call; the initial export
also appends one. A failed fit or an invalid bundle is reported but
does not stop the watcher.

The project profile (`.ghostslice.json`) is loaded once at startup;
edits to it are seen as ordinary file-change events but only take
effect on the next watch run.

Ctrl-C exits cleanly (exit code 0) after printing a session summary.
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace as _dc_replace
from pathlib import Path

from .exporter import build_bundle, validate_bundle
from .profile import Profile
from .textio import read_text as _gs_read_text
from .scanner import DEFAULT_IGNORE_DIRS, ScanResult, scan

LEDGER_NAME = ".ghostslice-history.jsonl"


def snapshot_of(result: ScanResult, exclude_prefix: str | None = None) -> dict[str, tuple[int, int, int]]:
    """path -> (mtime_ns, size, estimated tokens) for the visible files.

    Files under `exclude_prefix` (the bundle output dir, posix rel path)
    and the savings ledger are skipped: the watcher must never react to
    its own writes.
    """
    snap: dict[str, tuple[int, int, int]] = {}
    for entry in result.files:
        rel = entry.path
        if rel == LEDGER_NAME:
            continue
        if exclude_prefix and (rel == exclude_prefix or rel.startswith(exclude_prefix + "/")):
            continue
        try:
            mtime_ns = Path(entry.abspath).stat().st_mtime_ns
        except OSError:
            # Vanished between scan and stat; keep a sentinel so the next
            # poll reports it as removed instead of crashing the watch.
            mtime_ns = 0
        snap[rel] = (mtime_ns, entry.size, entry.tokens)
    return snap


def visible_files(result: ScanResult, exclude_prefix: str | None = None) -> list:
    return [e for e in result.files
            if e.path != LEDGER_NAME
            and not (exclude_prefix and (e.path == exclude_prefix
                                         or e.path.startswith(exclude_prefix + "/")))]


def diff_snapshots(old: dict, new: dict) -> tuple[list[str], list[str], list[str]]:
    """(added, removed, changed) relative paths, each sorted."""
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(p for p in set(old) & set(new) if old[p] != new[p])
    return added, removed, changed


def _tokens_of(result: ScanResult, exclude_prefix: str | None = None) -> int:
    return sum(e.tokens for e in visible_files(result, exclude_prefix))


def _bundle_rel(root: Path, out: Path) -> str | None:
    """Bundle dir as a posix path relative to root, or None if outside.

    Returns "" when out IS the project root (relative path "."), which
    the caller rejects: exporting a bundle into the project root would
    make every export ingest the previous bundle and grow without
    bound."""
    try:
        rel = out.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    if not rel.parts:
        return ""
    return rel.as_posix()


def run_watch(root: str | Path,
              out: str | Path | None = None,
              export: bool = False,
              interval: float = 1.0,
              debounce: float | None = None,
              once: bool = False,
              max_events: int | None = None,
              fit: int | None = None,
              preset: str | None = None,
              default_mode: str | None = None,
              exclude_secrets: bool = False,
              redact: bool | None = None,
              auto_shrink: bool = False,
              profile=None,
              scan_fn=None,
              sleep=time.sleep,
              clock=time.monotonic,
              stream=None) -> dict:
    """Run the watch loop. Returns a summary dict.

    Summary keys: duration_s, events, exports, polls, initial_files,
    initial_tokens (estimated). KeyboardInterrupt is caught and turned
    into a normal return so the CLI exits 0.

    `scan_fn`, `sleep`, and `clock` are injectable for tests: tests drive
    the loop deterministically by mutating the project inside a fake
    `sleep` instead of waiting in real time.
    """
    stream = stream if stream is not None else sys.stdout
    root = Path(root)
    if not root.exists():
        # A typo'd path is a usage error, not a watchable state; the
        # soft per-poll failure handling below is for a project that
        # disappears MID-watch (audit #2, G1).
        raise FileNotFoundError(str(root))
    if export and out is None:
        out = root / ".claude_context"
    bundle_rel: str | None = None
    if out is not None:
        out = Path(out)
        bundle_rel = _bundle_rel(root, out)
        if bundle_rel == "":
            raise ValueError("watch: bundle output directory cannot be the project root itself")
    if debounce is None:
        debounce = max(1.0, 2.0 * interval)
    # Exports must never ingest a previous bundle: when the bundle dir
    # is inside the project, hand build_bundle a copy of the profile
    # whose ignore list also excludes the bundle dir. One-shot export
    # is untouched; this is watch-only (audit F3).
    export_profile = profile
    if bundle_rel:
        base = profile if profile is not None else Profile()
        export_profile = _dc_replace(
            base,
            ignore=[*base.ignore, f"{bundle_rel}/**"],
            path=base.path or "(watch)")
    if scan_fn is None:
        matcher = profile.is_ignored if (profile is not None and profile.path) else None

        def scan_fn(p):  # noqa: F811 - intentional default scanner
            return scan(p, ignore_matcher=matcher)

    def say(msg: str) -> None:
        print(msg, file=stream, flush=True)

    def poll() -> ScanResult | None:
        try:
            return scan_fn(root)
        except (OSError, ValueError) as exc:
            # Project deleted mid-watch or a transient read failure:
            # warn and skip this poll rather than killing the session.
            say(f"[watch] scan failed ({exc}); keeping the last snapshot")
            return None

    exports = 0

    def do_export() -> None:
        nonlocal exports
        # A failed export (unwritable bundle dir, disk full, bad mode)
        # is reported and the watcher keeps watching; the next settled
        # change retries (audit F2).
        try:
            manifest = build_bundle(root, out, profile=export_profile, preset=preset,
                                    default_mode=default_mode,
                                    exclude_secrets=exclude_secrets,
                                    redact=redact,
                                    auto_shrink=True if auto_shrink else None,
                                    fit=fit)
        except (OSError, ValueError) as exc:
            say(f"[watch] export failed ({exc}); continuing to watch")
            return
        exports += 1
        try:
            check = validate_bundle(out)
            valid_note = ("validation OK" if check["ok"]
                          else f"VALIDATION FAILED: {'; '.join(check['errors'])}")
        except (OSError, ValueError, KeyError) as exc:
            valid_note = f"VALIDATION ERROR: {exc}"
        fit_note = ""
        if manifest.get("fit") is not None:
            fit_note = (f", fit target {manifest['fit']['fit_tokens']:,}: "
                        f"{'fitted' if manifest['fit']['fitted'] else 'COULD NOT FIT'}")
        redact_note = ""
        if manifest.get("redaction"):
            redact_note = (f", redacted "
                           f"{manifest['redaction']['values_redacted']} secret value(s)")
        plugin_note = ""
        if manifest.get("plugin_errors"):
            plugin_note = (f", WARNING: {len(manifest['plugin_errors'])} "
                           "plugin failure(s); those files shipped full text "
                           "(see the bundle's plugin_errors)")
        say(f"[watch] bundle rewritten: {out} "
            f"({manifest['total_sliced_tokens']:,} estimated sliced tokens, {valid_note}{fit_note}{redact_note}{plugin_note})")

    start = clock()
    events = 0
    polls = 0
    initial = poll()
    if initial is None:
        say("[watch] initial scan failed; nothing to watch")
        return {"duration_s": 0.0, "events": 0, "exports": 0, "polls": 0,
                "initial_files": 0, "initial_tokens": 0}
    initial_files = len(visible_files(initial, bundle_rel))
    initial_tokens = _tokens_of(initial, bundle_rel)
    say(f"[watch] watching {initial.root}: {initial_files} file(s), "
        f"{initial_tokens:,} estimated tokens (poll {interval:g}s, debounce {debounce:g}s)")
    if bundle_rel and not any(seg in DEFAULT_IGNORE_DIRS for seg in bundle_rel.split("/")):
        say(f"[watch] note: bundle dir '{bundle_rel}' is inside the project and is excluded "
            "from change detection; for a bundle that plain scans also ignore, use the "
            "default .claude_context name or a path outside the project")
    if not exclude_secrets:
        from .secrets_scan import scan_scan_result
        findings = scan_scan_result(initial)
        if findings:
            print(f"[watch] WARNING: possible secrets detected ({len(findings)} finding(s), values redacted):",
                  file=sys.stderr)
            for f in findings[:20]:
                print(f"  {f['path']}:{f['line']}  {f['type']}  ({f['redacted']})", file=sys.stderr)
    settled_result = initial
    settled_snap = snapshot_of(initial, bundle_rel)

    def settle(new_result: ScanResult) -> None:
        nonlocal events, settled_result, settled_snap
        new_snap = snapshot_of(new_result, bundle_rel)
        added, removed, changed = diff_snapshots(settled_snap, new_snap)
        before = _tokens_of(settled_result, bundle_rel)
        after = _tokens_of(new_result, bundle_rel)
        events += 1
        say(f"[watch] change #{events}: +{len(added)} added, -{len(removed)} removed, "
            f"~{len(changed)} changed; estimated tokens {before:,} -> {after:,} ({after - before:+,})")
        for label, paths in (("+", added), ("-", removed), ("~", changed)):
            for p in paths[:10]:
                say(f"  {label} {p}")
            if len(paths) > 10:
                say(f"  ... and {len(paths) - 10} more")
        if not exclude_secrets and (added or changed):
            from .secrets_scan import scan_text
            findings = []
            by_path = {e.path: e for e in new_result.files}
            for p in added + changed:
                entry = by_path.get(p)
                if entry is None:
                    continue
                try:
                    text = _gs_read_text(entry.abspath)
                except OSError:
                    continue
                findings.extend(scan_text(p, text))
            if findings:
                print(f"[watch] WARNING: possible secrets in changed files "
                      f"({len(findings)} finding(s), values redacted):", file=sys.stderr)
                for f in findings[:20]:
                    print(f"  {f['path']}:{f['line']}  {f['type']}  ({f['redacted']})", file=sys.stderr)
        settled_result = new_result
        settled_snap = new_snap
        if export:
            do_export()

    try:
        if export:
            do_export()
        if once:
            sleep(interval)
            polls += 1
            cur = poll()
            if cur is not None and snapshot_of(cur, bundle_rel) != settled_snap:
                settle(cur)
        else:
            pending_snap: dict | None = None
            pending_result: ScanResult | None = None
            pending_since = 0.0
            while True:
                if max_events is not None and events >= max_events:
                    break
                sleep(interval)
                polls += 1
                cur = poll()
                if cur is None:
                    continue
                cur_snap = snapshot_of(cur, bundle_rel)
                if cur_snap == settled_snap:
                    pending_snap = None
                    pending_result = None
                    continue
                if debounce <= 0:
                    settle(cur)
                    continue
                now = clock()
                if pending_snap != cur_snap:
                    pending_snap = cur_snap
                    pending_result = cur
                    pending_since = now
                    continue
                if now - pending_since >= debounce:
                    settle(cur)
                    pending_snap = None
                    pending_result = None
    except KeyboardInterrupt:
        pass
    duration = clock() - start
    say(f"[watch] stopped: watched {duration:.1f}s, {polls} poll(s), "
        f"{events} change event(s), {exports} export(s) written")
    return {"duration_s": duration, "events": events, "exports": exports,
            "polls": polls, "initial_files": initial_files,
            "initial_tokens": initial_tokens}
