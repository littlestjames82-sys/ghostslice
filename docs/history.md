# History and calibration

Part of the [GhostSlice README](../README.md). The savings ledger, its analytics, and the estimator calibration report.

## Savings ledger (v0.2)

Every export appends one line to `.ghostslice-history.jsonl` in the
project (scanner-ignored). `ghostslice history ~/my-project` and the
dashboard total the estimated savings across runs.

## History analytics (v0.14)

```bash
ghostslice history ~/my-project                 # plain totals (unchanged)
ghostslice history ~/my-project --trend         # per-run table + charts
ghostslice history ~/my-project --trend --model claude-opus
ghostslice history ~/my-project --json          # full analytics payload
ghostslice history ~/my-project --top 5         # the 5 biggest savings (v1.0.3)
ghostslice history ~/my-project --since 7d      # the last week (v1.0.3)
```

`--trend` prints each run oldest first (before → after, saved,
saved %, the change in after-tokens versus the previous run, and
estimated $ saved per run and cumulative), then aggregates: mean /
median saved %, per-run percentiles (p50/p90 of the saved and
after-token totals, v1.0.3), best and worst runs, the first→last
change in context size, the span (weekly run rate only when the
history spans at least a day), and ASCII sparklines of saved and
after tokens across runs. Dollar figures use the model's **input**
rate from the local prices snapshot (context is input tokens) and
are labelled with its date: "prices as of …, local snapshot, not
live".

**Filters (v1.0.3):** `--top N` keeps only the N runs with the
largest savings (largest first), and `--since WHEN` keeps runs at
or after a cutoff — an ISO date (`2026-10-01`), an ISO datetime,
or a relative form like `7d` (N days ago). They compose, and
everything shown (totals, trend, aggregates, percentiles) then
describes the runs shown; the text output says so on a `Filter:`
line, and the JSON gains a `filter` block with the total and
shown run counts. Records whose timestamps cannot be parsed are
excluded by `--since` and counted (`undated_excluded`), never
silently kept or dropped. With neither flag the output is exactly
what it was before, plus the percentile block in `aggregates`.

The JSON payload keeps the summary keys (`runs`,
`total_before_tokens`, `total_after_tokens`, `total_saved_tokens`,
`records`) and adds `runs_detail` (per-run saved %, deltas,
cumulative tokens and $), `aggregates`, `charts` (the sparklines),
`corrupt_lines`, an `estimator` block, and a `model` block when
priced. The dashboard's `/api/history` returns the same payload.
The HTML report embeds a savings-history chart (inline SVG bars for
saved tokens, a line for after tokens) whenever the project has a
ledger, and omits the section when it has none.

**Estimator versions, honestly:** records written from v0.14 on are
stamped with the estimator version that produced their totals
(`"estimator": "v2"`, the calibrated method). Older records carry
no stamp, and pre-v0.10 (v1) totals cannot be told apart from
v0.10–v0.13 (v2) totals — so any history that is not uniformly one
stamped version is flagged with an "Estimator mix" warning instead
of being trended as if its totals were directly comparable.
Corrupt ledger lines (bad JSON, non-object, non-numeric token
fields) are skipped and counted, never fatal.

## Calibration report (v0.10)

```bash
ghostslice calibrate ~/my-project [--json]
```

Per language family present: file count, characters, the raw
(uncalibrated) estimate, the calibrated estimate every other command
uses, the implied characters-per-token, and the factor and target
behind it. This is the transparency surface for the estimator: if a
total looks surprising, `calibrate` shows exactly which family and
factor produced it. See the token bullet under
[Honest labels](reference.md#honest-labels) for the
evidence basis and the v0.9 -> v0.10 totals-shift note.
