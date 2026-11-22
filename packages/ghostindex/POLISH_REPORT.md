# GhostIndex v0.1 - Polish report (Oct 14, 2026)

Polish round at Ryan's "Polishing" direction, after parent
verification of the D1 fix (45 passed). Sole folder ownership for
this round. Loop: audit (PLAN.md, IMPLEMENTATION_A.md, REPORT_B.md,
FIX_REPORT.md, README), demonstrate each problem before fixing it,
fix, pin with new tests, keep every existing assertion untouched.

## Test counts

- Before: **45 passed, 0 failed** (`python3 -m pytest tests -q`,
  baseline run at audit time, 46.5s).
- After: **49 passed, 0 failed**, confirmed on two consecutive full
  runs (51.9s, 67.6s). The 4 new tests are additions in
  `tests/test_vacuum.py`; no existing test was edited, weakened, or
  deleted.
- Version stays 0.1.0 in `pyproject.toml` and `__init__.py`. No push,
  no publish, no announcements, no spend. Stdlib only (no new imports
  anywhere; the work uses `sqlite3` facilities already in the tree).

## What changed

### 1. Deleted content now actually leaves the database file (main fix)

Problem, demonstrated before fixing: sqlite DELETEs only move pages
onto the freelist, and v0.1 never vacuumed (IMPLEMENTATION_A.md
stated this as a known limit). On a fixture project (one ~150 KB
text file plus a small file), the index was 217,088 bytes; after
`ghostindex remove` dropped every indexed file, the database was
still **217,088 bytes**. "Remove is the supported way to reclaim a
root's space" (PLAN.md) was not true in file-size terms.

Fix:
- `src/ghostindex/store.py`: new `reclaim_space(conn)` (FTS5
  'optimize' special insert, best effort on very old sqlite, then
  `VACUUM`, committing first because VACUUM cannot run inside a
  transaction) and `freelist_bytes(conn)` (freelist pages x page
  size).
- `remove` now calls `reclaim_space` after dropping the root and
  prints the compaction result. Same fixture: **217,088 -> 53,248
  bytes (163,840 reclaimed)**. The remaining 53 KB is live schema
  plus FTS shadow tables, verified by search/list behaving exactly
  as before.
- New `ghostindex vacuum` command for space freed by `update`
  removals, which do not drop a root: prints before/after bytes and
  the reclaimed count, supports `--json`, and exits 2 (creating
  nothing) when no database exists. Demonstrated: after an update
  removed the big file, the db sat at 237,568 bytes; `vacuum`
  brought it to 53,248 (184,320 reclaimed), with search still
  correct on both sides of the removal (kept term hits, removed
  term exits 1).
- `stats` now reports `reclaimable_bytes` (JSON) and a
  "reclaimable by vacuum: N bytes (run: ghostindex vacuum)" line
  when N > 0, so held space is visible before anyone reclaims it.
  In the demonstration it reported 131,072 reclaimable bytes,
  matching the freelist the subsequent vacuum released.

Tradeoff, stated plainly: `remove` is a deliberate housekeeping
action, so paying one VACUUM per remove is the right default; on a
very large index that compaction can take a moment. Routine
`index`/`update` runs do not vacuum, so their speed is unchanged.

### 2. `doctor` now reports the database size it always claimed to

PLAN.md's risk section and the README both said doctor reports the
database size; the first build printed only the path. `doctor` now
includes the size in text output and as `db_bytes` in `--json`,
making the documentation true instead of editing the claim away.

### 3. Stale honesty wording corrected

- README, honest limits: the FTS5 bullet now describes the real
  reclaim behaviour (remove compacts, stats shows reclaimable
  bytes, vacuum reclaims update-freed space) instead of the pre-fix
  "remove is the supported way to reclaim" line.
- README, command table: `remove` row mentions the compaction, and
  a `vacuum` row was added. (The long-line limit line was already
  corrected by the parent before this round; verified accurate.)
- IMPLEMENTATION_A.md: a dated polish addendum supersedes its two
  stale statements (the no-vacuum limit, and the pre-D1 excerpt
  description) rather than rewriting the original build record.
- PLAN.md was not edited: it is the v0.1 spec of record, and its
  risk note about remove reclaiming a root's space is now literally
  true.

### 4. New tests (tests/test_vacuum.py, 4 tests, all black-box CLI)

- `test_remove_vacuums_and_reclaims_space`: remove shrinks the db
  to under half and says "reclaimed"; the root is gone from `list`.
- `test_vacuum_command_reclaims_space_freed_by_update`: update
  removal leaves reclaimable bytes that `stats --json` reports > 0;
  `vacuum` shrinks the file to under half; `stats` then reports 0
  reclaimable; search hits/misses stay correct.
- `test_doctor_reports_database_size`: `doctor --json` `db_bytes`
  equals the real file size.
- `test_vacuum_with_no_database_is_exit_2_and_creates_nothing`.

## Deliberately left alone

- **bm25 text-only ranking.** The seed candidate, and a documented
  PLAN limit ("structure-aware ranking is a later wave if it earns
  its place"). There is no stdlib structure-aware ranker to swap in;
  any hand-rolled boost (filename or definition heuristics) would
  change result order against the pinned ranking fixture on a
  judgement call, not a proof. The vacuum win was provable to the
  byte; this one is not, so it stays a stated limit.
- **Lockfiles are still indexed.** IMPLEMENTATION_A.md records
  skipping them as a v0.2 candidate and explicitly "not a silent
  v0.1 behaviour"; changing the default in a polish round would
  break scanner parity with GhostSlice, which is a feature.
- **Update fast path trusts size + mtime.** Same documented tradeoff
  git's stat cache makes; the hash check runs whenever either
  differs. No evidence of a miss in any fixture or smoke.
- **No VACUUM inside `index`/`update`.** Only deletions strand
  meaningful space, and `remove`/`vacuum` now cover those moments;
  compacting on every incremental run would tax the common path
  for a rare benefit.
- **Suite runtime (~50-70s).** The suite is black-box subprocess
  runs against real sqlite databases; the time is the price of the
  hard-rule proofs staying honest. Not optimised.

## Files changed

- `src/ghostindex/store.py` - `reclaim_space`, `freelist_bytes`.
- `src/ghostindex/cli.py` - remove compacts and reports; new
  `vacuum` command; `stats` reclaimable bytes; `doctor` db size;
  command list in the module docstring.
- `tests/test_vacuum.py` - new, 4 tests.
- `README.md` - command table, FTS5 honest-limit bullet.
- `IMPLEMENTATION_A.md` - dated polish addendum.
- `POLISH_REPORT.md` - this file.

Gates held: stdlib only, local only, no network, no GitHub push,
no PyPI/publish, no announcements, no spend, no version bump.
