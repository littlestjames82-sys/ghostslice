# GhostConsole - Test Results

Reproducible record of a full-suite run. Regenerate on every
release-grade change; counts quoted anywhere else must match this
file or be removed.

## Run of Oct 19, 2026 (GhostWorkflow adapter)

- Date (UTC): 2026-10-19T02:39Z
- Platform: Linux 7.0.0-39-generic x86_64
- Python: 3.12.3
- pytest: 9.1.1
- Tree: ghostconsole v0.1.0 + GhostWorkflow adapter, working tree
  (not yet pushed when this section was written)
- Command:

```sh
cd ghostconsole
PYTHONPATH=src python3 -m pytest tests -q
```

- Result: **103 passed** (90 before this change; +13 in
  tests/test_workflow_adapter.py). Three count assertions in
  tests/test_evidence_contract.py moved with the row count (the
  board now has 12 tool rows: "11 of 12 checks missing"), and
  conftest's healthy_project fixture gained a workflow run, keeping
  its "every adapter present" contract.

## What the adapter does

Discovery is scoped to the one layout ghostworkflow writes:
`.ghostworkflow/<run-id>/workflow-report.json`, newest run first
(the shared bounded walk, mtime order, corrupt-newest falls back to
an older valid run, corrupt-only is an unreadable row). Verdicts map
from the writer's vocabulary: ok -> ok, attention -> attention,
failed -> attention (as with GhostVerify's "failed"). The row
carries the run id, per-step outcomes, the report's stated
verification_level and tool_version, and its tree_hash when it
states one (null stays unstated, never invented). The row's source
is the `board.html` the run rendered beside its report, falling
back to the report path when no board sits there. A workflow report
counts as live evidence like any other tool's: an ok run at
tests-executed supports Verified with the level named in the
reason; an attention run places the project in Attention. The
report's `provenance` field is not read (the writer's schema fixes
it to "live"); workflow reports are never treated as samples.

## Dogfood proof (same day)

Board built over a copy of the real GhostBench tree carrying the
Oct 19, 2026 dogfood run wf-20261019T021405Z-4f7aba (report and
board restored from the durable copies in
ghost-recruit-pack/demo2/; /tmp had been wiped). Project column:
attention. Column reason, verbatim: "Workflow verdict: attention".
Workflow row, verbatim summary: "run wf-20261019T021405Z-4f7aba:
verdict attention; steps: slice ok, verify attention, bench
attention, console ok; tree_hash
sha256:df6bbacd57f4edd0917d1365a16c9344131dc379eba1c00e7efb1425bff9bcb8
(ghostworkflow 0.1.0)", level tests-executed, source
`.ghostworkflow/wf-20261019T021405Z-4f7aba/board.html`. Link check:
the board was written to /tmp/dogfood2/board.html; card path +
row source resolves to the run's real board.html on disk.

## Known limits after this run

- The Oct 18 known limit on tree hashes is closed for workflow
  reports only: a workflow row surfaces its report's tree_hash.
  Bench reports remain multi-project with no report-level hash, as
  recorded below.

## Run of Oct 18, 2026 (evidence-contract build)

- Date (UTC): 2026-10-18T20:50Z
- Platform: Linux 7.0.0-39-generic x86_64
- Python: 3.12.3
- pytest: 9.1.1
- Tree: ghostconsole v0.1.0, evidence-contract build
  (verification_level consumption, honest Verified reasons),
  working tree identical to the GitHub push that carries this file
- Command:

```sh
cd ghostconsole
PYTHONPATH=src python3 -m pytest tests -q
```

- Result: **90 passed** (7.78s)

## Evidence-contract probes (known-answer set, in the suite)

`tests/test_evidence_contract.py` (11 tests) encodes the sanity gate:
static-only live evidence places a project in Verified only with a
reason naming `static-analysis` as static only and counting missing
checks; `tests-executed` is named when it is the strongest level; a
Bench report declaring `provenance: "sample"` at a live path is
labelled sample and never places the project; a report with no
`verification_level` renders the level as not stated, and an
unrecognized level value is treated as unstated, never accepted.
Parent re-verification on Oct 18, 2026 reproduced the static-only and
sample cases on synthetic projects through the CLI: Verified reason
read "strongest verification level: static-analysis (static only: no
tests executed, no live run); 10 of 11 checks missing (no live
report)", and the sample project landed in Stale with its sample
report labelled, not counted.

## Known limits of this run

- Only GhostBench emits the contract fields today
  (`verification_level`, `provenance`, `tool_version`). Rows for
  other tools honestly render the level as not stated until their
  writers land.
- Per-report commit/tree hash is not surfaced: Bench reports are
  multi-project with no report-level commit, and Console does not
  invent one from a single task row.
