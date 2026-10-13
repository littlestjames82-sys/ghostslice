# G15 Audit — Performance: caching + parallelism (v0.20.0)

Goal: make repeat runs fast without changing a single output byte —
a per-project content cache (`.ghostslice-cache/`), parallel slicing
where it measurably pays, `--timing` phase breakdowns, and benchmark
proof. Baseline: v0.19.0, 590 tests passed.

## Bench first (pre-optimization, Oct 13, 2026)

Environment: Python 3.12.3, Linux x86_64, 2 vCPUs, sandbox VM whose
wall clock is noisy (idle exec round-trips take seconds; an early
foreground bench run was aborted by the harness, and a CLI `scan`
showed 10.5s wall vs 3.3s user). All numbers below are IN-PROCESS
medians of 3 runs with `time.perf_counter()`, warm OS page cache —
local measurements on this machine, not portable absolutes.

Trees: (a) this repo, 95 files, ~352K estimated original tokens;
(b) a deterministic synthetic tree of 2,000 files (seeded generator:
60% Python, 20% TS, 10% Markdown, 10% JSON, 40 packages).

| op     | repo (95 files) | synthetic (2,000 files) |
|--------|-----------------|--------------------------|
| scan   | ~0.24s          | ~1.0s                    |
| export | ~0.96s          | ~6.3s                    |
| lint   | ~2.3s           | ~32s                     |
| calls  | ~6.4s           | ~19.5s                   |

cProfile of `export` (the surface this goal optimizes), synthetic
tree, tottime leaders of ~6s total:

- `tokens.estimate_tokens_raw`: 6,000 calls, ~2.6s cumulative —
  the regex `findall` (~1.0s) plus a per-match Python loop (`len`
  called 4M times, ~0.75s). Called for every file at scan time and
  twice per file inside `slice_text` (original + sliced). This is
  the #1 cost center across scan AND export.
- `builtins.compile` / `ast.parse`: 1,200 Python files, ~1.5-2.8s
  cumulative — AST parsing inside the Python slicer (and again in
  symslice/callgraph on their own paths).
- `slicer._brace_end` (TS parser-lite brace matching): ~0.74s.
- I/O: `open` ~0.59s, `mkdir` ~0.34s (one `mkdir(exist_ok=True)`
  per bundle file).

Repo export profile agrees: `estimate_tokens_raw` ~1.06s
cumulative of ~1.9s profiled, `compile` ~0.36s.

Conclusions the build follows:

1. The cache is the win: a content-keyed slice cache eliminates
   the token estimation (both passes), the AST parse, and the
   brace matching on every repeat run. A scan-entry cache keyed
   by content hash eliminates scan's own tokenize+detect pass.
2. Threading is suspect a priori: the hot work is pure-Python
   regex/AST under the GIL, and this box has 2 vCPUs. Measure
   1 vs 2 vs 4 workers on the synthetic export before choosing a
   default; keep parallelism only where it pays.
3. lint/calls keep their own derivations (out of this goal's
   surface list); their baselines are recorded above for context.
   `calls` re-parses every Python file itself, so it does not
   inherit the slice cache; noted as a limitation, not fixed here.

## Design summary (build)

New module `cache.py`: `ProjectCache` over
`<project>/.ghostslice-cache/v1/<kind>/<key>.json`, kinds `slice`,
`symslice`, `outline`, `scan`. Keys are sha256 of a canonical JSON
dimension set: ghostslice `__version__`, estimator
`tokens.METHOD_VERSION` (where tokens are stored), relative path,
mode (slices), sorted keep-set (symbol slices), and the sha256 of
the exact source text (slices/outlines) or raw file bytes (scan).
Every slicer input is one of those dimensions — verified against
`slicer.slice_source` (path, source, mode only; the config
backstop inside configslice consumes only the rendered text and
path) — so a hit is the same pure function evaluated earlier.

Entries are JSON envelopes {v, kind, key, payload}; any parse,
shape, or key mismatch counts as corrupt and reads as a miss (the
entry is unlinked so the next store self-heals). Stores write a
temp file in the same directory and `os.replace` — concurrent
writers cannot tear an entry. A byte cap (default 256 MiB) evicts
oldest-mtime entries on store. Counters (hits/misses/corrupt/
stores) live on the instance and surface via `--timing`.

Wiring: scanner gains `.ghostslice-cache` in DEFAULT_IGNORE_DIRS
(so the cache is never scanned, exported, or watched) and an
opt-in `cache=` parameter consulted per file in `_add_file`;
`build_bundle` gains `use_cache` (default on, env
GHOSTSLICE_NO_CACHE disables), `workers`, and a `timing` out-dict,
shares one ProjectCache across its scan, fit ladder (via a new
optional `slice_fn` on fit_modes), main slicing loop, symbol
resolution (optional `cache=` on resolve_symbol_selection), and
`slice_with_symbols`. CLI: `cache stats|clear <project>`,
`scan --timing [--no-cache]`, `export --timing [--no-cache]
[--workers N]`. Default output of every command is unchanged;
manifest bytes are unchanged (timing travels out-of-band, never
into the manifest).

## Audit #1 — after build

Self-attack battery (probe scripts, all run against the built
code; bundle comparisons normalize only `generated_at`):

- Task-style bundles (selections + include + task_scores),
  slice-CLI tree output, watch `--once` exports: byte-identical
  cache-off vs cold vs warm. Notebook and empty-file corpus
  members included.
- Blocked cache dir (a regular file at `.ghostslice-cache`):
  export succeeds, output identical, failures counted not raised.
- Entry path replaced by a directory: reads degrade to misses,
  the blocked store is dropped, output identical.
- Symlinked project root: second run hits the cache stored via
  the link path; identical output. (Two different paths to one
  project keep two independent caches — duplication, never
  staleness, since keys are content-based.)
- Old-format cache dir (`v0/`) ignored entirely.
- Poison probe: an entry hand-edited to a valid envelope with a
  wrong payload text DOES change the output. This is the cache
  trust model, stated plainly: `.ghostslice-cache` is trusted
  derived data, exactly like ccache's store — an actor who can
  rewrite it can already rewrite your sources. Defenses are
  procedural: `ghostslice cache clear`, GHOSTSLICE_NO_CACHE, and
  bundle validation (`check` verifies hashes against the manifest
  of the same run, so a poisoned slice is at least internally
  consistent — it cannot be detected by `check`; documented in
  README).

### F1 [LOW] In-flight temp files match the `*.json` walks
Store temp files were named `.tmp-*.json` inside the kind dirs, so
the eviction walk and `cache stats` could see (and the eviction
walk could delete) a temp file mid-store in a racing process. A
deleted temp makes os.replace raise, which is caught and counted
as a dropped store — output was never wrong — but the fix is
trivial: temp files now use a `.part` suffix and both walks skip
dotfiles.

### F2 [LOW] Export CLI's secret-warning pre-scan bypassed the cache
The export command scans once for warnings before build_bundle
scans again; the first scan ignored the cache, so repeat exports
paid a full tokenize+detect pass the timing output didn't show.
It now shares the same open_cache (and honours --no-cache).

### Checked, no defect
- Key-dimension review against the actual slicer inputs:
  slice_source consumes (path, source, mode); the config backstop
  consumes (rendered text, path); scan derivations consume (path,
  raw bytes); outlines consume (path, source); symbol slices
  consume (path, source, keep set). Every dimension is in its
  key, plus gs/estimator versions. A profile edit cannot poison
  the cache: profiles steer mode resolution upstream, so a
  changed profile resolves different modes, which are different
  keys (pinned by test_profile_mode_change_uses_new_mode).
- Cold cache-on exports pay ~+1s per 2,000 files vs cache-off
  (6,000 small JSON stores). Accepted and documented: it is the
  one-time price of the warm-run win, and correctness never
  depends on a store succeeding.

## Improve #1

F1 + F2 fixed (cache.py temp naming/walk filters; cli.py pre-scan
cache). Full new-test file re-run green after the fixes; the
audit battery's identity probes re-run clean.

## Audit #2 — after Improve #1

Fresh probes, different angles than round 1:

- PYTHONHASHSEED 1/2/3 in three separate processes sharing one
  warm cache (symbols export): bundles identical — no set-order
  leakage into slices, manifests, or cache keys.
- `ghostslice diff` between a cache-off bundle and a warm bundle
  of the same tree: 0 added, 0 removed, 0 changed, totals delta 0.
- Incrementality on the 2,000-file tree: change exactly one file
  and re-export — counters show 3,998 hits, 2 misses, 2 stores
  (the changed file's scan + slice entries) and the new function
  is present in the output. The cache is precise, not coarse.
- Final paired benchmarks (same session, medians of 3; this
  sandbox's absolute numbers swing between sessions, so the
  paired ratios are the reliable figures):
  repo export cold-off 2.61s → warm 0.085s; repo scan 0.43s →
  0.08s; synthetic export 4.38s → 0.65s; synthetic scan 0.68s →
  0.21s. One warm synthetic run spiked to 17.5s under contention;
  the median is robust to it, and the test-suite assertion uses
  best-of-2 minima for the same reason.
- Watch settled re-exports inherit all of this (they call
  build_bundle): the warm re-export of an unchanged 2,000-file
  tree is the warm export above (~0.65s vs ~4.4s cold, ~6.8x);
  the earlier session measured the same effect at 0.59s vs 3.7s.

No defects found in the probes above. The round's tail — the
full-suite verification run under heavy sandbox load — did find
one, and it was in Improve #1's own fix:

### F6 [MED] Stale-temp sweep made cold fills quadratic
Improve #1's sweep walked the whole cache tree on EVERY store.
A cold fill of the 2,000-file tree (4,000 stores) therefore paid
O(entries) per store: measured under load at 53.5s wall / 14.8s
CPU for the fill, vs 2.2s CPU for the same export cache-off.
Fix (Improve #2): the sweep runs on the first store and then at
most every 512 stores per cache instance. Same fill after the
fix: 4.2s wall / 3.1s CPU (cache-off: 2.9s / 2.2s) — the store
overhead is back to a sane ~0.9s CPU for 4,000 entries.
The same loaded run flaked the suite's warm-speedup test once
(warm WALL 2.31s vs its usual ~0.65s while its CPU stayed
~0.45s: the warm path is many small file ops and eats I/O
contention the cache cannot control). The test now times
PROCESS CPU — the resource the cache actually saves (paired
under load: cold-off 2.26s CPU vs warm 0.45s CPU, ~5x) — with
the 3x threshold kept. A separate environment incident in the
same verification window: /tmp (512MB tmpfs) filled to 100%
with accumulated test/bench debris and two big-tree tests
failed with ENOSPC; the tests were made disk-lean (in-memory
bundle snapshots, one reused output dir) and the debris
cleaned. Not a code defect; recorded because it shaped the
test design.

## Improve #2

- F6 fix above (sweep throttled to first + every-512th store).
- `--timing` prints phases at millisecond precision (3 decimals),
  so small projects stop showing resolve phases of "0.00s".
- BENCHMARKS.md checked in with the paired local measurements,
  the environment, and the honesty notes (sandbox noise, medians,
  local-only). README gains the cache section: design, key
  dimensions, trust model, commands, the .gitignore suggestion,
  and the estimator-version discipline note. CHANGELOG and
  roadmap updated; version 0.20.0.

  (The cold-fill store cost accepted in Audit #1 was re-measured
  after the F6 fix in Audit #2: 4,000 stores ≈ +0.9s CPU over a
  cache-off cold run — the ~+1s-per-2,000-files estimate holds.)

## Limitations

- Threads do not pay here: at 2 workers cold exports gained ~5%
  (noise), at 4 they lost time, and warm runs were SLOWER with
  threads (0.78s vs 0.59s) — GIL-bound regex/AST work on a 2-vCPU
  box. `--workers N` exists, is deterministic, and defaults to 1.
  The cache is the repeat-run win; a cold cache-on run pays the
  one-time store cost (~+0.9s CPU per 4,000 entries measured
  after the F6 fix; the fill's wall time under sandbox load
  varies far more than its CPU).
- lint and calls do not consume the disk cache (recorded
  baselines: lint ~2.3s/~32s, calls ~6.4s/~19.5s repo/synthetic).
  lint keeps its per-run memo; calls re-parses ASTs itself. The
  scan cache is available to them via scan(cache=...) but wiring
  their slice/outline derivations through is a future goal's
  work, not this one's.
- The cache is trusted derived data (see Audit #1, P4): a
  hand-forged entry with a valid envelope changes output, like
  any build cache. `cache clear` + GHOSTSLICE_NO_CACHE are the
  procedural defenses; nothing in the cache is ever trusted for
  a security decision (secret scanning/redaction always run on
  the final slice text, cached or not — redaction happens after
  the cache lookup, on whatever text ships).
- Two paths to one project (symlink vs real) keep two caches;
  duplication, never staleness (content keys).
- Cache entries are per (content, path): renaming a file misses
  even when its bytes are unchanged. Deliberate — path is a real
  slicer input (language, test detection) — and the cost is one
  re-slice.
- The 256 MiB cap evicts by mtime, which a busy racing process
  can skew; eviction only ever costs recompute.

Final state: 614 tests passed (590 baseline unweakened + 24 new
in tests/test_v20_perf.py), 9 subtests passed; `ghostslice
secrets .` exits 0; version 0.20.0. Suite wall time in this
sandbox swung 30s (quiet) to 245s (peak contention) across the
marathon window for the pre-existing 590 alone; the final green
run took 84s under load, of which the new file is ~25-35s
standalone (the two 2,000-file tests are most of it, by design —
the task's one-big-tree budget). No .ghostslice-cache is left in
this repo (the Q4 bench cleared its own; tests build on temp
roots only).
