# GhostConsole v0.1 - Polish Report (Oct 14, 2026)

Polish round at Ryan's "Polishing", after Wave 4 parent verification
(18 tests passing). Sole folder ownership for this round. House loop:
audit first (PLAN.md, IMPLEMENTATION_A.md, REPORT_B.md, the core, and
the shipped sibling tools' own writers), then improve only what a
fixture proved better. No version bump: pyproject still says 0.1.0,
releases stay Ryan-gated, polish is in-tree only.

## Test counts

- Before: 18 passed, 0 failed (`python3 -m pytest tests -q`).
- After: **32 passed, 0 failed**. 14 tests added in
  `tests/test_polish.py`; no existing test was edited, weakened, or
  deleted, and the 18 original tests pass unchanged.

## What changed (all in src/ghostconsole/adapters.py)

### 1. Verdict matching: substring -> exact per-format vocabularies

The old matcher tested substrings (`_PASS_LIKE` / `_FAIL_LIKE`: any of
"sufficient/pass/clean/ok" vs "insufficient/fail/gap/error/missing"
anywhere in the word). Grounded against the vocabularies the shipped
siblings actually write (GhostVerify core.py / reports.py, GhostBench
runner.py), two real values matched no substring at all and fell
through to an ok row marked "(verdict wording not recognized)":

- GhostVerify verdict `could_not_verify` (a check that did not
  complete; GhostVerify returns a passing verdict only on positive
  evidence, and this value carries exit code 2) rendered as ok, in
  the report path and in the history path.
- GhostVerify patch verdict `flagged` (findings present, exit code 1)
  rendered as ok.

Before-state, on identical fixtures run against the pre-polish core:
both projects landed in the **Verified** column. After: both land in
**Attention**, with the verdict named in the reason.

Fix: `_verdict_state` (Verify report, post, and history verdicts) and
a new `_bench_status_state` (Bench task statuses) now share
`_exact_state`, an exact whole-word match (after strip + lower)
against frozen vocabularies taken from the sibling writers:

- Verify ok: `sufficient`, `sufficient_after_expand`, `ok`.
  Verify attention: `insufficient` (the documented plan-level word),
  `gaps_found`, `gaps_remain`, `could_not_verify`, `failed`, `flagged`.
- Bench failing: `fail`, `failed`. Bench ok: `pass`, `passed`.
  Bench's `unknown` is in neither set on purpose: Bench counts it
  separately from failures in its own tallies, so it never counts as
  failing here either (pinned by a new test).

Anything outside the known vocabulary returns None exactly as before:
the wording is shown verbatim on the row with "(verdict wording not
recognized)" and never guessed at (pinned by a new test using a
nonsense verdict). All previously pinned words (`sufficient`,
`gaps_found`, Bench fixture `passed`/`failed`, real `pass`/`fail`)
classify identically to before.

### 2. GhostApprove: stores are now found nested, not only at the root

`approve_section` used to look only at `<project>/.ghostapprove/` (or
the `--approve-store` card). A store one level down, for example
`sub/.ghostapprove/`, was invisible: before-state fixture showed the
GhostApprove row absent and the project in Stale while a request sat
pending. Fix:

- The project-root store still wins unchanged when present (pinned by
  a new test: a clear root store beats a pending nested one, so the
  v0.1 single-store wording and semantics are byte-identical).
- With no root store, `_find_store_dirs` runs the same bounded search
  discipline as the file adapters (depth cap MAX_DEPTH, SKIP_DIRS
  pruned, symlinks not followed or read, stores not descended into).
  One nested store renders exactly like a root store, with its real
  relative path as the source. Several nested stores aggregate into
  one section: pending and totals are summed, decisions are resolved
  against each store's own ledger, risks are unioned, and the summary
  says "across N nested store(s)" with every store path named (first
  two plus a count when there are more than three).
- Stores inside skipped directories (`node_modules`) or beyond the
  depth bound are not found; both bounds are pinned by new tests.

Per-store reading was factored into `_store_facts`, shared by the
root, `--approve-store`, single-nested, and aggregated paths, so the
four routes cannot drift apart.

### 3. GhostApprove: pending risks now read from the real record shape

IMPLEMENTATION_A claimed the pending summary "names the risk values
present", but the code read `risk` only at the top level of a request
record. GhostApprove's real record shape nests it:
`{"id", "hash", "ingested_at", "content": {"risk": ...}}`, so on a
real store no risk was ever named (before-state fixture: root store
with content risk "critical" summarized as "1 pending of 1
request(s)" with no risk). `_record_risk` now reads the top level
first (the suite fixture shape) and falls back to `content.risk`
(the shipped shape); the after-state summary reads "1 pending of 1
request(s) (risk: critical)". Pinned by new tests on both the root
and nested paths.

## Real-data check (the plan's self bar)

Board summary over the suite's own seven repos (ghostslice,
ghostverify, ghostbench, ghostscope, ghostledger, ghostwatch,
ghostapprove) matches the pre-polish hand check in
IMPLEMENTATION_A.md exactly: ghostslice verified, ghostbench in
Attention (its on-disk SAMPLE-run-b report genuinely has 1 failing
task, still caught under the exact Bench vocabulary), the rest
verified, ghostapprove Stale with "no reports found" (that tree
contains no Approve store anywhere, so nested discovery changed
nothing there). The committed examples board also rebuilds with
identical column counts (1 verified, 1 attention, 2 stale);
examples/board.html was not regenerated, as only its generated-at
timestamp would change.

## Deliberately left alone

- The Approve ledger decision scan (substring over the ledger row's
  event/type/decision/action_taken fields). Checked against the
  shipped GhostApprove store: decisions are exactly the events
  "approved" / "denied", ingests are "ingested", and no real row
  shape could be constructed where the substring scan mis-decides a
  request. No proven misclassification, no change.
- GhostWatch verdict handling: already an exact comparison against
  "fresh", with anything else landing in Stale rather than ok.
- Bench history fallback reading a `failed` field: documented
  behaviour in IMPLEMENTATION_A.md (a history line without the field
  makes no failure claim). Not a verdict-vocabulary issue.
- README.md and examples/: no statement in either became false.
  README never claimed root-only store lookup, and its "unrecognized
  verdict wording is noted on the row" line is still exactly true.
- Depths, caps, skip lists, renderers, CLI, and the classification
  precedence: untouched.
- Version: still 0.1.0 everywhere. No push, no PyPI, no announcements,
  no spend. Stdlib only, local only, no sibling tool executed at any
  point (all fixtures are hand-written files, including the
  before/after demonstrations).
