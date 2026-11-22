# GhostLedger - Agent B Report (tests / docs / examples)

Builder: Agent B, tests/docs side only. Date: Oct 14, 2026.
Ownership respected: `tests/**`, `README.md`, `examples/**`, and this
file only. Nothing under `src/**` was edited, `pyproject.toml` and
`PLAN.md` were not touched. Gates respected: local only, no network,
no push, no publish, no announcements, no spend. No real keys or
live prices anywhere: every cost figure in tests/examples is an
estimate hand-computed from the local dated snapshot table
(GhostSlice `prices.json` shape, as of 2026-10-12).

## Test result (final run, this machine)

```
python3 -m pytest tests -q     ->  30 passed in 12.32s
```

## What was delivered

- `tests/` - 30 tests in 4 files, all passing:
  - `test_examples_format.py` (8) - the shipped sample history
    carries the full PLAN entry shape; covers all four sources;
    per-entry ratio and loop-warning math rechecked (strictly
    greater than 3x); costs hand-check against the dated table,
    including unknown model = null and zero-rate local = 0.0 as
    distinct cases; the sample report's totals and all four grouped
    buckets (project/model/agent/day) are recomputed from the
    history and match exactly; cost labelling carries the date and
    "never billed amounts"; a recursive scan proves no
    credential-named field exists anywhere in the examples.
  - `test_ingest_fixtures.py` (6) - each fixture mirrors the real
    producer's shape: Slice history lines satisfy
    saved = before - after; the Proxy fixture's top-level
    `requests` is a count (not a record list) and its entries sum to
    the report totals; the Bench fixture's tasks sum to its corpus
    totals with sliced variants present; the credential canary is
    planted in exactly the one input fixture designed to prove the
    drop.
  - `test_cli.py` (15) - black-box CLI against the landed core:
    version/help; add with a known model hand-checks
    (10,000 in / 2,000 out on claude-sonnet = $0.06 estimated);
    `--total-tokens` alone books as input; unknown model books cost
    null, prints the not-in-table note, and lists under
    `unknown_models`; identical re-add is not double-booked; loop
    boundaries: 3.1x flagged, 2.9x not, exactly 3.0x not (strict >);
    summary exits 1 with the warning listed and writes no files;
    since/until and project filters; Slice import counts
    (3 parsed / 3 added / 2 skipped) with totals equal to the sum
    of `after_tokens` (9,000) and re-import adding 0; Proxy import
    drops the canary (see below); Bench import books each task;
    `--source-file` auto-detects slice and bench; import with no
    source exits 2; report writes `ledger-report.json` + `LEDGER.md`
    with all four groupings, the estimate cost note, and the
    warnings section, exiting 1 when warned; `report --json` prints
    and writes no files.
  - `test_docs_examples.py` (1) - the examples/README demo flow end
    to end: three imports add 2 entries each, the manual 3.6x entry
    warns, 7 entries / 85,970 total tokens, summary and report exit
    1, re-import adds 0.
- `examples/`:
  - `sample-history.jsonl` - SAMPLE ledger in the core entry shape:
    8 entries, all four sources, 2 projects, 3 models (one
    unlisted), 3 agents, 2 days; planted cases led-007 (3.6x, loop
    warning), led-008 (2.9x boundary, unknown model, cost null),
    zero-rate local entries.
  - `sample-report.json` + `sample-report.md` - the report for that
    history in the core `summarise()` / LEDGER.md shape, recomputed
    from the history, labelled SAMPLE in both files. Totals:
    84,470 total tokens, 82,170 estimated, $0.27891 estimated cost
    over 7 costed entries, 1 loop warning.
  - `inputs/` - one importable file per source tool, each in the
    producer's real shape (Slice history, Proxy report, Bench
    report), plus `examples/README.md` with a verified five-minute
    demo.
- `README.md` - install, quickstart, the loop-warning rule and its
  "warning, not a verdict" framing, cost-estimate labelling and the
  unknown-model rule, the full entry-format table, per-source import
  behaviour (including the Bench v0.1 limit, stated plainly), the
  secrets discipline, the command table with exit codes, the report
  format with the honest grouped-cost split, and the verification
  bar.

## Findings for Agent A / parent verification

- **F1 (real, minor) - Proxy entry timestamps are missed on
  import.** GhostProxy ledger entries timestamp with `ts`
  (e.g. `"ts": "2026-10-13T11:02:00+00:00"`), but the Proxy
  importer's timestamp aliases are `at` / `timestamp` / `time`
  only. Verified by spot run: both fixture entries (ts days
  2026-10-13 and 2026-10-14) booked with `at` = import time and
  `day` = the import day. Token counts, project, and dedupe are
  unaffected; the impact is that by-day grouping for Proxy data is
  wrong whenever import happens on a later day than the requests.
  One-word fix on Agent A's side: add `"ts"` to the `_pick` alias
  list in `_proxy_record_to_entry`. No B-side test asserts the
  imported day for Proxy entries, deliberately, so the fix will
  not flip a test; a day assertion should be added with the fix.
- **F2 (known limit, pinned) - Bench sliced tokens inside
  `variants{}` are not read.** PLAN.md says a Bench task's actual
  is the sliced/proxied tokens "when present"; in real
  bench-report.json rows those tokens are present only inside
  `variants.sliced.tokens`, which the importer does not look at,
  so tasks book actual = `full_tokens` and estimated = actual.
  Agent A already records this in IMPLEMENTATION_A.md.
  `test_import_bench_report_books_each_task` pins the current
  behaviour with a comment so an importer fix updates it openly
  rather than silently. Note the shipped sample led-003 is a
  hand-written ledger entry (labelled SAMPLE) showing the intended
  sliced-vs-full shape, not core import output.

## Canary record (required gate)

`tests/fixtures/proxy-report.json` plants one labelled fake value,
`api_key: "FAKE-LEDGER-CANARY-not-a-real-key"` (not a real
credential), in a Proxy-shaped entry. `test_import_proxy_report_
drops_credential_canary` imports it and asserts the ledger file
contains neither the canary value nor the string `api_key`. PASS.
The examples tree carries no credential-named field at all
(`test_no_credential_fields_anywhere_in_the_examples`).

## Manual spot run (outputs in /tmp, not shipped)

The examples demo exactly as written in `examples/README.md`:
Slice import 2 added, Proxy import 2 added, Bench import 2 added,
manual add at 3.6x prints the WARNING line, summary reports
7 entries / 85,970 total tokens / $0.0132 estimated cost and exits
1, report writes both files and exits 1. All figures matched the
documentation before it shipped.

## Assumptions, stated

1. **Alignment happened mid-build.** This build started before
   `~/workspace/ghostledger/` existed. Agent A's PLAN.md and core
   landed during the build; Agent B re-read the actual core
   (`cli.py`, `ledger.py`, `ingest.py`, `prices.py`, `report.py`,
   IMPLEMENTATION_A.md) and wrote the B side to the landed
   contract: global `--ledger`/`--prices` before the subcommand,
   commands `add` / `import` / `report` / `summary`, exit codes
   0/1/2 with 1 meaning loop-warning-present on report/summary,
   `report --json` writing no files, and the summarise() bucket
   keys. First aligned run: 29 passed; the docs-demo test brought
   the final total to 30 passed, 0 failed, 0 skipped.
2. The price rates used for hand-checks are the local snapshot's
   (claude-sonnet $3/$15 per Mtok in/out, as of 2026-10-12),
   reached by the core through its sibling-GhostSlice resolution
   before the bundled copy; both tables are identical at build
   time and carry the same date.
3. Sample files are hand-generated in the core's shapes and are
   labelled SAMPLE; the format tests (not the core) are what
   guarantee their internal consistency.

## Not covered / open for the parent

- The F1 `ts` fix and a follow-up day assertion for Proxy imports.
- Whether the Bench importer should learn `variants.sliced.tokens`
  in v0.1 or stay as the documented limit (F2).
- `--prices` with a user-edited table is documented but not
  exercised by a B-side test; the core resolves the sibling Slice
  table first in this workspace, so a custom-table test would need
  an isolated checkout layout to be meaningful.
