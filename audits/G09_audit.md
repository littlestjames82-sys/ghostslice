# G09 Audit — History analytics (v0.14.0)

Goal: real analytics over the savings ledger — per-run trend with
deltas, estimated $ saved at input rates, ASCII sparklines, estimator
stamping + mix warning, corrupt-line tolerance, the savings chart in
the HTML report, and the analytics payload on /api/history.
Baseline 398 tests; build brought the suite to 423 (25 new in
tests/test_v14_history.py).

## Audit #1 (after build)

### F1 [MEDIUM] Cumulative $ and total $ disagree by rounding drift
Per-run saved_cost_usd is rounded to 4 decimals and the cumulative
column sums the ROUNDED values, while aggregates.total_saved_cost_usd
is computed from total tokens. On this repo's own ledger the trend
table's final cumulative reads 0.7620 while the total line reads
0.7619. Two numbers on one screen claiming the same quantity must
agree exactly. Fix: accumulate the raw (unrounded) running cost;
round only for display. Then final cumulative == total by
construction (sum of saved == total saved). Pin with a test whose
per-run values round against each other.

### F2 [MEDIUM] runs_per_week is noise over sub-day spans
Three runs inside 22 minutes produce "Span: 0.0 day(s), ~1388.6
run(s)/week". The math is defensible and the message is nonsense:
a weekly rate extrapolated from minutes misleads. Fix: analytics
only reports runs_per_week when the span is at least 1 day (else
null), and the CLI prints sub-day spans in hours. Pin both.

### F3 [LOW] After-change line has nested parens and doubled sign
"(+23,505 (+120.2%))" — the delta format and the pct format each add
their own sign/parens. Fix formatting to "(+23,505 tokens, +120.2%)".

### F4 [TEST QUALITY] test_no_model_no_dollar_fields is tautological
Its last assert is `X if cond else True`, which can never fail.
Tighten to assert the real contract: without a model, aggregates
carry no total_saved_cost_usd key and runs carry no $ fields.

### Reviewed, sound
- $ side: _input_cost uses input_per_mtok_usd only; a fixture model
  with output rate 99.0 vs input 2.0 pins it (totals match the input
  math and provably not the output math). Context tokens are input
  tokens; preflight() prices the same side. Consistent.
- Negative-saving runs stay negative end to end (record, pct, $,
  aggregates) — no clamping anywhere; pricing.estimate_cost's clamp
  is deliberately NOT reused for per-run $ (documented in _input_cost).
- Estimator mix semantics: any unstamped record => mixed, because
  pre-v0.14 records cannot be split into v1-era vs v2-era. Multiple
  stamped versions => mixed. Uniform stamped => clean. The repo's own
  3 unstamped records warn as designed.
- Ordering: runs_detail follows ledger append order (the chronological
  truth of an append-only file); timestamps are parsed only for span
  math, never used to re-sort. A record with an unparseable `at`
  yields timestamp=null and is excluded from span, not from totals.
- Corrupt lines: non-JSON, non-object JSON, and non-int token fields
  are all counted and skipped. This is stricter than the old summary
  (which summed with .get defaults and would have CRASHED on a
  non-dict line at r.get) — a robustness fix, and old append_record
  output always parses clean, so no legitimate record is lost.
- summary() gained corrupt_lines additively; every old key is
  untouched (CLI default block asserted byte-shape by test).
- Report SVG: saved bars share one zero line (negatives hang below);
  the after-tokens polyline is min/max normalised and LABELLED "own
  scale" in the SVG itself; timestamps are escaped via _e; run data
  enters the SVG only as formatted numbers and <title> text built
  from ints. 1-run and flat-series shapes covered by tests.
- /api/history and the scan payload's history key now carry the
  analytics superset (old keys intact, records list intact).

## Improve #1 (fixes applied)
- F1: ledger.analytics accumulates raw cumulative cost; per-run and
  cumulative $ are display-roundings of raw values.
- F2: runs_per_week gated to span_days >= 1 in analytics; CLI prints
  sub-day spans as hours.
- F3: after-change line reformatted.
- F4: test tightened to the real no-model contract.

## Audit #2 (of the build + Improve #1 fixes)

### G1 [VERIFIED] F1 invariant now holds on real data
The repo's own ledger (the F1 reproducer) now trends 0.2803 ->
0.5074 -> 0.7619 cumulative, and the aggregate total is 0.7619 —
identical, where the build printed 0.7620 vs 0.7619. A synthetic
drift-shaped fixture (3 runs of saved 333 at $3/Mtok) pins it.

### G2 [LOW] _input_cost docstring outlived its per-run role
After F1, _input_cost serves only the aggregate total; its docstring
still framed the no-clamp choice around per-run display. Wording
fixed to state both uses plainly (per-run values are raw-accumulated
in analytics; the helper prices a single token count, unclamped).

### G3 [TEST GAP] Tie-breaking and empty-JSON shapes unpinned
Best/worst ties (equal saved_tokens) resolved to the earliest run by
key design but had no test; the CLI --json path on an empty ledger
was only covered at the analytics level. Both pinned in Improve #2.

### Reviewed, no change
- Report with a ledger of ONLY corrupt lines: runs == 0 after
  skipping, so the savings section is absent (per the goal's
  absent-not-empty rule); the corrupt count still surfaces on the
  CLI and in the JSON payload. Accepted: the report is a snapshot
  surface, the warning lives where the ledger is inspected.
- All-zero saved series in the report SVG: zero line sits at the
  plot top and bars have zero height — geometrically consistent
  (nothing saved), and the totals paragraph carries the numbers.
- /api/history payload duplicates records + runs_detail for a large
  ledger (~2x the old payload). It is a localhost dashboard API and
  the duplication is the price of the additive contract; noted as
  the known cost, revisited only if G15 (performance) profiles it.
- span_days is stored rounded to 2 decimals while the runs/week gate
  uses the unrounded span; a 0.996-day history shows "Span: 1.0
  day(s)" with no weekly rate. Consistent enough, and the gate's
  direction (suppress the noisy number) is preserved.
- --trend together with --json: JSON wins, trend is ignored. Same
  precedence as the other commands' --json paths.

## Improve #2 (fixes applied)
- G2: _input_cost docstring corrected.
- G3: tests pin best/worst tie -> earliest run, and CLI --json on an
  empty ledger parses with runs == 0 and null aggregates.

