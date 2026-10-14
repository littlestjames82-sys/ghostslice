# Polish Audit — v1.0.2: cache for lint + calls, call data in the dashboard, configurable duplicate floors

Round: post-marathon polish round 2 (Ryan: "Keep going").
Baseline v1.0.1, local HEAD 9adc384, 795 tests. Three items,
all integration/performance/config polish — no new analysis
engines. Zero-dependency stdlib only; no PyPI publish, no
announcements — those gates were never opened.

## Before / after

| Probe | Before (v1.0.1) | After (v1.0.2 work) |
|---|---|---|
| Full test suite | 795 passed | 829 passed (34 new), 1 pre-existing skip |
| `lint .` this repo (125 files) | ~2.0s every run (no cache) | --no-cache 2.34s / cold 1.90s / warm 1.71s |
| `calls .` this repo | ~3.7s every run (no cache) | --no-cache 3.52s / cold 3.73s / warm 2.88s |
| `lint` GhostBus | 0.48s | warm 0.31s, output byte-identical to the v1.0.1 baseline capture |
| `calls` GhostBus | 0.22s | warm 0.18s, cached/no-cache byte-identical |
| `/api/graph` payload | import graph + recs + duplicates | + `calls` payload (below) |
| GhostBus demo export | 129,555 -> 45,770 | 129,555 -> 45,770 (unchanged; test_v13 pin) |
| `secrets .` | exit 0 | exit 0 |

Timings are single-machine medians-of-a-few in this sandbox,
Python 3.12.3, and are labelled observations, not guarantees.
The warm gains are real but modest on this repo: lint's remaining
time is duplicate detection + secret scanning + file reads
(none of them cache kinds), and calls' remaining time is the
`ast` parse + walk per Python file (also not a cache kind — see
Item A). Cold `calls` is slightly SLOWER than --no-cache (cache
fill cost); the win starts at the second run.

## Item A — persistent cache for lint + calls

cache.py's kinds already keyed everything needed; lint.py and
callgraph.py simply never imported it. Now:

- `lint_project(..., cache=None)`: when a cache is passed, the
  scan it runs goes through the scan kind and the rules' slice
  derivations go through `cache.cached_slice_text` (the export
  path's one seam). The CLI `lint` command opens the cache with
  the active plugin set's digest as namespace — the exact
  discipline export uses — and gains `--no-cache` with the same
  help text/semantics as scan/slice/export. MCP `lint_project`
  and the dashboard pass no cache (the dashboard is a startup
  snapshot whose state test pins "writes nothing"; ci.py keeps
  its never-opens-the-cache rule) and keep the in-run memo.
- `CallGraph(..., cache=None)` / `build_call_graph(...,
  cache=None)` / `dead_symbol_recommendations(..., cache=None)`:
  per-file outlines route through the cache's outline kind via
  the same get/put seam `symslice.resolve_symbol_selection`
  uses (rows are Symbol dicts; a shape drift on read falls back
  to recompute). The CLI `calls` command opens the cache once
  (plugin-digest namespace) and shares it between its scan and
  the graph build; `--no-cache` added identically.
- NOT cached, deliberately: duplicate detection (cache.py has
  no kind for normalized text/shingles; inventing one is a
  separate design), the call graph's ast parse + walk, secret
  scanning (never cache-derived, per cache.py's trust model).

Parity evidence (Audit #1 probes): on this repo, lint --json is
byte-identical across --no-cache / cold / warm / warm-again
(md5-matched), and calls --json likewise (1.51 MB payload).
GhostBus lint warm output is byte-identical to the pre-change
v1.0.1 baseline capture. Corrupt-cache probe: six cache entries
overwritten with garbage — lint and calls output unchanged,
exit 0 (corrupt reads as miss, entries self-heal).
GHOSTSLICE_NO_CACHE=1 suppresses cache creation for lint/calls
and output still matches. Plugin invalidation is pinned by a
shipped test: a Lua plugin whose slice changes between runs —
the second run's lint output reflects the new plugin and equals
its --no-cache run, because the plugin digest is the namespace.
Dogfood after the version bump: `secrets .` exit 0, doctor
healthy (version 1.0.2 agrees with pyproject), self-lint still
exactly the 5 documented warnings, `calls . --dead` still 0.

## Item B — call data in the dashboard graph

Neither server.py nor graph.py referenced callgraph; the
dashboard had the import graph only. Now:

- `_State.calls_payload()` builds `callgraph.build_call_graph`
  over the state's startup scan/profile/graph on FIRST use and
  memoises it for the server run (double-checked lock; the
  state is a startup snapshot, so a per-run memo matches its
  semantics — same rule as the slice memo). `/api/graph` gains
  a `"calls"` key; no endpoint was added or changed shape
  otherwise.
- Payload bounds: symbols ship in full (the per-file view needs
  every symbol of the previewed file; rows are small), edges
  are capped at CALL_EDGE_CAP = 2,000 and dead candidates at
  CALL_DEAD_CAP = 200, with `edges_total` / `dead_total` and
  `*_truncated` flags reported. A `"scope"` line states the
  analysis is Python-only. On THIS repo the payload proves the
  caps matter: 2,214 symbols, 4,160 edges -> 2,000 served
  (truncated: true), /api/graph 889 KiB total, first request
  2.74s (the build), second 0.009s (memoised).
- UI: a "Call graph" panel under the slice preview. Selecting
  a file renders its symbols with called-by / calls /
  referenced-by lists (deduped display names; module-level
  callers shown as "(module level)") and a "possibly dead" tag.
  Non-Python files get the honest sentence "No call data for
  this file: call relationships are computed for Python files
  only." When edges are truncated the panel says so and gives
  the counts. All rendering is createElement + textContent —
  the served page still contains no `.innerHTML` (the v1.0.1
  pin passes, re-pinned for the new surface); the page JS
  passes `node --check`.
- A project with no Python files serves an empty calls payload
  (0 symbols/edges/dead) with the scope line — probed.

## Item C — configurable duplicate floors

Two profile sections, validated with the lint section's
discipline (unknown keys, non-numeric, non-positive, or
fractional values are a loud ValueError at load; doctor's
profile check therefore accepts valid sections and FAILs on a
typo'd key, naming it):

- `"duplicates": {"near_min_chars": N}` — the near-duplicate
  normalized-char floor in duplicates.find_duplicates
  (default NEAR_MIN_CHARS = 200, unchanged when unset).
  find_duplicates takes the floor as a parameter; every caller
  holding the profile passes `near_min_chars_for(profile)`:
  graph.recommendations, lint, ci.run_ci, the dashboard state,
  the HTML report, and the scan/graph/explain CLI surfaces — so
  all surfaces agree on one project (probed via CLI: scan,
  graph, and lint all flip together when the profile floor
  drops to 100 on the fixture pair).
- `"ci": {"duplicates_floor_tokens": N}` — the CI duplicates
  check floor (default DUP_FLOOR_TOKENS = 500, unchanged when
  unset). _check_duplicates reads `duplicates_floor_for
  (profile)`; the check's details report the EFFECTIVE floor.
- Config surface checklist: profile.py schema + FLOOR_SECTIONS
  validation ✓; Profile.to_dict carries both sections (doctor's
  "sets:" line names them) ✓; init wizard documents both in its
  justification lines with the defaults and the key spellings,
  and — the lint precedent — writes neither (defaults stay live,
  not frozen into generated config) ✓; _existing_summary names
  the sections when present ✓; README config reference
  (Profiles section), Duplicates section, and CI section
  updated ✓; tests pin default parity + lowered/raised results
  ✓. CLI flags: deliberately none — the duplicates surfaces
  (scan/graph/lint) have no analogous per-run numeric flags and
  ci's only numeric flag (--budget) belongs to a different
  check; the README says the floors are profile-only.

## Audit #1 — self-probes (done)

Parity battery above (repo + GhostBus, md5-compared); dashboard
fixture checks (known chain main->helper->leaf served, a
no-calls symbol, a dead candidate, a non-Python file, an
HTML-shaped filename flowing as inert JSON); config checklist
above; full suite green at this point (823 passed; 829 final
after the Improve #2 pins) with exactly the expected
regeneration — adding `--no-cache` to two parsers changed the
generated completions, so the shipped examples were regenerated
with `ghostslice completions` (the v1.0.1 L007 known-warning
files; their content changed because the parser did).

### F1 [LOW] scan's dead-symbol pass ignores the cache scan already opened
`cli._with_dead_symbol_recs` builds a full CallGraph with no
cache even in the `scan` handler, which has already opened (and
filled) the project cache for its scan records — so `scan`
re-outlines every Python file on every run while its sibling
derivations are cached. (The `graph` handler opens no cache at
all today.) Fix in Improve #1: thread the scan handler's
already-open cache through `_with_dead_symbol_recs` into
dead_symbol_recommendations. The `graph` command keeps its
current no-cache behaviour — opening a cache there is a new
write for that command, out of this item's scope; recorded as
a limitation, not silently changed.

### Observations (no action)
- Cold `calls` (3.73s) is slower than --no-cache (3.52s): the
  fill writes ~450 KB of outline entries for this repo. Warm
  runs (2.88s) repay it. This matches the export cache's known
  cold-fill cost shape.
- First /api/graph request on a large project pays the full
  call-graph build (2.74s here) on the request thread; later
  requests are memoised (0.009s). ThreadingHTTPServer keeps
  other endpoints responsive meanwhile. Accepted for a local
  dashboard; noted so it is a decision, not a surprise.

## Improve #1 (done)

F1 fixed: `_with_dead_symbol_recs` takes an optional cache and
the `scan` handler passes the cache it already opened; pinned
by test_scan_dead_symbol_pass_reuses_open_cache (scan --json
byte-identical off/on, outline entries present after a cached
run, dead-symbol recommendations still produced). The `graph`
command is unchanged (limitation, below).

## Audit #2 — fresh eyes (done)

**Cache invalidation on plugin change, for calls too:** the
lint-side invalidation was already pinned; the same wiring
serves calls (the CLI opens its cache under
`active_digest()`). Probe: warm `calls` under plugin v1 (5
cache entries), edit the plugin, re-run — entries 5 -> 10 (the
old namespace orphaned, the new one filled) and output
byte-identical to --no-cache. Converted to a shipped pin
(test_calls_plugin_edit_moves_cache_namespace).

**Graph payload on a big project:** this repo served live —
889 KiB /api/graph, caps engaging honestly (2,000 of 4,160
edges, truncation flagged in payload AND repeated by the UI),
2,214 symbols, dead 0. Concurrency probe: 8 simultaneous first
requests return byte-identical bodies (the double-checked lock
builds once) — converted to a shipped pin.

**Floor edge values:** 0 and negative are load-time ValueErrors
(pinned, both sections). Fractional, string, bool, and typo'd
keys likewise. The non-obvious cases: Python's json accepts the
bare literals `Infinity` / `NaN`, and int(inf) raises
OverflowError rather than ValueError — the validator's
math.isfinite guard rejects both as ValueError naming the key
(probed, then pinned). Huge values are legitimate and behave
as documented: floor 10^9 loads, finds no near pairs, and the
CI check passes; floor 1 admits the small fixture pair.
Sections resolve independently (a profile setting only "ci"
leaves the near floor at its default — probed).

**Unparseable Python under cache:** a syntax-error file lands
in skipped_files with cold/warm payload parity (no outline is
stored for it — outline_source returns None and the put is
skipped — so a later fix to the file can never meet a stale
"no outline" entry). Pinned (test_calls_unparseable_file_
skipped_cold_and_warm).

**Single-file lint:** `lint <file>` still works (open_cache
degrades to None for a non-directory root, the pre-v1.0.2
behaviour exactly). Probed: exit 0, correct payload.

No over/under-reach found in Audit #2: no fix beyond Improve
#1 was needed. Improve #2 is the probe-to-pin conversion
above (5 additional tests; the round's file totals 34).

## Limitations

- The `graph` CLI command still builds its dead-symbol pass
  without a cache: it has never opened one, and giving it a
  new write was out of Item A's scope (lint + calls). Its
  output is unchanged; only its speed is.
- Duplicate detection, secret scanning, and the call graph's
  ast walk are not cache kinds, so warm lint/calls still pay
  them; the measured warm gains (lint ~27%, calls ~18% on
  this repo) are what the keyed derivations are worth here.
  Repos whose cost is scan/slice-dominated gain more (GhostBus
  lint: ~35%).
- Dashboard call edges are capped at 2,000 per payload: on a
  project past the cap, a symbol's caller/callee lists in the
  panel can be incomplete. The payload and the panel both say
  so with counts; the CLI `calls` command remains the uncapped
  surface.
- The floors are profile-only (no per-run CLI flags) — a
  deliberate consistency call, documented in the README.
