# GhostConsole - Seam Fix Report (Oct 14, 2026)

Fix round for seams 3 and 4 from the ecosystem pass record
(~/workspace/ghostslice-companions/ECOSYSTEM.md), found during the
live board run over all 34 suite projects
(~/workspace/ghostslice-companions/ecosystem/runs/meta/console/).
Sole folder ownership for this round. No version bump: still 0.1.0.
Stdlib only, local only, no push, no PyPI, no announcements, no spend.

## Test counts

- Before: **32 passed, 0 failed** (`python3 -m pytest tests -q`).
- After: **54 passed, 0 failed**. 22 tests added in
  `tests/test_seam_fixes.py`; no existing test was edited, weakened,
  or deleted, and all 32 pre-existing tests pass unchanged.

## Seam 3: fixture/example reports no longer wear live clothing

Problem (as recorded in ECOSYSTEM.md): Console discovered reports by
file name anywhere under a project, so reports a project ships as
test/example material counted as its live state. On the full-suite
board, all 3 Attention rows were fixture reports, and the same defect
flattered other projects into Verified on sample material alone.

Design: every discovered report now carries a **provenance**,
recorded on the section and in the JSON model (`"provenance"`).

- `adapters._provenance(path, project)`: a report whose project
  relative path passes through a test, fixture, or example directory
  segment (`test`, `tests`, `testing`, `example`, `examples`,
  `fixture`, `fixtures`, `sample`, `samples`, `testdata`,
  `test-data`, `snapshots`, or any segment containing "fixture",
  which covers `fixture_reports` and `__fixtures__`) is "fixture";
  anything else, including root-level files, is "live".
- Adapters search **live paths first** (`pick_report_two_pass`, and
  `find_newest(..., provenance=...)`); fixture paths are consulted
  only when no live file with that name exists at all. A live
  corrupt report still wins over fixture material: it is the
  project's real state and is never masked.
- A fixture-derived section keeps its parsed state as evidence (a
  failing sample run still reads "attention" on its row) but is
  labelled "(fixture/example report)" in its summary, so the label
  shows in HTML, text, and JSON alike.
- `collect.classify` places projects on **live sections only**.
  Fixture sections never drive Attention, Stale, or Verified, and no
  longer feed the newest-evidence clock (a fresh fixture cannot make
  a quiet project look current). A project with fixture evidence but
  no live reports lands in Stale with the reason on its face:
  "no live reports found (N fixture/example report(s) on the card,
  labelled, not counted)".
- GhostApprove nested stores are partitioned by the same rule: live
  stores aggregate as before; fixture stores fall back to a labelled
  fixture section when no live store exists, and when both exist the
  live section's summary states the fixture store count that was not
  counted.

Pinned by 8 new tests, including the ecosystem board's exact shapes
(failing Verify under `tests/fixtures/reports/`, failing Bench under
`examples/runs/`), live-wins-over-newer-fixture for the same tool, a
real failing live report still landing in Attention amid fixture
noise, fixture unreadable and fixture pending-approval cases not
placing the project, and fresh fixture evidence not defeating age
staleness.

## Seam 4: four Wave 4 adapters

New adapters (appended to `collect.ADAPTERS`), each reading only the
sibling's documented, shipped format, grounded in the siblings'
READMEs and real outputs under the ecosystem runs:

- **GhostHandoff** (`handoff.json`, shape: `tool == "ghosthandoff"`
  or the documented open_loops/session_window fields). Row states
  the session: branch@short-head, uncommitted change count from the
  pack's own status counts, open loop count, next step count. A pack
  is a snapshot with no pass/fail vocabulary, so a parseable pack is
  an ok row; it never drives Attention on its own (the failing
  evidence a pack quotes is read by its own adapter when that file
  is discoverable). Corrupt pack: unreadable row, Attention, as with
  every live report.
- **GhostLogs** (incident pack `manifest.json`, shape: `tool ==
  "ghostlogs"` or counts carrying `total_lines` + `reconciles`).
  Row states line accounting (total, kept, collapsed, dropped),
  error windows emitted, estimated vs budget tokens with the tier
  when the manifest records one, and the redaction count.
  Attention when the pack shipped `over_budget`, or when its counts
  record `reconciles: false`.
- **GhostDeps** (`deps-manifest.json`, shape: `tool == "ghostdeps"`
  or the documented counts keys). Row states declared / imported /
  declared-not-imported counts and pins recorded. Imported but not
  declared drives Attention (the Ledger loop-warning analogue);
  declared but not imported is stated only, because GhostDeps' own
  manifest notes call it "a lead for a human, not a verdict".
- **GhostData** (pack `manifest.json`, shape: `tool == "ghostdata"`
  or counts carrying `rows_parsed` beside a columns list). Row
  states source file and format, rows parsed of total, malformed
  rows, column count, and redacted column count; a pack with
  redaction disabled says so. Malformed source rows drive Attention.

The bare name `manifest.json` is shared by Slice bundles, Logs
packs, and Data packs, so Logs and Data claim a manifest **only by
parsed shape**, and claim a corrupt one only when the pack's
companion file sits beside it (`INCIDENT.md` for Logs, `PROMPT.md`
for Data; both packs always ship the pair). A corrupt manifest
without the companion belongs to some other tool's pack and neither
adapter reports it. Anything outside the documented shapes stays
unrecognized and unguessed, exactly like verdict wording.

Absent rows for the four new adapters name the artifact they look
for ("no handoff pack found", "no incident pack found", "no deps
pack found", "no data pack found") instead of the generic "no report
found"; that is also what keeps the pre-existing healthy-project
summary invariant (no absent wording when every original tool is
present) true with four more rows on the card.

Pinned by 14 new tests with real-shaped fixtures: Handoff with and
without git state, corrupt Handoff; Logs ok / over-budget /
unreconciled; the ambiguous corrupt manifest claimed by Logs only
with INCIDENT.md beside it and by Data never without PROMPT.md;
Deps gap vs lead; Data clean vs malformed; a Slice bundle manifest
claimed by neither Logs nor Data; absent rows on an empty project;
and hostile file strings (a script-shaped branch name) escaping
through a new adapter's summary.

## Demonstration: the fixed board over the suite's own repos

Same 34 project paths as the ecosystem run, same command, fixed code:

- Before: **9 Verified, 3 Attention, 22 Stale**.
- After: **2 Verified, 1 Attention, 31 Stale**.

Every movement is accounted for:

- The 3 fixture-driven Attention rows are gone from Attention.
  ghostbench (Bench sample run under `examples/runs/`), ghostreview
  (Verify report under `tests/fixtures/reports/`), and ghostconsole
  (its own `examples/fixture_reports/` set) now sit in Stale with
  "no live reports found (N fixture/example report(s) on the card,
  labelled, not counted)", their fixture rows still on the card,
  labelled, states intact as evidence.
- 7 projects the old board called Verified were verified by shipped
  sample material only: ghostscope (`examples/sample_pack/`),
  ghostwatch (`examples/fixture-bundle/`), ghostledger
  (`tests/fixtures/bench-report.json`), ghostconvert, ghostreplay,
  ghostshard, ghostfixture (all `examples/` sample bundles). They
  now read Stale with the same stated reason. The seam cut both
  ways; the fix removes the flattery too.
- ghostlogs moved Stale to Attention on **live** evidence that did
  not exist when the before board was built: the emergent
  workstream's Fixture-to-Verify run wrote
  `~/workspace/ghostlogs/.ghostverify-history.jsonl` at 14:06 (after
  the ~14:03 board) with latest verdict `gaps_found`. The fixed
  board surfaces it, which is the board working as designed. Its
  GhostLogs row is the shipped example pack, labelled fixture.
- The new adapters read real packs where projects ship them as
  examples (GhostLogs' incident pack, GhostData's events pack), all
  correctly labelled fixture. No project tree contains a live
  Handoff, Deps, or Data pack today (the ecosystem runs wrote those
  to the runs area), so those rows are absent there, as they should
  be.

`examples/board.html` was regenerated via `examples/run_demo.sh`:
identical column counts (1 verified, 1 attention, 2 stale), with the
four new rows on every card; the demo projects are passed as roots,
so their reports are live relative to each project and provenance
changes nothing there. README.md was updated to match (adapters,
provenance rule, manifest collision rule).

## Deliberately left alone

- Verdict matching: untouched. The polish round's exact per-format
  vocabularies (`_exact_state` and its frozen sets) are exactly as
  they were; the new adapters introduce no verdict words at all
  (Handoff has none; Logs, Deps, and Data states come from
  documented boolean/count fields, not wording).
- Renderers: untouched. The fixture label rides in the section
  summary and the JSON model carries `provenance`; no new markup,
  no new CSS, still zero scripts and zero external references
  (pinned by the existing offline bar and a new hostile-content
  test through the Handoff adapter).
- Root-level history files (Slice, Verify, Bench, Ledger) and the
  root Approve store: live by construction, read exactly as before.
- Classification precedence, stale window, depths, caps, skip lists:
  unchanged. The only classifier change is which sections count as
  evidence (live ones), which is the seam itself.
- Version: 0.1.0 in pyproject and `__init__`, unchanged.
