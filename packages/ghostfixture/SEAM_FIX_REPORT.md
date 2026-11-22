# GhostFixture seam fix: upstream guard findings now propagate

Oct 14, 2026. Sole-owner fix round for the seam recorded in
~/workspace/ghostslice-companions/ECOSYSTEM.md (Seams #2): GhostSlice's
export guard records findings against bundled files, but GhostFixture
building from that bundle dropped the flags silently - a flagged file
was copied at full fidelity with no trace of the upstream flag in
Fixture's outputs. The two scanners disagree by design (Slice's guard
is name-based, Fixture's scan is shape-based); the seam was the
silence between them.

## Test counts

- Before: **39 passed, 0 failed** (parent-verified baseline, re-run
  at the start of this round).
- After: **43 passed, 0 failed** (two consecutive full runs).
- Added: 4 regression tests in `tests/test_upstream_findings.py`.
  No existing test was edited, weakened, or deleted. All 4 new tests
  verified to fail against the pre-fix code (run against the stale
  pre-fix copy in `build/lib/`, which has no upstream handling) and
  pass against the fixed code.
- Version stays **0.1.0**; stdlib only; no push, PyPI, publish,
  announcements, or spend.

## What the bundle actually records (verified against Slice v1.0.6)

The exact fields were learned from real exports, not assumed:

- A plain `ghostslice export` writes NO per-file findings into
  `manifest.json`; the guard's warning exists only on the export
  terminal. There is nothing in such a bundle to propagate, and
  this fix does not pretend otherwise (the manifest's limits text
  and the README both say so).
- An export with `--redact` records the guard's findings per file:
  each flagged entry gains `redactions` (count of values the guard
  flagged and replaced in that file) and `redaction_kinds` (the
  guard's finding types, e.g. `sensitive-assignment`,
  `aws-access-key`), plus a top-level `redaction` block.
  GhostConvert already reads the same per-file fields; this fix
  follows that suite precedent.
- The real disagreement case was reproduced first: GhostIndex's
  `src/ghostindex/store.py` line 52, `tokenize = 'unicode61'`
  inside an FTS5 schema string, is flagged by Slice's guard as
  `sensitive-assignment` (name contains "token"; value clears the
  length gate) and is not flagged by Fixture's shape scan. A real
  `--redact --mode full` export of a replica project produced the
  manifest records above, and the fixed Fixture was smoke-tested
  against that genuine bundle before the regression tests were
  written.

## The fix

- `bundle.py`: `BundleEntry` now carries `redactions` and
  `redaction_kinds`, parsed defensively, exposed as
  `entry.upstream_findings` (None when the bundle recorded none).
- `build.py`: for every candidate file with recorded upstream
  findings, Fixture still runs its own shape scan over the project
  original (its verdict stays sovereign):
  - Scan confirms (secret shape present): the file is excluded
    under the existing flagged-secret rules (or copied under
    `--include-flagged`, unchanged), and the `excluded_flagged`
    record now also names the upstream verdict
    (`upstream_kinds`, `upstream_redactions`,
    `upstream_confirmed: true`).
  - Scan does not confirm: the file is copied, and the
    disagreement is recorded three ways - on the included entry
    (`upstream_kinds`, `upstream_redactions`), in the manifest's
    new `upstream_disagreements` list (path, upstream kinds,
    upstream count, Fixture's empty type list), and in FIXTURE.md
    (below). If the copy is then refused by the size cap, the
    flag stays attached to the `left_out` record instead of
    becoming a disagreement; the same attachment covers
    missing/unreadable/escaping left-out paths, so no outcome
    drops the flag.
  - Totals gain `files_upstream_flagged` (recorded files that
    reached the scan) and `files_upstream_disagreements`.
  - A new manifest limits line states the propagation rule and
    its boundary (plain exports record nothing to propagate).
- `reports.py`: FIXTURE.md gains the named section
  "## Upstream guard findings not confirmed by the shape scan"
  (rendered only when disagreements exist), explaining both
  verdicts and why the files were still copied, plus a summary
  line in the header block. Exclusion lines for confirmed files
  note "also flagged by the bundle's guard (...) - both scanners
  agree".
- `cli.py`: one additive line when disagreements exist
  ("upstream disagreement: N copied file(s) were flagged by the
  bundle's guard but not confirmed by the shape scan ...").
  `mcp_server.py`: the build summary now includes
  `upstream_disagreements` next to `excluded_flagged`.
- `README.md`: a new rule bullet ("Guard findings recorded in
  the bundle are propagated") and the manifest description in
  "What you get" now names `upstream_disagreements[]`.

Files with no upstream findings behave exactly as before: every
new field, record key, and output line is gated on a recorded
finding existing for that file or build, and all 39 pre-existing
tests pass unmodified. (The manifest does always gain the new
`upstream_disagreements` key as an empty list and the two new
totals counters at 0, mirroring how the polish round's `drift`
records are always present.)

## Regression tests (tests/test_upstream_findings.py)

Black-box CLI tests in the suite's existing style; the bundles
they build replicate a real Slice `--redact` manifest shape
(per-file `redactions`/`redaction_kinds`, top-level `redaction`
block, honest sha256s):

1. `test_disagreement_copied_and_recorded_everywhere` - the real
   FTS5 `tokenize = 'unicode61'` case, flagged upstream as
   `sensitive-assignment`: file copied byte-identical, one
   disagreement record with the upstream kinds, the included
   entry annotated, the clean control file unannotated,
   FIXTURE.md's named section present naming file and kind,
   CLI line present, `ghostfixture check` clean.
2. `test_confirmed_upstream_flag_excluded_with_both_verdicts` -
   an AWS-shaped canary flagged upstream as `aws-access-key` and
   confirmed by the shape scan: excluded, exclusion record names
   both verdicts, not a disagreement, `files_upstream_flagged`
   is 2, canary absent from every output byte and the CLI output.
3. `test_override_copy_keeps_both_records_no_disagreement` -
   with `--include-flagged`, the confirmed file is copied by
   override and both records stay; the only disagreement is the
   unconfirmed file.
4. `test_no_upstream_records_behaves_exactly_as_before` - a
   bundle with no guard records: no disagreement list entries,
   no upstream keys on any record, no FIXTURE.md section, no CLI
   line; the shape scan's standalone verdicts are unchanged
   (secret-shaped file excluded, benign file copied).

One correction made during the round: the first draft of test 2
asserted an empty disagreement list for the whole build, but the
fixture bundle also contains the (correctly disagreeing)
store.py; the assertion now pins that the confirmed file is not
among the disagreements. The fix's behaviour was never in
question; the test's expectation was.

## Live smoke evidence (real Slice bundle, replica of the seam case)

`ghostfixture build` on a genuine `ghostslice export --redact
--mode full` bundle: store.py copied with 1 disagreement recorded
(kinds `sensitive-assignment`), keys.py excluded with
`upstream_confirmed: true`, CLI printed the upstream
disagreement line, `ghostfixture check` OK. The drift warning
that also fired on store.py is correct pre-existing behaviour:
Slice's recorded sha256 is over its redacted bundle text, so the
project original differs from it, which the drift section's
wording already covers ("or the bundle text was transformed").

## Deliberately left alone

- Slice's stderr-only warnings on plain exports: not recorded in
  any artifact, so there is nothing downstream to read. Recording
  them is a GhostSlice-side decision, not something Fixture can
  reconstruct without becoming a second name-based guard (which
  would erase the by-design disagreement this fix surfaces).
- The top-level `redaction` block's `left_in_place` leftovers:
  kinds only, no per-file paths, so they cannot be attributed to
  a file honestly; per-file records are the propagation channel.
- Bundle entries at mode `exclude`: already never copied and
  already recorded as bundle-excluded; exclusion dominates any
  flag.
- `check_fixture`: unchanged. Disagreement files are ordinary
  included files (present, hash-verified); confirmed exclusions
  are verified absent by the existing excluded-flagged check.
- PLAN.md, version, gates: untouched.
