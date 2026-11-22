# GhostHandoff v0.1 - Polish Report

Date: Oct 14, 2026. One polish round at Ryan's "Polishing", run by a
single agent as sole owner of this folder. House loop: audit first
(PLAN.md, IMPLEMENTATION_A.md, REPORT_B.md, all of src/), demonstrate
each defect before fixing it, add regression tests, keep the whole
suite green. No version bump (still 0.1.0 in pyproject.toml and
`__init__.py`); releases stay Ryan-gated. Stdlib only, local only,
nothing pushed, published, announced, or spent.

## Test counts

- Before: **29 passed, 0 failed** (`python3 -m pytest tests -q`,
  24.79s, matching the parent-verified baseline).
- After: **35 passed, 0 failed** (22.83s). All 29 pre-existing tests
  pass unmodified; no existing assertion was weakened, edited, or
  deleted. The 6 new tests live in `tests/test_marker_context.py`.

## Change 1: documentation/fixture markers no longer manufacture loops

The documented v0.1 limit was that marker scans have false
positives: markers inside docs and fixtures match. The audit showed
the cost was worse than noise in a list. Open loops and next steps
are derived from the raw marker total, so documentation quoting a
marker became drafted work for the next session.

Demonstrated before the fix, on a project with zero code markers
(clean `main.py`; markers only in `docs/guide.md`, `README.md`,
`fixtures/sample.py`):

```text
markers total: 5 by_kind: {'TODO': 4, 'FIXME': 1}
open_loops:
 - open-markers | 5 open marker(s) (FIXME 1, TODO 4)
next_steps:
 - Address FIXME markers first (1 open); the first listed is at docs/guide.md:5.
 - Work through the TODO markers (4 open); the first listed is at README.md:3.
```

The fix splits markers by context, conservatively:

- `src/ghosthandoff/scan.py` gains `marker_context()`: a file is
  `"docs"` only for an unambiguous documentation or fixture
  location: a `docs` / `doc` / `documentation` or `fixtures` /
  `fixture` / `testdata` / `test_data` / `__fixtures__` directory
  segment, or a documentation extension (.md, .markdown, .rst,
  .adoc). Everything else is `"code"`. Plain `.txt` is deliberately
  NOT down-weighted (a notes file can hold real work), and a code
  file merely named `docs.py` stays code. Both edges are pinned by
  tests.
- Each marker item gains a `"context"` field; the markers section
  gains `code_total`, `docs_total`, `code_by_kind`, `docs_by_kind`.
  `total` and `by_kind` keep their old meaning (grand totals), so
  the CLI summary and MCP payload semantics are unchanged.
- `pack.py` `derive_open_loops`: the open-markers loop fires only
  on code-context markers, and its detail says so, e.g.
  "1 open marker(s) in code (TODO 1); 2 more marker(s) sit in
  documentation or fixture files: listed in the Markers section,
  not counted as open loops".
- `derive_next_steps`: marker steps use code counts only, and the
  cited "first listed" marker is the first code one, never a docs
  mention. A docs-only FIXME no longer produces "Address FIXME
  markers first".
- `render_markdown`: the Markers section states the split on the
  pack's face ("Only the code ones are counted as open loops
  above; the others are listed here so nothing is hidden") and
  annotates docs items "(documentation/fixture)". Every marker is
  still listed with file and line: nothing is hidden, it just
  stops being counted as unfinished work.
- The pack's own limits line and README (Open loops section and
  Honest limits) were updated to state the new rule; both were
  stale the moment the behaviour changed.

Demonstrated after the fix, same two projects:

```text
DOCS-ONLY PROJECT: total 5, code_total 0, docs_total 5
  open_loops: []   next_steps: []
MIXED PROJECT (1 code TODO + 2 docs markers): total 3, code 1, docs 2
  loop: open-markers | 1 open marker(s) in code (TODO 1); 2 more ...
  step: Work through the TODO markers (1 open); the first listed is at app.py:3.
```

Regression anchor: the PLAN fixture repo's 3 markers are all in
code files, so its arithmetic is untouched (code_total 3,
docs_total 0, still exactly 5 loops), pinned by a new test
alongside the pre-existing no-invention test.

## Change 2: the marker scan's file-list cap is now stated, not silent

PLAN.md promises: "Caps are stated ... and the pack says when a
cap was hit." The items-list cap honoured that (`truncated`), but
`scan_markers` also slices the file list at `max_files` (20,000),
and files past the cap vanished with no record anywhere.
Demonstrated before: 5 files, `max_files=3` returned total 3 with
no field recording the cap.

Fix: the markers result now carries `files_considered`,
`files_limit`, and `files_truncated`, and HANDOFF.md's Markers
section says "File list capped: N project files, only the first M
were scanned for markers; files past the cap were not scanned"
when it happens. Verified by probe (fields flip exactly at the
cap) and by unit tests.

## What was deliberately left alone

- PLAN.md: it is the approved spec record. Its risks section
  describes the general false-positive hazard, which is still
  true; the refinement is recorded here instead of rewriting the
  spec after the fact.
- IMPLEMENTATION_A.md and REPORT_B.md: the builders' records,
  untouched.
- All pre-existing tests: untouched byte for byte; the polish
  added one new test file and nothing else under tests/.
- `.txt` files are not a docs signal, `examples/` and `tests/`
  directories are not fixture signals, and classification never
  looks at file contents: the split stays a pure, conservative
  path rule, so a real loop can only be down-weighted if a human
  filed real work under a docs/ or fixtures/ directory, where it
  remains listed with file and line.
- The recorded-test-failures next step reads its count from the
  loop detail's first token. It is fragile-looking but correct
  against the one template that produces that detail, and no
  fixture shows it failing; not worth churn in a polish round.
- `write_pack` builds the pack data before its overwrite refusal
  check. Observable behaviour is identical either way (refusal
  only triggers when pack files already exist, which requires the
  directory to exist), so there was nothing provably better to
  change.
- Version stays 0.1.0 everywhere; the JSON additions are additive
  fields, and `total` / `by_kind` semantics did not change, so
  existing consumers (CLI summary, MCP build summary, the suite's
  lenient diggers) need no changes.

## Files changed

- `src/ghosthandoff/scan.py` (context classifier, split counts,
  file-cap fields)
- `src/ghosthandoff/pack.py` (loop and step derivation, Markers
  section rendering, limits wording)
- `README.md` (Open loops and Honest limits wording)
- `tests/test_marker_context.py` (new: 4 black-box CLI tests,
  2 unit tests)
- `POLISH_REPORT.md` (this file)
