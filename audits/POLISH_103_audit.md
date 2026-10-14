# Polish Audit — v1.0.3: dashboard warm-up, graph cache parity, history filters + percentiles, watch profile reload

Round: post-marathon polish round 3 (Ryan: "Keep going").
Baseline v1.0.2, local HEAD 107a9ec, 829 tests. Four items,
all responsiveness/reach polish on existing surfaces — no new
analysis engines. Zero-dependency stdlib only; no PyPI publish,
no announcements — those gates were never opened.

## Before / after

| Probe | Before (v1.0.2) | After (v1.0.3 work) |
|---|---|---|
| Full test suite | 829 passed | 864 passed (35 new), 1 pre-existing skip |
| First `/api/graph` call-graph build, this repo | 2.7s on the request thread (lazy) | built on a daemon thread from serve() start; measured lazy 3.29s vs warm-started first request ~0ms (payload memo hit), payloads identical |
| `graph . --json` this repo | no cache at all: ~4.6s every run | --no-cache 4.61s / cold 3.55s / warm 3.42s, md5-identical across all three |
| `history` | full listing + plain stats only | `--top N`, `--since` (ISO date/datetime or `Nd`), p50/p90 per-run percentiles; unfiltered output shape unchanged |
| `watch` profile | loaded once at startup; edits invisible until restart | content-hash reload on the poll path: valid applies, invalid keeps last-good (one report per bad content), delete reverts to defaults |
| GhostBus demo export | 129,555 -> 45,770 | unchanged (test_v13 pin) |
| `secrets .` | exit 0 | exit 0 (final verification) |

Timings are single-machine observations in this sandbox,
Python 3.12.3, labelled as such — not guarantees.

## Item A — dashboard call-graph warm-up

`_State.calls_payload()` was lazy: the first `/api/graph` request
paid the whole call-graph build on its request thread (~2.7s on
this repo per the round-2 audit; 3.29s measured this round).
Now `serve()` calls `state.start_calls_warmup()` before
`serve_forever()`: a daemon thread runs the same build while the
user is still opening the page.

Design choices, and why:

- The seam is `serve()`, not `_State.__init__` / `make_server`:
  the existing test suite (and any embedder) constructs state
  without serving, and must not pay for — or be surprised by — a
  background build. A shipped pin asserts a fresh `make_server`
  state has no warm-up thread and no payload.
- The payload contract is unchanged: there is no "building"
  state. A request that arrives mid-build waits on the existing
  build lock and receives the same final payload object as every
  other request (pinned with a gated build: 4 concurrent callers,
  all blocked until the gate opens, all receive the identical
  object). Warm-started and lazy payloads are pinned identical.
  The wait, when it happens at all, is bounded by the same build
  the lazy path would have charged that request anyway; the
  warm-up only moves when the cost is paid.
- Failure is recorded, never swallowed: the build stores its
  exception on the state and every `calls_payload()` call
  re-raises it — exactly what the lazy build did per request.
  Storing (rather than retrying per request) is sound because
  the build runs over the fixed startup scan snapshot, so it is
  deterministic: a retry would compute over the same inputs and
  fail identically. A pin drives a failing build through the
  warm-up thread and asserts the raise on the payload path, the
  same raise from a lazy state, and `/api/scan` still answering
  200 over HTTP afterwards.
- Lifecycle: the thread is a daemon and holds no server
  resource. A pin gates the build, then shuts the server down
  and closes it while the build is still blocked: shutdown
  completes, and releasing the build afterwards is harmless.

## Item B — graph command cache parity

The last command still opening no cache (round 2, F1 fixed
`scan` only). `graph` now opens the content cache under the
active plugin digest exactly like scan/lint/calls, passes it to
its scan and to the dead-symbol pass (`_with_dead_symbol_recs`),
and gains `--no-cache` with identical help/semantics;
`GHOSTSLICE_NO_CACHE=1` suppresses it the same way (pinned).
The import-graph walk itself still reads file text directly —
it is not a cache kind, exactly like the call graph's ast walk.
Byte parity is pinned three ways: fixture project
(--no-cache == cold == warm), this repo (test + a process-level
md5 probe: bebe8144… in all three modes), and a plugin project
across a plugin edit — the edit moves the digest namespace
(cache entry count grows) and the cached output still equals
--no-cache, so no stale derivation is served. Completions
examples were regenerated; the parser-drift test passes.

The warm gain is modest on this repo (4.61s -> 3.42s) for the
same reason round 2's were: the graph walk reads every file
and duplicates/secrets are not cache kinds. The win grows on
scan-dominated projects; the parity is the point of the change,
the speed is a bonus.

## Item C — history filters + percentiles

`ghostslice history` gains `--top N` and `--since WHEN`, and the
analytics payload gains per-run percentiles.

- Filters select BEFORE anything is derived
  (`ledger.analytics(..., since=..., top=...)`): totals, trend
  rows, aggregates, percentiles, and the estimator-mix check all
  describe the shown subset, and the payload gains a `filter`
  block (`since` ISO cutoff, `top`, `runs_total`, `runs_shown`,
  `undated_excluded`). Without flags there is no `filter` key
  and the payload differs from v1.0.2 only by the additive
  `aggregates.percentiles` block — the default CLI block keeps
  its pinned shape (test_v14's pin passes untouched).
- `--since` accepts an ISO date (start of day, UTC), an ISO
  datetime (naive read as UTC — the same convention `_parse_ts`
  applies to ledger timestamps), or a relative `Nd`. There was
  no relative-date precedent in the codebase, so the grammar is
  deliberately one form, documented in `--help` and the README;
  anything else is exit 2 naming the accepted forms. The cutoff
  is inclusive (a run timestamped exactly at it is shown;
  pinned). Records whose timestamps cannot be parsed cannot be
  shown to be in range: they are excluded under `--since` and
  counted in `undated_excluded`, with a note line in the text
  output — never silently kept, never silently dropped.
- `--top N` keeps the N largest savings, largest first (ties
  keep ledger order); the trend header says "largest savings
  first" instead of "oldest first" when it is active. Filters
  compose (pinned: since+top picks the right run). An empty
  filtered range reports "showing 0 of N recorded run(s)" with
  the subset's true (zero) totals — it never claims the ledger
  itself is empty; `--trend` on an empty filtered range says
  "No runs match the active filter" instead of "No recorded
  runs yet".
- Percentiles: p50/p90 of per-run before/after/saved totals in
  `aggregates.percentiles`, linear interpolation between
  closest ranks (inclusive method), rounded to 2 decimals like
  the other aggregate floats. Hand-computed pins: the v14
  fixture's saved series [400, 450, 600] gives p50 450 /
  p90 570; n=1 is its own percentile; n=2 interpolates
  (p50 200, p90 280 on [100, 300]); an empty ledger yields
  None for every percentile, never an invented zero. The
  `--trend` stats block prints the saved and after-token
  percentiles alongside mean/median.

Smoke test against this repo's real 21-run ledger: `--top 3`
shows the 3 largest runs with subset totals (saved 1,362,515
estimated tokens across them) and the filter line; `--trend`
prints percentiles over all 21 runs (saved p50 322,133 /
p90 452,861 — estimates, like everything in the ledger).

## Item D — watch profile reload

`run_watch` loaded the profile once; the module docstring said
edits "only take effect on the next watch run". Now the loop
checks the profile file at the top of every poll — before the
scan, so the scan and any settle/export in the same cycle
already use the new profile. No second poller, no threads: the
check rides the existing poll.

- Detection is stat-then-hash: most polls end at the stat
  comparison (mtime_ns, size). Only when the stat moves is the
  file read and hashed, and only a hash change counts — an
  mtime touch with identical content reloads nothing and
  reports nothing (pinned). Justification: mtime alone cannot
  distinguish a touch from an edit, and the file is a small
  JSON read only on stat changes.
- A valid new profile is applied by REPLACING the live profile
  objects (the scan matcher source and the derived export
  profile); profiles are never mutated. An invalid one (the
  same ValueError `load_profile_file` raises everywhere else)
  keeps the last-good profile and is reported once per distinct
  bad content — re-saving the same bad bytes stays silent, a
  different bad edit reports again; fixing the file applies it
  and the report says "(recovered from an invalid profile)".
  Deleting the file reverts to the built-in defaults and says
  so. The session summary gains a `profile_reloads` count.
- The watched file is `profile.path` — whatever file the
  session's profile was loaded from, including one outside the
  project (pinned at the run_watch level). Note, honestly:
  the CLI has no `--profile` flag today — it loads
  `<project>/.ghostslice.json` — so the outside-project case is
  reachable through the library API, and the CLI case is the
  project file. `profile.py` gained `load_profile_file` (the
  parsing half of `load_profile`, split out unchanged) so the
  reload validates through the exact same code path as startup.
- F1 [LOW] (Audit #1, fixed in Improve #1): a session that
  started profile-less never watched any file, so a profile
  CREATED mid-watch stayed invisible — the limiting case of the
  invisibility this item exists to remove. The watcher now
  falls back to the project's own `.ghostslice.json` when the
  session profile has no path; creation applies like any edit
  (pinned).
- Race analysis (Audit #2): the loop is single-threaded and
  the check runs only at poll tops, never inside settle() or
  an export. An export therefore always runs under exactly one
  profile object — the one `live["export"]` held when
  build_bundle was called — and a reload can only land between
  exports, never halfway through one. A pin covers the tightest
  interleaving available: a file change pending inside its
  debounce window while the profile is edited; the pending
  settle's export uses the new profile.
- Known limit, stated in the module docstring and README: the
  profile's "plugins" list is NOT re-applied on reload —
  plugins are process state the CLI activates once at startup,
  so changing it still needs a restart. Likewise a profile
  created before the session for a DIFFERENT path than the
  project file is only watched when it is the session
  profile's own path.

## Audit #2 (fresh eyes)

Probes beyond the shipped pins above:

- Warm-up thread vs. repeated serve/stop cycles in one
  process: state is per-`_State`, threads are per-state
  daemons; the full dashboard suite (which boots many servers)
  passes with no thread-related flake.
- `start_calls_warmup` racing a lazy build already in flight:
  the claim is taken under the build lock, so a warm-up call
  during a lazy build blocks until the build lands, then sees
  the payload and starts nothing.
- Graph parity under `GHOSTSLICE_NO_CACHE=1`: pinned equal to
  `--no-cache` (both mean open_cache returns None).
- Percentile edges: n=1 and n=2 pinned with hand-computed
  values; `--since` boundary inclusivity pinned; `--top`
  larger than the run count just shows everything (the filter
  block still reports runs_total == runs_shown honestly).
- Watch: two DIFFERENT bad profiles in a row each report once
  (the bad-hash is per content, not a latch) — covered by the
  recovery pin's sequence (bad -> valid); a bad -> different
  bad sequence was probed by hand in the audit session and
  reported exactly twice.
- Reload of a profile whose only change is key ORDER in the
  JSON: the hash changes (bytes differ), the reload applies a
  semantically identical profile and reports "profile
  reloaded". Accepted: the watcher reports file changes, and
  claiming it can prove semantic identity would need a Profile
  equality story the codebase does not have; the report is
  truthful (the file did change, the profile was reloaded).

## Final verification (parent-style dogfood, after the version bump)

- Full suite: 864 passed, 1 pre-existing skip, 9 subtests
  (829 baseline + 35 new in tests/test_v28_polish3.py). The one
  existing pin changed is the release version pin
  (test_v25_release.py: 1.0.2 -> 1.0.3, function renamed to
  match) — the change that pin exists to track. The completions
  drift test earned its keep twice this round: it caught the
  graph `--no-cache` regeneration AND a second drift from the
  new history flags; both regenerated, test green.
- `ghostslice secrets .`: exit 0. `ghostslice doctor .`:
  healthy (9 ok, 1 warning — the pre-existing ledger estimator-
  mix note; version 1.0.3 agrees with pyproject).
- `ghostslice lint .`: 0 errors, exactly the 5 documented
  warnings — the new code introduced none. `ghostslice calls .
  --dead`: 0 candidates — the new code is all reachable.
- GhostBus demo export unchanged at 129,555 -> 45,770
  estimated tokens (test_v13 pin, in the suite).
- No `.ghostslice-cache` in the commit; `.ghostslice-history.jsonl`
  left unstaged, as always.

## Limitations

- Warm-up removes the first-request cost only when the user
  takes longer to open the graph than the build takes (~3s on
  this repo); a request that beats the build still waits for
  it, bounded by the old lazy cost. The dashboard payload
  itself (and its 2,000-edge cap from v1.0.2) is unchanged.
- `history --since` relative form is days only (`Nd`) — no
  hours/weeks grammar; ISO values remain the precise route.
- Watch reload does not re-activate plugins (above), and a
  profile edit that only reorders keys reports a reload
  (above).
- Graph's warm-cache gain is bounded by the non-cacheable
  import walk (above).
