# GhostShard — merge of harden + polish + deepen lanes

Date: 2026-10-18. Merged tree built as a fresh copy of the pristine
tree (`~/workspace/ghostshard/`, never edited), with lane changes
applied in the order harden, then polish, then deepen. No
`IMPROVE.md` files were carried into the merged tree. `LICENSE` and
`pyproject.toml` are byte-identical to pristine (no version bump).

## Test counts (all verified by running, `PYTHONPATH=. python3 -m pytest tests -q`)

| Tree | Result |
|---|---|
| pristine (baseline) | 27 passed, 3 subtests passed |
| harden lane | 41 passed, 8 subtests passed |
| polish lane | 27 passed, 3 subtests passed |
| deepen lane | 36 passed, 3 subtests passed |
| **merged** | **50 passed, 8 subtests passed** |

Merged = 27 baseline + 14 harden tests + 9 deepen tests, and
3 + 5 = 8 subtests. Zero failures, zero new failures versus any
lane; merged passes everything the best lane passed and more
(the full union of all three suites).

## Files taken from a single lane (copied verbatim)

- `tests/test_harden.py` — harden (new file)
- `tests/test_plan_analytics.py` — deepen (new file)
- `examples/README.md` — polish
- `src/ghostshard/__main__.py` — polish (module docstring)
- `src/ghostshard/project.py` — polish (docstrings)
- `src/ghostshard/slicing.py` — polish (docstring)
- `src/ghostshard/taskfile.py` — polish (docstrings)
- `src/ghostshard/tokens.py` — polish (docstring)

## Files changed by multiple lanes (hand-merged)

### `src/ghostshard/bundles.py` — harden + polish + deepen (2 conflicts)

- Helper insertion anchor (conflict 1): harden inserts `_levels` /
  `_within` and deepen inserts `compute_schedule_analytics`, both
  immediately after `_sha`; polish adds the `_sha` docstring.
  Resolution: `_sha` with the polish docstring, then harden's
  helpers, then deepen's `compute_schedule_analytics`. Both helper
  sets survive in full; no duplicate logic.
- `check_plan` docstring (conflict 2, same code region written two
  ways): harden and polish each wrote a different docstring for the
  same function. Resolution: one combined docstring covering
  polish's check list and return shape, harden's never-raise /
  path-containment warning, plus the deepen analytics-recompute and
  harden dispatch checks. Docstring only; no behavior at stake.
- `write_plan`: harden's fit-split fix (id_map, `depends_on`
  expansion to all `-partN` ids, parallel groups recomputed via
  `_levels`) and deepen's `analytics` key both survive. Ordering
  note: in the merged writer, deepen's
  `compute_schedule_analytics(final_shards)` runs inside `plan_out`
  construction, i.e. AFTER harden's recompute has already fixed
  `depends_on` and `parallel_group` on the final shards, so the
  analytics (including per-group makespan) describe the corrected
  plan, and `plan_out` carries harden's recomputed
  `parallel_groups` / `max_parallelism` alongside deepen's
  `analytics`.
- `render_plan_md`: polish docstring + deepen's "Schedule analysis"
  section both survive.
- `write_bundle` / `write_bus_manifest`: polish docstrings only;
  logic untouched.

### `src/ghostshard/cli.py` — harden + polish + deepen (no textual conflicts, verified region by region)

- Module docstring, `_load_profile` docstring, `main` docstring,
  and all argparse descriptions / epilogs / help text: polish.
- `_positive_int` coercion, hardened `_load_profile` body
  (non-object profile / shard section rejected, explicit `--budget 0`
  rejected instead of silently dropped), and the hardened
  `export-bus` body (JSON/shape validation, exit 2 on bad input,
  `-o` parent directories created): harden. Verified present in the
  merged file — an early merge attempt using the wrong three-way
  base silently dropped `_positive_int`; it was caught by grep,
  redone against the pristine base, and re-verified.
- `plan` output: deepen's `analytics` in `--json` and the
  critical-path text line both survive.

### `src/ghostshard/planner.py` — harden + polish (no conflicts)

Polish docstrings (`ShardDraft`, `plan_project`) sit on top of
harden's logic unchanged: `find_cycle` import, shard-level
dependency-cycle contraction, empty-plan marked partial, and the
iterative longest-path level computation (recursive `level_of` is
gone).

### `README.md` — polish + deepen (no conflicts)

Polish's full README (At a glance table, command guide, Reading a
plan, Troubleshooting, etc.) with deepen's "Schedule analysis"
section inserted at the analogous position (after "Ownership,
sequencing, parallelism", before "Fit and caps"). One merger
touch-up: a `[Schedule analysis](#schedule-analysis)` entry was
added to polish's Contents line so the new section is reachable
from it.

## Repo-specific requirement: merged checker enforces BOTH lanes

Verified in `src/ghostshard/bundles.py::check_plan` and live:

- Harden: shape/type validation at every level (never raises on
  malformed input), resolved-path containment for bundle and file
  paths (`_within`), and bus-manifest enforcement — any present
  `bus-manifest.json` job whose `dispatch` is not exactly `false`
  fails check.
- Deepen: a present `analytics` block is recomputed from the shards
  via `compute_schedule_analytics` and any mismatched field fails
  check. The recompute runs on harden's validated shard list, so
  malformed entries are reported by harden's checks and never reach
  the analytics comparison as phantom shards.

Live smoke on the merged tree (disjoint fixture): clean plan
passes `check` (rc 0); after flipping one bus-manifest job to
`dispatch: true` AND setting `parallel_speedup` to 999, `check`
fails (rc 1) reporting BOTH the analytics mismatch and the
dispatch violation. The full suites for both behaviors
(`tests/test_harden.py`, `tests/test_plan_analytics.py`) also pass
in the merged tree.

## Anything suspicious

- Nothing dropped: lane-vs-merged tree diffs touch only files the
  other lanes changed, plus the other lanes' new test files.
- The one judgment call beyond verbatim lane text is the combined
  `check_plan` docstring (conflict 2 above) and the one-line README
  Contents addition; both are documentation only.
- No harden fix was dropped or weakened; no conflict was
  unresolvable, so nothing is flagged as blocked.
