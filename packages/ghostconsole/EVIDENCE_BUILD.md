# EVIDENCE_BUILD.md - GhostConsole half of the shared evidence contract

Built Oct 18, 2026 in the real tree (`~/workspace/ghostconsole`), from
`~/workspace/ghostslice-companions/EVIDENCE_CONTRACT_DRAFT.md` (Console
rules), consuming the field shapes GhostBench just landed
(`~/workspace/ghostbench/EVIDENCE_BUILD.md`): top-level
`verification_level`, `provenance` (`"live"` / `"sample"`),
`tool_version`, `tier`, `honest_scope` on bench-report.json.
Version stays 0.1.0. Stdlib only. No existing test was weakened or
deleted; 11 tests were added. Nothing pushed or published.

## Sanity gate: the four known-answer cases, pre / post

Probed before any code change with a synthetic project whose ONLY
report is a Bench report at a live path (`runs/bench-report.json`),
then re-probed after, and encoded permanently as tests in
`tests/test_evidence_contract.py`.

| # | Case | Pre-change behavior | Post-change behavior |
|---|------|---------------------|----------------------|
| 1 | Only live evidence is Bench `verification_level: "static-analysis"` | **Verified**, reason just "latest reports ok and inside the 7 day stale window"; level appeared nowhere (section JSON had no level field at all) | **Verified**, reason: "latest reports ok and inside the 7 day stale window; strongest verification level: static-analysis (static only: no tests executed, no live run); 10 of 11 checks missing (no live report)". Bench row carries `verification_level: "static-analysis"`, `tool_version: "0.1.0"`, summary "run probe-1: 2 task(s) (ghostbench 0.1.0)" |
| 2 | Same, `verification_level: "tests-executed"` | **Verified**, identical generic reason; indistinguishable from case 1 | **Verified**, reason names the level: "strongest verification level: tests-executed (the project's own tests were actually run); 10 of 11 checks missing (no live report)" |
| 3 | Bench report declaring `provenance: "sample"` at a LIVE path (`runs/`, not under examples/) | **Verified as live evidence** - the report's own sample declaration was ignored; only its path was consulted | Section provenance is **"sample"** regardless of path, summary labelled "(sample report)", project lands in **Stale** with reason "no live reports found (1 sample report(s) on the card, labelled, not counted)". A sample report with a failing task likewise cannot place a project in Attention (its row still shows state attention - the evidence is kept, not hidden) |
| 4 | Bench report with NO `verification_level` (all pre-contract reports) | No level field existed; reason claimed an unqualified Verified | Section JSON carries `verification_level: null` and `tool_version: null`; the row renders no level; the Verified reason says "verification level not stated by any live report" - a level is never invented. An unrecognized level value ("certified-gold") is treated the same way |

Cross-check with the real artifact: GhostBench's shipped sample
(`examples/runs/sample-tier-a-run-a/bench-report.json`, failing task
included) copied to a live path renders as provenance "sample",
level "static-analysis", version "0.1.0", and the project sits in
Stale - not Attention, not Verified.

## What was implemented

### 1. Model (`src/ghostconsole/model.py`)

- `Section` gains `verification_level: str | None` and
  `tool_version: str | None`, both included in `to_dict()` (null
  when unstated).
- Contract constants: `VERIFICATION_LEVELS` ordered
  `none < static-analysis < tests-executed < live-agent` with
  `LEVEL_RANK`, plain-word descriptions (`LEVEL_PLAIN`), and
  `strongest_level(sections)` - the strongest STATED level, where
  an unrecognized value is not a level and never wins.
- Provenance vocabulary documented as `live` / `fixture` /
  `sample`; fixture and sample are both non-live.

### 2. Adapters (`src/ghostconsole/adapters.py`)

- New tolerant readers: `_stated_level` (string in the enum only),
  `_stated_version` (non-empty string only), `_apply_evidence`
  (carries stated fields onto a section; absent stays None), and
  `_mark_sample` (provenance "sample" + "(sample report)" summary
  label).
- Bench adapter: reads `verification_level`, `provenance`,
  `tool_version` from bench-report.json. The report's own
  `provenance: "sample"` overrides its path, live paths included.
  `tool_version` shows in the row summary as "(ghostbench 0.1.0)".
  History lines (`.ghostbench-history.jsonl`) carry the level too
  when the line states one (Bench's ledger record now writes it).
- Verify (report + history), Watch, and Ledger adapters apply the
  same stated-fields rule: they read `verification_level` /
  `tool_version` only when the report object actually carries
  them, and leave both unstated otherwise. No adapter infers a
  level from any other field (a tier string is not a level).

### 3. Classification (`src/ghostconsole/collect.py`)

- Sample sections, like fixture sections, never place a project and
  never feed the freshness clock (the clock already keyed on
  `provenance == "live"`; sample inherits that exclusion).
- The no-live-evidence Stale reason now counts sample reports
  alongside fixture/example ones, each named.
- `_verified_reason`: a Verified placement reason now always
  (a) names the strongest verification level among LIVE sections -
  static-analysis gets the explicit "(static only: no tests
  executed, no live run)", and when no live section states a level
  the reason says "verification level not stated by any live
  report" - and (b) counts missing checks as
  "N of 11 checks missing (no live report)", where a row whose only
  evidence is fixture/sample counts as missing. Attention and Stale
  (age/verdict) reasons are unchanged.

### 4. Renderers (`src/ghostconsole/render.py`)

- `LEVEL_LEGEND`: one plain-words line in the HTML header and the
  text summary - "Verification levels: static-analysis = static
  analysis only (no code executed, no agent ran); tests-executed =
  the project's own tests were actually run; live-agent = a real
  agent attempted the real task. A level appears on a row only when
  the report states one; ..."
- Every row that has a stated level shows it: `level: <level>` in
  the HTML meta and as `| level: <level>` in the text summary.
  Rows without a stated level show nothing - no fabricated label.
  The JSON model carries the fields (null when unstated).

## Files changed

- `src/ghostconsole/model.py` - level enum/rank/plain words,
  `strongest_level`, new Section fields in `to_dict()`.
- `src/ghostconsole/adapters.py` - stated-field readers, Bench
  contract fields + declared-sample override + version in summary,
  stated fields applied in Verify/Watch/Ledger where carried.
- `src/ghostconsole/collect.py` - sample in classification,
  `_verified_reason` (strongest level + missing-check count),
  sample counted in the no-live-evidence reason.
- `src/ghostconsole/render.py` - level legend (HTML + text),
  per-row level display (HTML + text).
- `tests/test_evidence_contract.py` - NEW, 11 tests (the four
  sanity cases, sample-with-failure, unrecognized level, strongest
  across sections, fixture level excluded from strongest, Bench
  history level, HTML/text rendering + legend, no-level row).
- `EVIDENCE_BUILD.md` - this file.

## Final test run

```
$ cd ~/workspace/ghostconsole && PYTHONPATH=src python3 -m pytest tests -q
90 passed in 7.61s
```

Baseline was 79 passed; 79 + 11 new = 90, zero regressions.

## Limitations / notes

1. **Only GhostBench emits the contract fields today.** Verify,
   Watch, and Ledger sections will stay level-unstated until those
   tools' writers land their half; Console renders that honestly
   ("not stated") rather than guessing, per the contract.
2. **Commit / tree hash are not surfaced.** Bench rows carry
   per-task `project_commit` / `project_tree_hash`, but a Bench
   report covers several projects/tasks and has no single top-level
   commit; inventing a per-section value from one row would misstate
   the rest, so the section leaves it out until Bench states a
   report-level value.
3. **Declared provenance other than "sample" is not honoured.**
   A report claiming `provenance: "live"` for itself gains nothing:
   path-based fixture classification still wins, so shipped sample
   material cannot promote itself by declaration. Only the
   downgrade (live path, declared sample) is taken at the report's
   word - the safe direction.
4. **RESULTS.md (contract step 3) was not created** - shared with
   the GhostBench half and outside this task's deliverables, same
   as noted in GhostBench's EVIDENCE_BUILD.md.
