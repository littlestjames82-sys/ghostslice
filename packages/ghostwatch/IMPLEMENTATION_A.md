# GhostWatch v0.1 - Implementation A (core owner)

Built Oct 14, 2026. Agent A owns: PLAN.md, src/**, pyproject.toml, this file.
Agent B owns tests/README/examples (REPORT_B.md) - no file collisions.

## Files delivered
- `PLAN.md` - Slice-format plan. Includes the required honest note, up front: GhostSlice already has a `watch` command for its dashboard/export session (single project, token deltas, profile/plugin reload, re-export of the default bundle). GhostWatch is the standalone staleness checker for SAVED bundles/Packs across projects: verdict (fresh/stale/unknown) tied to a bundle manifest hash, baseline snapshot of source hashes + symbols, no dashboard, no session.
- `pyproject.toml` - ghostwatch 0.1.0, stdlib only (dependencies = []), requires-python >=3.10, console script `ghostwatch = ghostwatch.cli:main`, readme=PLAN.md (Agent B's README.md can replace this later without touching core).
- `src/ghostwatch/__init__.py` (version 0.1.0), `__main__.py`
- `src/ghostwatch/core.py` - snapshot / bundle reading / check / markdown report
- `src/ghostwatch/cli.py` - `snapshot`, `check`, `watch` commands + re-export delegation

## Core design
- **Baseline problem solved explicitly:** a GhostSlice manifest's per-file sha256 hashes the SLICED text, not the source. So `snapshot` records SOURCE sha256 + size + mtime_ns + symbols per file in `<project>/.ghostwatch/snapshot.json` (versioned JSON, hashes/symbol names only, never file bodies), plus the bundle path, manifest-bytes sha256, generated_at, and file list when a bundle is present.
- **Snapshot walker:** stdlib rglob; default ignore dirs (.git, __pycache__, .claude_context, .ghostwatch, .venv, node_modules, build/dist, etc.) + `.gitignore`-lite (plain names, dir prefixes, `*` globs; negations ignored, `**` collapsed - labelled lite in the snapshot). Symlinks skipped.
- **Symbols:** Python via `ast` (qualified def/async def/class names, method=ast); JS/TS/Go/Rust/Java/Ruby/PHP/C/C++/C#/Kotlin/Swift/Scala/shell/Lua via labelled parser-lite regex line scan; other/binary/oversize (>2MB) files get hash only, method=none.
- **Check:** re-snapshots in memory and diffs.
  - With baseline snapshot: added / removed / content-changed (sha256 decides; mtime-only touch reported as `touched_only`, never stale), per-file symbol added/removed, bundle-manifest-replaced detection. Findings classified: changed_in_bundle, changed_not_in_bundle, added_not_in_bundle, removed_from_project, missing_bundle_file, stale_symbols. Only in-bundle changes, deletions of bundled files, and removed bundled symbols make the verdict stale. Verdict fresh or stale.
  - Without baseline: labelled `manifest_heuristic` fallback - bundled file missing on disk = stale; symbols_included symbol gone = stale; source mtime newer than manifest generated_at = possibly-stale finding only. Verdict is stale on a definite finding, otherwise **unknown, never a confident fresh**.
  - `pack_stale` mirrors `stale` in the report: a Pack carrying/pointing at a bundle gets the same verdict.
  - `--strict-added` (check/watch) makes added in-bundle-list files stale-making.
  - Exit codes: 0 fresh, 1 stale, 2 unknown / could-not-determine / usage error.
  - Reports: full JSON report dict (`watch-report.json` shape) + `WATCH.md` via `render_markdown`; written only when caller passes --json-out/--md-out.
- **Watch:** simple stdlib polling loop over check (interval default 2s). No daemon, no OS notifications. A verdict is only printed after two consecutive identical polls (simple anti-flap debounce). `--max-polls` bounds scripted runs; Ctrl-C exits cleanly with a summary; exit 1 if any stale verdict was seen, else 0.
- **Re-export (`--reexport`, opt-in):** on stale only. Delegates to GhostSlice: `ghostslice` on PATH, else probes `import ghostslice` and uses `python -m ghostslice export <project> -o <bundle>`. Unavailable or failed => report `reexport: unavailable|failed` with reason, verdict stays stale, exit 1, no traceback, nothing sliced locally. On success, a fresh snapshot is written so the next check starts from the new baseline.

## Gates honoured
Stdlib only. Local only. No network anywhere (no imports of socket/urllib/requests). No push, no publish, no announcements, no spend.

## Smoke verification (Agent A, /tmp fixture, since removed)
Fixture: 2-file Python project + hand-built GhostSlice-shaped `.claude_context/manifest.json`.
- `snapshot` -> 2 files hashed, bundle manifest hash recorded.
- `check` unmodified -> verdict fresh, exit 0.
- Edited bundled app.py (body change + deleted symbol `beta`) -> verdict stale, exit 1, findings name app.py under changed_in_bundle AND stale_symbols removed: ['beta'].
- `touch` on util.py -> reported under touched_only only; verdict unaffected.
- `check --reexport` while stale, with GhostSlice not on PATH/in env -> `reexport: unavailable` with reason, exit 1, no traceback, no bundle written.
- Restored files -> `watch --interval 0.1 --max-polls 3` -> exit 0, stale seen: False.
- No snapshot baseline -> verdict unknown (manifest_heuristic), exit 2, possibly-stale findings labelled heuristic.
- No bundle -> clean error message, exit 2.

## Known limits (also in PLAN.md)
- Manifest-heuristic path cannot prove freshness (by design; returns unknown).
- Parser-lite symbols are line-pattern level; per-file method is recorded so confidence is judgeable.
- `.gitignore`-lite is not full gitignore semantics.
- Poll cost is O(tree); mtime/size pre-filter is not yet implemented - every file is hashed each snapshot in v0.1 (correct first, fast later; recorded honestly here).
- Re-export argument shape assumes `ghostslice export <project> -o <bundle>`; if Slice's CLI flags differ on the installed version, re-export returns failed with stderr captured rather than guessing other flags.
