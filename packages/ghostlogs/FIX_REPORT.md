# GhostLogs fix round: REPORT_B.md defects D1 and D3

Parent-directed fix round, src/** only. No tests edited, no xfail
markers touched. Both pinning tests now XPASS as strict failures,
which is the expected signal; the parent removes the markers.

## Suite, exact counts

- Before: `python3 -m pytest tests -q` -> 24 passed, 2 xfailed
  (the parent's baseline, reproduced at the start of this round).
- After: 24 passed, 2 failed - and both "failures" are the strict
  XPASS of `test_dedupe.py::test_error_line_true_count_is_stated`
  (D1) and `test_budget_and_safety.py::test_budget_600_lands_at_or_under_budget`
  (D3). Everything else green, including the reconciliation bars
  (exact line accounting, dropped-by-reason sums at budgets 850
  and 150) and the planted-secret bars.

## D1 - repeated ERROR lines got no counted exemplar

Root cause: lines claimed by an error window never enter the
routine duplicate table (`dup_account` in analyze.py), and nothing
else counted them. On the fixture the five occurrences of
`ERROR db connection failed host=db1` (stored at lines 57 and 63,
three more collapsed in place at 64-66) produced no duplicate
group, and the window's in-place note ("3 consecutive repeated
lines collapsed in place") stated no total, so the true count 5
appeared nowhere in the pack or the manifest.

Fix (analyze.py, pack.py):
- `Window` now keeps per-signature occurrence accounting
  (`line_counts`) for EVERY line it claims - stored, collapsed in
  place, or past the store cap - recording exemplar text,
  occurrences, byte-identical copies, and first/last line numbers.
  Counting only; no claim decision changed.
- `Analysis.window_duplicate_groups` aggregates those counts
  across windows by signature (occurrences >= 2). The table is
  deliberately separate from the routine duplicate table: window
  lines follow window accounting in the pack (kept /
  window-not-fitted), not exemplar accounting, so merging the
  tables would double-count.
- The manifest's `duplicates` section now carries `window_groups`,
  `window_list_truncated`, and `window_list` (same entry shape as
  the routine list, plus `in_window: true`), and INCIDENT.md's
  Repeated lines section lists the window groups with their exact
  counts under "Repeated lines inside error windows".

Demonstrated on the fixture (default budget): the manifest window
list carries the ERROR group with occurrences 5, lines 57-66, and
INCIDENT.md states `- x5 (byte-identical x1), lines 57-66:
2026-10-14T08:03:11Z ERROR db connection failed host=db1`.
Byte-identical is honestly 1, not 5: the five occurrences differ
in their timestamps, which is exactly the near-duplicate case the
plan's two-tier counting describes.

## D3 - budget tier selection overshot when a fittable tier existed

Root cause: selection was greedy on per-item estimates with a
fixed scaffold reserve, and fit was judged only afterwards on the
rendered pack. The reserve badly underestimated the real scaffold,
so at --budget 600 the full window was selected and the rendered
pack landed at ~823, marked over_budget with exit 1 - even though
a fittable selection existed. The over-budget path is reserved by
the plan for when the mandatory anchors alone exceed the budget.

Fix (pack.py): the builder now descends a tier ladder, rendering
and measuring each candidate for real, and ships the first tier
whose rendered estimate fits:

  full      - windows with all stored lines, plus exemplars
  trimmed   - windows trimmed to matched lines, trace/continuation
              lines, and repeat representatives, plus exemplars
  exemplars - no windows; anchors plus duplicate exemplars
  anchors   - the mandatory minimum only

The over-budget path (pack written, `over_budget: true`, exit 1)
is reached only when even the anchors tier cannot fit. The shipped
tier is recorded in the manifest as `budget_tier`, and trimmed
windows are marked per window (`trimmed_lines`) and in the pack
text; trimmed-away lines are counted under windows not fitted.

Accounting under trimming: an in-window repeat counts as collapsed
only when the stored line above its run is kept to represent it
(the trim rule always keeps that representative). On a fully
emitted window this reduces exactly to the previous formula.
Agent A's anchor-overlap adjustment (a duplicate-group member that
is also a timeline anchor counts once, as kept), which landed in
pack.py/analyze.py during this round, is preserved verbatim in the
new `_assemble`.

Each tier attempt renders with a fresh redactor, so the shipped
manifest's redaction counts describe the shipped pack only.

Demonstrated on the fixture (short path):

| budget | before | after |
|---|---|---|
| 500 | window skipped, est 519, over, exit 1 | anchors tier, est 509, over, exit 1 (mandatory minimum alone exceeds 500, so the over-budget path is the plan-correct outcome) |
| 600 | full window shipped, est 823, over, exit 1 | exemplars tier, est 587, fits, exit 0 |
| 850 | full, est 823, exit 0 | trimmed tier, est 797, exit 0 (the full tier grew to 891 with D1's count statements, so the ladder descends one tier and still fits) |
| 2000 | full, est 823, exit 0 | full tier, est 891, exit 0 |
| 150 | over-budget path | anchors tier, est 509, over, exit 1 |

Counts reconcile exactly (`reconciles: true`) at every tier and
every budget probed.

## Files changed

- `src/ghostlogs/analyze.py` - `Window.line_counts` accounting in
  `claim_window_line`; `Analysis.window_duplicate_groups`.
- `src/ghostlogs/pack.py` - tier ladder (`TIERS`, `_select`,
  `_assemble`, `_trimmed_lines`), `build_pack` descends tiers and
  records `budget_tier`; manifest `duplicates.window_list` and
  per-window `trimmed_lines`; INCIDENT.md renders trimmed windows
  and the window duplicate groups; limits list updated to match.

Gates held: stdlib only, local only, no network, no push, no
publish, no spend. Manifest line accounting still reconciles
exactly, as pinned by the passing tests.
