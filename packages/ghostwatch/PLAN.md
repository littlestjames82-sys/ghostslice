# GhostWatch - Standalone Staleness Checker for GhostSlice Bundles and Packs
Working name, prepared Oct 14, 2026. Wave 3 tool #20 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostWatch: plain job, plain name. It watches saved context go stale.
- Checked against the family: sits next to GhostSlice, GhostVerify, and GhostPacks without claiming any of their jobs. No claim of a live product search yet. Treat as a working name until a name check runs at build gate, same as GhostSlice did Oct 12.
- Alternatives held in reserve: GhostStale (accurate but ugly, and names the failure not the job), GhostFresh (implies it refreshes bundles on its own, which v0.1 must not do silently).

## Honest note on overlap with GhostSlice `watch` (read this first)
GhostSlice already has a `watch` command (`ghostslice watch`, `src/ghostslice/watch.py`). That watcher is a **dashboard/export session tool**: it polls ONE project inside a live Slice session, reports token deltas, reloads the project profile and plugins, and optionally re-exports that project's default `.claude_context` bundle after a debounced change. It is the right tool while you are sitting in a Slice session working on one repo.

GhostWatch is **not a duplicate of that dashboard watcher**. The differences are the whole reason it exists:

- **Object checked:** Slice `watch` watches a live project. GhostWatch checks **saved artifacts**: an already-exported bundle directory, a `.claude_context` folder, or a GhostPacks-saved Pack, possibly weeks old, possibly in a different project than the one you have open.
- **Question answered:** Slice `watch` asks "what changed just now, and what is the token delta?" GhostWatch asks "is this specific saved bundle/Pack still trustworthy, yes or no, and which files/symbols made it stale?" It produces a verdict (`fresh` / `stale` / `unknown`) tied to a bundle manifest hash, not a live token stream.
- **Scope:** Slice `watch` is single-project, single-bundle. GhostWatch is built to be run across projects (CI, a nightly sweep, a pre-flight step before reusing an old Pack on a new machine) with a machine-readable report per bundle.
- **Baseline:** Slice `watch` snapshots scanner state at session start. GhostWatch snapshots **source hashes and symbols at bundle time** and stores that baseline next to the bundle (`.ghostwatch/snapshot.json`), because a saved bundle's manifest `sha256` is a hash of the *sliced* text, not of the source file, so the manifest alone can never prove the source has not moved for non-`full` modes.
- **No session, no dashboard:** GhostWatch has no dashboard, no server, no profile/plugin reload, and no token-delta stream in v0.1. If you want those, use `ghostslice watch`.

If a future Slice release folds a bundle-verdict into its own watcher, GhostWatch should be retired in favour of it rather than kept as a parallel watcher. That is stated here so the overlap is a known, bounded risk, not a hidden duplication.

## The problem
A GhostSlice bundle is a snapshot in time. The project keeps moving:

- A file that was sliced `full` or `signatures` is edited, so the agent works from an old body or old signatures.
- A symbol is renamed, added, or deleted, so a `symbols`-mode entry or a task prompt names something that no longer exists, or misses something new.
- A new file is added that the bundle never included, or a bundled file is deleted.
- A saved Pack (GhostPacks) or a shared `.claude_context` is reused days later with no indication that its baseline is gone.

Today there is no check for any of this except re-running `ghostslice check`, which only proves the bundle on disk matches its own manifest. It says nothing about whether the bundle still matches the **project**. A stale bundle passes `check` and still misleads the agent, and the developer pays for it in a wasted run.

## Position in the Ghost stack
- GhostSlice governs what an agent READS and proves a bundle matches its manifest (`check`).
- GhostVerify governs whether what it read was ENOUGH for a task, and whether a patch holds.
- GhostPacks governs sharing Slice profiles/packs as data.
- GhostWatch governs whether a saved bundle/Pack is still CURRENT against its project.
- Agent Seatbelt governs what an agent DOES.

Story: Slice exports -> Watch snapshots the baseline -> project changes -> Watch reports the bundle stale (by file and symbol) -> developer re-exports (optionally via Watch) -> Verify checks the fresh bundle is enough.
No overlap: Watch never judges sufficiency (Verify), never slices (Slice), never edits project source.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Bundle format: reads any GhostSlice bundle (`manifest.json`, `PROMPT.md`, `files/`), including the default `.claude_context` layout. Reads `generated_at`, `root`, per-file `path` / `mode` / `language` / `sha256` (sliced-text hash) / `symbols_included` when present.
- Pack format: a GhostPacks Pack that carries or points at a bundle/manifest is checked the same way; the bundle verdict is the Pack verdict, labelled as such.
- Profile: respects `.ghostslice.json` ignore behaviour only in the lightweight sense documented under MVP (default ignore dirs + `.gitignore`-lite). Watch does not load Slice plugins and does not execute project code.
- Re-export: by calling the GhostSlice CLI as a subprocess when it is available (see MVP item 4). Watch contains no slicer of its own.

Integration contract:
- Input: project path + bundle path (default `<project>/.claude_context`) and/or an explicit snapshot file.
- Baseline: `.ghostwatch/snapshot.json` written by `ghostwatch snapshot`, normally at export time. Without a baseline, Watch falls back to a clearly-labelled mtime heuristic and reports verdict `unknown`-leaning detail (see MVP item 2), never a confident `fresh`.
- Output: `watch-report.json` + a human report `WATCH.md` next to the bundle or at a caller-chosen path, never inside project source files.
- Exit codes: 0 = fresh, 1 = stale, 2 = could not determine (no bundle, no baseline and no manifest timestamp, unreadable manifest, missing project).

## MVP (v0.1) - local CLI first, no daemon requirement
Rationale: same as Slice v0.1. A check that runs on demand in CI or by hand proves the verdict before anyone trusts a background watcher.

1. Snapshot: `ghostwatch snapshot <project> [--bundle <path>] [-o <snapshot.json>]`
   - Walks the project with stdlib only: default ignore dirs (`.git`, `__pycache__`, `.claude_context`, `.ghostwatch`, virtualenvs, `node_modules`, build/dist dirs) plus a lightweight `.gitignore` reader (plain names, directory prefixes, and `*` globs; negations and `**` are best-effort and labelled as lite in the snapshot).
   - For each visible file records: relative path, size, `mtime_ns`, and a sha256 of the source bytes.
   - Extracts a symbol outline per file: Python via `ast` (top-level and nested `def` / `async def` / `class`, qualified names); other text files via a labelled parser-lite line scan (`function`, `class`, `def`, `export ... function/class/const`). Binary or unreadable files record hash/size only, symbols empty, and are labelled as such.
   - If a bundle is given or found, records the bundle path, the sha256 of its `manifest.json` bytes, its `generated_at`, and its file list, so a later check can also detect the bundle itself being replaced.
   - Snapshot format is versioned JSON (`tool`, `version`, `created_at`, `root`, `bundle`, `files`). It contains hashes and symbol names only, never file bodies.

2. Check once: `ghostwatch check <project> [--bundle <path>] [--snapshot <path>] [--json]`
   - Re-snapshots the project in memory and diffs against the baseline snapshot when one exists: added, removed, and content-changed files (hash is the decider; an mtime-only touch with identical bytes is reported as touched, not stale).
   - Without a baseline snapshot: falls back to the manifest. Bundled files missing on disk are stale by name. Files whose source mtime is newer than the manifest `generated_at` (or, if absent, the manifest file's mtime) are reported as `possibly_stale` under a heuristic baseline, and the verdict is `stale` only on a definite finding (missing file, or a `symbols_included` symbol that no longer exists); otherwise the verdict is `unknown`, never a confident `fresh`. The report states which baseline was used.
   - Symbol staleness: for each bundled file, compares baseline symbols (or manifest `symbols_included`) with current symbols and reports added / removed / renamed-by-disappearance symbols by file. A removed symbol that the bundle shipped is a definite stale finding.
   - Pack staleness: if the checked path is a Pack/bundle directory, the same verdict is reported as the Pack verdict (`pack_stale` mirrors `stale`), so a saved Pack and a plain bundle get one consistent answer.
   - Report classifies every finding as: `changed_in_bundle`, `changed_not_in_bundle`, `added_not_in_bundle`, `removed_from_project`, `missing_bundle_file`, `stale_symbols`. Only the in-bundle / missing / removed-symbol classes make a bundle stale; out-of-bundle changes are reported for context and labelled as not by themselves invalidating the bundle (a caller may treat new in-scope files as stale with `--strict-added`).

3. Polling watch (simple loop, no daemon): `ghostwatch watch <project> [--bundle <path>] [--interval 2] [--max-polls N] [--reexport]`
   - A plain stdlib polling loop: snapshot, sleep `interval` seconds, re-check, print each settled verdict change. No daemon, no service install, no file-system notification dependency in v0.1 (polling only, same choice as Slice's own watcher).
   - Debounce is deliberately simple in v0.1: a change must be seen in two consecutive polls before it is reported, so a mid-save read does not flap the verdict. This is a smaller, dumber debounce than Slice watch's token-settle window, on purpose: Watch reports verdicts, not token deltas.
   - `--max-polls` bounds a run for scripts and tests; without it the loop runs until Ctrl-C, which exits cleanly with a session summary and exit 0 if no stale verdict was ever reported, else 1.
   - There is no requirement to run `watch` at all: `snapshot` + `check` are the v0.1 product. `watch` is a convenience loop over `check`.

4. Optional re-export: `ghostwatch check|watch ... --reexport`
   - On a stale verdict, Watch may attempt one re-export by calling GhostSlice if it is available: first `ghostslice` on `PATH`, else `python -m ghostslice`, probed without side effects.
   - If GhostSlice is not available, or the call fails, Watch reports `reexport: unavailable` or `reexport: failed` with the reason, keeps the stale verdict, and exits 1. It never crashes, never pretends a re-export happened, and never falls back to slicing anything itself.
   - A successful re-export is followed by a fresh snapshot, so the next check starts from the new baseline. Re-export is opt-in only; a plain `check` never writes a bundle.

5. Reports and history
   - `WATCH.md`: verdict, baseline used, bundle manifest hash, and every finding grouped by class with file + symbol + reason.
   - `watch-report.json`: same data, machine-readable, for CI and for GhostBench.
   - No history ledger in v0.1 beyond the report files the caller asked for. Watch does not write into the project except: the snapshot file (only on `snapshot`, or after a successful opt-in re-export), and the report files at the caller's chosen output path.

## Out of scope for v0.1
- A daemon, a system service, OS file notifications (inotify/FSEvents/ReadDirectoryChangesW), or a dashboard/server of any kind.
- Slicing, re-slicing, or editing any project or bundle file itself. Re-export is delegated to the GhostSlice CLI, opt-in, or it does not happen.
- Judging whether a bundle is sufficient for a task (GhostVerify), or whether a patch is correct.
- Loading or executing GhostSlice plugins, project code, or Pack code. Packs are data; Watch reads manifests only.
- Symbol analysis beyond the outline level above. No call graph, no type checking, no cross-file reachability.
- Cloud, accounts, telemetry, paid layer, network access of any kind.

## Build estimate
- Snapshot walker + hashing + symbol outline (ast + parser-lite): 2-3 days
- Manifest/Pack reader + baseline diff + symbol staleness + report: 2-3 days
- Polling loop + opt-in re-export delegation: 1-2 days
- Tests (planted-change fixtures, touch-vs-edit, missing baseline, missing GhostSlice), README, demo on a real bundle: 2 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through. The polling loop is the part most likely to be cut to a stub if time slips; `snapshot` + `check` must ship whole.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team CI staleness gates / multi-project sweep history. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Planted-change test: snapshot a known project + bundle, edit one bundled file's body without changing its symbols, `check` must report it stale by file name.
- Symbol test: rename or delete a bundled symbol, `check` must report that file and that symbol as stale; add a symbol to an out-of-bundle file and the bundle verdict must stay fresh (finding reported as context only, unless `--strict-added`).
- Touch test: `touch` a bundled file without changing bytes; `check` must stay fresh (hash decides, not mtime).
- Missing-baseline test: with no snapshot, a bundle whose files all predate the manifest must not be reported confidently fresh; the report must name the heuristic baseline used.
- Missing-GhostSlice test: `--reexport` on a stale bundle with no GhostSlice available must exit 1 with `reexport: unavailable`, no traceback, no bundle written.
- Every verdict reproducible from `watch-report.json` + snapshot + bundle manifest hash alone.

## Risks / honest notes
- Hash-of-sliced-text limit: a GhostSlice manifest alone cannot prove source freshness for sliced modes, which is exactly why the snapshot baseline exists. Any copy that claims Watch can judge a bundle from its manifest alone would be overstating it; the heuristic path is labelled wherever it is used.
- Parser-lite limits: non-Python symbol outlines are line-pattern level. A symbol hidden by a macro, a generator, or unusual formatting can be missed; reports label the per-file extraction method (`ast` vs `parser-lite` vs `none`) so a reader can judge confidence.
- Polling cost on very large trees: hashing every file on every poll is O(tree size). v0.1 uses mtime/size as a cheap pre-filter and only re-hashes files whose stat moved, but a tree with constantly-changing build outputs should be kept out by ignore rules, and the report says how many files were hashed per check.
- `.gitignore`-lite is not full gitignore semantics. Where it matters, the snapshot records that the lite reader was used; a caller who needs exact git semantics should snapshot with explicit ignore options instead of trusting the lite parse.

## Next gate
Ryan's go on: (1) GhostWatch as working name, (2) snapshot + check as the v0.1 product with the polling loop as a convenience, no daemon, (3) re-export opt-in only and delegated to the GhostSlice CLI, never built in, (4) build position in Wave 3 as directed Oct 14, 2026 ("All of them").
