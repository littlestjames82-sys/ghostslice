# GhostLogs v0.1, Agent B report (tests, README, examples)

Ownership respected: everything below was written under `tests/**`,
`README.md`, `examples/**`, and this file. No edits to `src/**`,
`pyproject.toml`, or `PLAN.md`.

## Final result

**24 passed, 2 xfailed, 0 failed** against Agent A's real core
(`python3 -m pytest tests -q`, final run). The 2 xfails are strict:
each pins a genuine open defect (D1, D3 below) and will turn the
suite red as an XPASS the moment the core is fixed, forcing the
marker to be removed deliberately. A third defect (D2) was found
against the core as first landed and was fixed by Agent A mid-run;
its test now passes as a regression test.

Per file:
- `tests/test_fixtures_sanity.py`: 5 passed (no core needed; pins the
  fixture's ground truth)
- `tests/test_accounting.py`: 4 passed
- `tests/test_dedupe.py`: 2 passed, 1 xfailed (D1)
- `tests/test_secrets.py`: 4 passed
- `tests/test_budget_and_safety.py`: 5 passed, 1 xfailed (D3)
- `tests/test_error_windows_and_cli.py`: 4 passed

## Contract assumed, and alignment with the landed core

Tests were written fixture-first against the Wave 4 plan line, then
aligned once Agent A's `PLAN.md` and core landed. Entrypoint
discovery in `tests/conftest.py`, in order: `GHOSTLOGS_CMD` env
override, `ghostlogs` on PATH, `python -m ghostlogs` with
`PYTHONPATH=src`, installed package. No alignment edits to test
intent were needed; the landed contract matched the plan-level
assumptions:

- `ghostlogs pack <logfile> -o <pack-dir> [--budget <tokens>]`, plus
  `ghostlogs doctor`. Pack = `INCIDENT.md` + `manifest.json`.
- Manifest accounting lives in `manifest["counts"]` with
  `total_lines`, `kept`, `collapsed`, `dropped`,
  `dropped_by_reason`, and a `reconciles` flag; budget figures are
  top-level `budget_tokens` and `pack_estimated_tokens`. The conftest
  helpers accept these spellings among a documented candidate set and
  fail loudly with the manifest keys if none are present.
- Redaction placeholders are typed (`[REDACTED:aws-access-key]`,
  `[REDACTED:github-token]`), and the manifest records counts per
  shape under `redaction.counts`.

## Fixture

`tests/fixtures/noisy.log`, 70 lines, exact ground truth pinned by
`test_fixtures_sanity.py`: unique first and last anchor lines, one
heartbeat line x40, one cache WARN x12, one ERROR line x5 (first
occurrence inside a traceback window, 4 repeats that merge into the
same window), 13 unique lines, and two planted canaries: a
GitHub-token shape on a routine INFO line and an exact 20-char
AWS-access-key shape on an ERROR line inside the window (the plan's
own planted-secret bar).

## Hard rules, as pinned and verified

- Reconciliation: on the fixture at default budget the manifest reads
  70 = kept + collapsed + dropped exactly, and collapsed covers the
  routine repeat groups (heartbeat 39 + cache 11 = 50 minimum). The
  dropped-by-reason breakdown test (D2 regression) checks the
  breakdown sums at budgets 850 and 150.
- Secrets: neither canary, nor a long fragment of either, appears in
  any pack file, the manifest, stdout, or stderr (the test scans all
  of them). The manifest records `aws-access-key` by shape name, as
  the plan requires.
- Dedupe: heartbeat and cache-warn exemplars each appear exactly once
  in `INCIDENT.md`, with their true counts (40, 12) stated on the
  exemplar line; the manifest's duplicate groups carry the same
  counts with first and last line numbers.
- Budget: across budgets 500, 600, 850, 2000 the pack is never
  silently over budget (clean exit implies estimate at or under
  budget and `over_budget: false`; otherwise the manifest marks
  `over_budget: true` and the exit is nonzero). At budget 150 the
  over-budget path is exercised directly. At budget 500 the pack is
  strictly smaller than the default pack.
- Source safety: sha256 of the source log is identical after a run,
  and nothing is written beside the source except the named pack dir.
- CLI hygiene: missing input exits nonzero with no traceback; an
  empty log packs cleanly with all-zero accounting; `--help` works.

## Defects found (core code not touched by Agent B)

### D1, open, pinned as strict xfail: repeated ERROR lines get no counted exemplar
The plan's duplicate-collapse item and its planted-repeat bar
promise that a repeated error line shows as one exemplar with its
exact count. On the fixture, the 5 occurrences of
`ERROR db connection failed host=db1` produce no duplicate group:
`manifest["duplicates"]["groups"]` is 2 (heartbeat x40, cache x12
only). Inside the window, 3 of the repeats are collapsed in place
under a generic note ("3 consecutive repeated lines collapsed in
place inside this window"), so the true count 5 is stated nowhere in
the pack or the manifest; a reader must infer it from 2 shown copies
plus the note. Pinned by
`tests/test_dedupe.py::test_error_line_true_count_is_stated`.

### D2, fixed by Agent A mid-run, regression test now passes
Against the core as first landed (probed 09:31 ET), any pack with
dropped lines shipped a manifest whose `dropped_by_reason` did not
sum to `dropped` and which reported `reconciles: false`: at
`--budget 150`, dropped 68 vs reasons summing to 65; at
`--budget 800`, dropped 3 vs reasons summing to 0, exit 0. The plan's
bar is that the breakdown sums and "a pack whose counts do not
reconcile does not ship". Agent A patched `src/ghostlogs/pack.py`
and `analyze.py` (file mtimes 13:33 UTC, after the probes above), and
the behaviour is now correct at budgets 150, 800, and 850
(breakdown sums, `reconciles: true`). The test remains as
`tests/test_accounting.py::test_dropped_breakdown_sums_to_dropped`
without the xfail marker. Recorded here so the fix round is visible
in the history rather than silently absorbed.

### D3, open, pinned as strict xfail: budget tier selection overshoots when a fittable tier exists
At `--budget 600` the core emits the full error-window pack at an
estimated 825 tokens, marks it `over_budget`, and exits 1, although
a smaller tier that fits 600 demonstrably exists: at `--budget 500`
the core emits a pack estimated at 521. (Sweep on the fixture,
short path: 500 gives 521, 550 gives 784, 600 and 700 give 825, 850
gives 825 with exit 0.) The plan reserves the over-budget path for
when the mandatory anchors alone exceed the budget and says items
that do not fit are skipped and counted; at 600 the anchors are two
short lines, so a fittable selection should have shipped with exit
0. Pinned by
`tests/test_budget_and_safety.py::test_budget_600_lands_at_or_under_budget`.

### Observations, not defects
- The pack estimate counts `INCIDENT.md` as written, including the
  absolute source path in its header, so the same log estimates
  higher at a longer path (same content: 789 tokens at a short path
  vs 840 at a long pytest-style path). Documented in the README.
- Secret-shape matching is exact-length sensitive: during example
  preparation, a 22-char `AKIA`-prefixed string was not recognised
  as `aws-access-key`, while the exact 20-char shape is. Documented
  in the README's limits.

## Examples

`examples/billing-api.log` (33-line synthetic log: poll line x15,
warning x6, one gateway error window with traceback, one fake
exact-shape AWS key) and `examples/incident-pack/`, generated with
the real CLI at `--budget 2000`: 33 = kept 15 + collapsed 18 +
dropped 0, estimate 752, one redaction (`aws-access-key`), canary
absent from both pack files. `examples/README.md` walks through it.

## Gates held

Stdlib only, local only, no network use, no GitHub push, no PyPI or
publish step, no announcements, no spend. Defects were documented,
not fixed, in core code.
