# GhostConsole — MERGE report (2026-10-18)

Merged tree built from a fresh copy of the pristine tree
(`~/workspace/ghostconsole/`, never edited), with the harden, polish,
and deepen lane changes applied in that order. Method: per-file
three-way merge (`git merge-file`, pristine as base, polish first,
then harden, then deepen), followed by hand resolution of the two
conflicts and a line-level audit that no lane change was dropped.

## Final test counts

| Tree | Result |
| --- | --- |
| Pristine baseline | 54 passed (stated in all three IMPROVE.md files) |
| Harden lane | 70 passed (54 + 16 new in tests/test_harden.py) |
| Polish lane | 54 passed (no test changes) |
| Deepen lane | 63 passed (54 + 9 new in tests/test_history_trends.py) |
| **Merged** | **79 passed, 0 failed** (`python3 -m pytest -q`, 61.17s) |

79 = 54 baseline + 16 harden + 9 deepen. The merged suite passes
everything every lane passed, with zero new failures. No lane suite
was re-run: the IMPROVE.md counts are stated above and the merged
run includes every lane test file verbatim.

## Files by source lane

Only one lane changed it — copied that lane's version:

- Harden: `tests/test_harden.py` (new)
- Polish: `examples/README.md`, `examples/run_demo.sh`,
  `src/ghostconsole/__main__.py`, `src/ghostconsole/collect.py`
- Deepen: `tests/test_history_trends.py` (new)

Changed by multiple lanes — hand/three-way merged, all changes kept:

- `src/ghostconsole/adapters.py` — harden + polish + deepen (see
  conflicts below)
- `src/ghostconsole/cli.py` — harden + polish (see conflicts below)
- `src/ghostconsole/model.py` — polish class/`to_dict()` docstrings +
  deepen's new optional `trend` field on `Section` (included in
  `to_dict()`); disjoint regions, clean merge
- `src/ghostconsole/render.py` — polish docstrings + deepen's trend
  rendering (escaped meta span in HTML, appended in text summary);
  disjoint regions, clean merge
- `README.md` — polish's rewrite (In short summary, Quick start,
  options/exit-code tables, Troubleshooting) + deepen's history
  trend paragraph; disjoint regions, clean merge

No `IMPROVE.md` is present in the merged tree (lane files were not
copied; the two new test files were copied individually).

## Conflicts and resolutions

### 1. KNOWN CONFLICT — Bench `tasks_failed` history bug (harden vs deepen, adapters.py)

Both lanes fixed the same code region in the Bench history-only
branch: the adapter read only `failed`, but GhostBench's history
writer records `tasks_failed`.

- Harden's version (inline): `raw_failed = last.get("tasks_failed",
  last.get("failed"))`, accepted only when `_is_int(raw_failed)`
  (excludes bools) and `>= 0`, else coerced to 0.
- Deepen's version: `failed = _bench_failed_count(last)`, a helper
  that tries `tasks_failed` then `failed` via `_int_or_none`
  (excludes bools), returns the count or `None`, and is also used
  by `_bench_trend`, where `None` correctly means "no comparison"
  rather than a fake 0.

Resolution: kept deepen's helper as the single code path (the
history branch now calls `_bench_failed_count(last)`; harden's
inline duplicate was removed, so no duplicated logic remains),
and strengthened the helper with harden's negative guard: a
negative value is not a count — it is skipped, falling through
to the other key, and yields `None` if neither key counts.
This keeps every behavior both lanes tested:

- `tasks_failed: 2` → attention, "2 failed" (both lanes' tests)
- `tasks_failed: 0` → ok (both lanes' tests)
- bool counts are never accepted as numbers (deepen `_int_or_none`)
- negative counts can no longer print as e.g. "-1 failed" or drive
  Attention (harden's guard; deepen's original would have)
- trend comparisons still skip unknown counts instead of using 0

One deliberate nuance: if `tasks_failed` is present but invalid
(bool/negative/non-int) and `failed` holds a valid count, the
merged code uses `failed` (deepen's fall-through), where harden's
inline code coerced to 0 without consulting `failed`. No lane test
pins that combination; falling through to a valid recorded count
was judged the more correct reading, and it is recorded here.

### 2. cli.py `_build_model` (harden vs polish)

Polish added a docstring to `_build_model`; harden added the
`--stale-days < 0` usage-error check (stderr message, return None
→ exit 2) as the function's first statements. The merge conflicted
because both touched the function head. Resolution: kept both —
polish docstring first, then harden's validation immediately after,
before project resolution. Verified by harden's negative
stale-days test passing in the merged suite.

### Non-conflict overlaps verified in the audit

- adapters.py: harden's substantive fixes (Bench/Watch embedded
  timestamps `created_utc`/`checked_at`, Watch verdict stripping
  and findings dict counting, Ledger `estimated_cost` fallback,
  empty/corrupt histories rendering UNREADABLE, non-object JSON
  treated as corrupt for Ghost-specific files, `_is_int` bool
  rejection everywhere), polish's 12 adapter docstrings, and
  deepen's trend builders/wiring (including trends on report-backed
  rows) are all present. Lines a lane "lost" in diff audits were
  pristine lines superseded by another lane's fix (e.g. harden's
  `_is_int` replacing `isinstance(value, int)`), never a lane fix.
- cli.py: harden retained pristine's short help strings where
  polish rewrote them; polish's fuller help/epilog wording wins
  for help text only, exactly as the polish lane intended, and
  harden's only cli.py behavior change (stale-days validation)
  is preserved.
- README.md: deepen's removed lines are pristine text that
  polish's rewrite reorganised; deepen's sole README addition
  (the trend paragraph) is present in the merged file.

## Anything suspicious

- Nothing unresolved. No harden fix was dropped.
- The strengthened `_bench_failed_count` negative guard is the
  only code in the merged tree that appears in neither lane
  verbatim; it is the union of the two lanes' stated rules
  (deepen IMPROVE: "non-int counts (including bools) yield no
  comparison"; harden IMPROVE: "a boolean or negative value in
  either is treated as 0 rather than guessed at" — in the merged
  history branch, `None` is falsy and behaves exactly as 0 for
  state and summary).
