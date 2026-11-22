# GhostLedger - Polish Round (Oct 14, 2026)

Sole folder owner polish of v0.1, at Ryan's "Polishing" direction
after Wave 3 parent verification (30 tests passing). House loop:
audit first, demonstrate-then-fix, two distinct improvement passes,
a regression test for every fix.

**Final suite: 44 passed** (`python3 -m pytest tests -q`), up from
30. No version bump, no release, no push, no publish, no
announcements, no spend, no network. Stdlib only throughout. The
parent's earlier F1 fix (Proxy importer accepts the `ts` timestamp
alias) is untouched and still covered.

## Audit findings (all demonstrated before any fix)

Probes were run against the unmodified core first; observed values
below are the pre-polish outputs.

- **A1 / F2 (required) - Bench `variants{}` never read.** Importing
  the Bench fixture booked task adv-001 at total 4200 / estimated
  4200 / ratio 1.0, although the task's own data says sliced 1000
  of full 4200 (the shipped sample ledger entry led-003 shows the
  intended 1000 / 4200 / 0.2381 shape). The suite's headline
  sliced-vs-full divergence was invisible in Ledger.
- **A2 - Negative token counts book nonsense.** `make_entry` with
  input -10000 booked total -10000, cost -$0.03, ratio -10.0; with
  estimated -1000 and actual 100 it set `loop_warning: true`
  (100 > 3 x -1000). The CLI accepted negative `--*-tokens` flags
  and every importer passed source counts through unchecked.
- **A3 - Model matching was exact-only.** `--model Claude-Sonnet`
  and `--model " claude-sonnet "` both booked cost null (unknown)
  against a table that lists `claude-sonnet`, producing false
  unknown-model entries; the spaced label would also have grouped
  separately from `claude-sonnet` in reports.
- **A4 - Report ratio mixed coverage.** With one entry estimated
  1000 / actual 1000 and one unestimated entry of 9000, totals
  reported ratio 10.0 and delta 9000 - blaming the estimated entry
  for tokens nobody estimated. The formula divided the grand
  total by the estimated sum.
- **A5 - Batch dedupe gap (defence in depth).** `append_entries`
  deduped only against the file, not within the batch it was
  handed. No CLI path can trigger it today (every importer stamps
  a per-record `source_ref` into the entry id, so duplicate source
  lines still book separately, faithfully, under different refs),
  but a direct caller handing `[entry, entry]` double-booked.
- **A6 - Bench variant edge shapes all silently collapsed to
  full.** Null tokens, a missing sliced variant with `proxied`
  present, `variants` of the wrong type, string token counts, and
  `variants.full` with no top-level `full_tokens` were probed: all
  booked actual = full. Some of those are correct fallbacks (null,
  wrong type); proxied-only, string counts, and variant-supplied
  full were real information being dropped.

## Pass 1 - import correctness (F2 + invalid evidence + dedupe)

- `ingest.py`, Bench importer: reads `variants{}` after the
  top-level fields. Priority `sliced`, then `proxied`, `verified`,
  `recalled` - `sliced` is the variant GhostBench always emits and
  the one its own totals aggregate; the extras are fallbacks.
  Variant values may be `{"tokens": N}` dicts (also `token_count` /
  `total_tokens` keys) or a bare number. `variants.full.tokens`
  supplies the full count when `full_tokens` is absent. The chosen
  variant is recorded as `bench_variant=<name>` in the entry note
  (note is not part of the id, so existing dedupe is stable).
  Estimate stays `full_tokens` whenever a different actual was
  found, per PLAN.md.
- Invalid variant evidence (null, negative, unparseable) is
  treated as absent and falls back, never booked. A sliced count
  of exactly 0 is valid and books 0.
- Negative counts are invalid everywhere: `make_entry` raises
  `ValueError` for a negative input/output/total/estimated count;
  the CLI `add` path reports it as an error and exits 2 writing
  nothing; Slice imports count a negative `after_tokens` record as
  skipped (a negative `before_tokens` reference is dropped from
  the note); Proxy records with any negative count or estimate are
  skipped; Bench records with a negative full/output count are
  skipped.
- `ledger.append_entries`: dedupe now also applies within the
  batch, order preserved.
- `make_entry` strips surrounding whitespace from project / model /
  agent labels before grouping and id computation.

Demonstration after Pass 1: the Bench fixture imports as
1000 / 4200 / ratio 0.2381 and 2600 / 2600; a real GhostBench
sample run imports as 2 entries, 2,000 actual vs 8,400 estimated,
matching GhostBench's own totals line.

## Pass 2 - report and cost accuracy

- `ledger.py` grouping: buckets now track
  `actual_tokens_with_estimate` (the summed actuals of only the
  entries that carry an estimate). `estimate_vs_actual_ratio` and
  `estimate_delta_tokens` are computed from that figure, not the
  grand total. The CLI summary line was updated to match
  ("entries with an estimate only"). Demonstration: the A4 case
  now reports ratio 1.0 / delta 0 instead of 10.0 / 9000. When
  every entry carries an estimate - as in all shipped samples -
  the numbers are unchanged.
- `prices.model_rates`: exact id match first (a table listing two
  ids that differ only by case keeps its meaning), then a
  trimmed, case-folded match. `Claude-Sonnet` and `CLAUDE-SONNET`
  now book the claude-sonnet estimate; genuinely unlisted models
  still book null and list under `unknown_models`.
- Docs brought back in line with the CLI (the shipped README
  described the F2 limit as current behaviour):
  - `README.md`: Bench import paragraph rewritten; report-format
    section documents `actual_tokens_with_estimate` and the new
    ratio semantics; costs section documents the model matching
    and the negative-count rule; layout lists this file.
  - `examples/README.md`: Bench bullet rewritten; demo total
    corrected 85,970 -> 79,570.
  - `examples/sample-report.json`: gained
    `actual_tokens_with_estimate` in totals and every bucket
    (equal to `total_tokens` everywhere in the samples, since
    every sample entry carries an estimate; ratio/delta values
    unchanged).

## Tests

- Updated openly (pinned behaviour changed by F2):
  - `tests/test_cli.py::test_import_bench_report_books_each_task`
    previously pinned actual = full (sum 6800) as the v0.1 limit;
    it now asserts the corrected per-task booking (1000/4200 ratio
    0.2381, 2600/2600, sums 3600 actual / 6800 estimated), with the
    history stated in the comment.
  - `tests/test_docs_examples.py`: demo total 85970 -> 79570, plus
    explicit Bench-row assertions (1000 of 4200 per task).
  - `tests/test_examples_format.py`: its mirror `agg()` now
    computes ratio/delta over estimated entries only and includes
    `actual_tokens_with_estimate`; sample numbers unchanged.
- New `tests/test_polish.py` (14 tests): proxied-only variant,
  null/negative variant fallback, string variant tokens and
  variant-supplied full, zero sliced, variant over-estimate
  tripping the loop warning, Bench re-import dedupe, negative
  `add` for all four token flags (exit 2, nothing booked), Slice
  import skipping a negative record, the `append_entries` batch
  guard (labelled unit test - no CLI path can reach it), model
  case / whitespace / genuinely-unknown booking, and report ratio
  at totals and by-model level under partial estimate coverage.
- Full suite re-run at the end: **44 passed**.

## Left alone, deliberately

- Duplicate lines inside one Slice history file still book as two
  entries: their `source_ref` line numbers differ, and a history
  file with the same export logged twice is two exports. That is
  faithful mirroring, not double-booking; re-importing the same
  file still adds 0.
- Proxy records whose stated `total_tokens` disagrees with
  `tokens_in + tokens_out`: the parts win (they are what cost is
  computed from) and the stated total is used only when no parts
  exist. That was the shipped, sensible rule; no producer shape
  demonstrating a conflict was found, so it was not changed on
  speculation.
- Bench sliced tokens that live in `variants{}` are now read, but
  Bench's per-variant cost figures (`estimated_input_cost_usd`)
  are not imported: Ledger costs come from its own dated table
  only, by design.
- Summaries do not recompute cost for entries already on disk
  (a model that becomes known after a table edit still shows its
  booked null in old entries). Rewriting booked history on read
  would break the ledger's append-only honesty; a reprice command
  is a feature decision for Ryan, not a polish fix.
- `IMPLEMENTATION_A.md` and `REPORT_B.md` are the build record and
  were not edited; F2's status there is superseded by this file.
- No version bump: `ghostledger` stays 0.1.0 everywhere.
