# GhostReview v0.1 - Polish Round (Oct 14, 2026)

House loop: audit first, then two distinct improvement passes,
demonstrate-then-fix. Every fix below was first shown broken with
a probe fixture (results quoted from the probes), then fixed, then
pinned with a regression test in `tests/test_polish.py` (24 new
tests). Final suite: **67 passed** (43 pre-existing + 24 polish),
0 failed. No version bump, no push, no publish. Version stays
0.1.0. Stdlib only, local only, no network, no spend.

## Audit findings

### Diff parser (diffparse.py)
- **A1 Quoted paths corrupted.** Git quotes paths containing
  spaces/non-ASCII. Probe: diff for `my file.py` reported the path
  as `"b/my file.py"` - quotes included - so the path matched
  nothing on disk.
- **A2 Header collision inside a hunk (worst finding).** A deleted
  line whose content starts with `-- ` and an added line whose
  content starts with `++ ` appear in a diff as `--- `/`+++ ` and
  were parsed as file headers. Probe: one-file diff for cfg.txt
  came back with old_path `old banner`, new_path `new banner`,
  and BOTH content lines lost (0 added / 0 deleted).
- **A3 Mode-only changes dropped.** `old mode`/`new mode` lines
  were ignored: a chmod-only change showed as a modified file with
  0 lines added and 0 deleted, with no record of what changed.
- **A4 Copy mislabelled as rename.** `copy from`/`copy to` fell
  through to the ---/+++ normalisation and reported status
  `renamed`, implying the original file was gone.
- **A5 Checked and correct, left alone:** `\ No newline at end of
  file` markers keep counts and line numbers right; plain renames;
  binary detection; hunk line numbers.

### Dependents (dependents.py) - all demonstrated misses
Probe projects where the importer plainly imports the changed file
and the scan returned no dependent:
- **B1** `from pkg import helper` (submodule import), importer
  outside the package.
- **B2** `import pkg` when `pkg/__init__.py` changed (the match
  test compared against `pkg.__init__` instead of `pkg`).
- **B3** `from . import helper` (relative import: the module part
  captured was just `.`).
- **B4** `import os, pricing` (comma imports: only the first
  module was captured).
- **B5** JS bare side-effect import `import './util.js'`.
- **B6** JS extensionless import resolving to `util.mjs` or
  `lib/index.mjs` (suffix/index candidates stopped at .jsx).

### Risks, citations, reports, MCP
- **C1 Verify citation contradicted the verdict.** A Verify report
  with verdict `gaps_found` but NO exit_code produced no
  VERIFY-FAILED flag and a `straightforward` verdict, while the
  summary still cited the gaps. The flag keyed on exit_code only.
- **C2 Scope reasons dropped and under-counted.** The reader never
  read scope.json's top-level `changed` list (reasons recorded only
  there were silently dropped - the shipped fixture lost 2 of 5),
  and reasons were de-duplicated across files, so the summary
  under-counted entries and REVIEW.md lost which file each reason
  belonged to.
- **C3 Summary risk wall.** The verdict summary joined EVERY
  high/medium flag detail; on a large diff the one-paragraph
  summary (and the MCP payload built from the same report) grew
  without bound.
- **C4 MCP caps covered risks only.** `_capped` trimmed risks to
  50 but returned change rows and dependent lists uncapped
  (probe: 300 change rows passed through untouched).
- **C5 No plain-language gloss.** REVIEW.md opened with the raw
  verdict word; a non-technical reader got no sentence explaining
  what `needs-a-look` asks of them.

## Pass 1 - parser and dependents (A1-A4, B1-B6)

- diffparse.py rewritten as an indexed loop. Git C-style quoted
  paths are unquoted (including octal escapes for non-ASCII) in
  the `diff --git` header, ---/+++ lines, and rename lines.
- ---/+++ are treated as headers only before a file's first hunk,
  or when an exact pair is immediately followed by a new `@@`
  header (header-less multi-file diffs still parse as two files -
  regression-tested). Otherwise they fall through as added/deleted
  content lines, fixing A2 with no loss to real headers.
- `old mode`/`new mode` (and the mode on new/deleted file lines)
  are recorded on FileChange; review.json rows carry
  `old_mode`/`new_mode`/`mode_changed`, and REVIEW.md says in
  words when a file's mode changed.
- `copy from`/`copy to` produce status `copied`; core totals gain
  `copied_files`, the summary names it, and REVIEW.md words it as
  "copied from another file (the original stays)".
- dependents.py matching reworked around FULL dotted module
  names: a changed file's name is its path dotted
  (`pkg/__init__.py` -> `pkg`). Candidates come from `import`
  lines (comma-split), `from` lines (the base plus each imported
  name tried as a submodule), and relative imports resolved
  against the importer's package. A bare stem still only matches
  a same-directory sibling, and two negative probes are pinned as
  tests: a bare `import helper` from another directory claims
  nothing, and `from pkg import thing` (an attribute of
  `__init__`) creates no edge to `pkg/helper.py`.
- JS scan: bare `import './x'` added to the pattern; resolution
  candidates extended with .mjs/.cjs and index files in all six
  suffixes.

## Pass 2 - risks, citations, readability, MCP caps (C1-C5)

- VERIFY-FAILED now fires on a non-pass verdict (pass set:
  pass/passed/sufficient/ok/clean) even when exit_code is absent,
  as well as on any non-zero exit code as before. A `sufficient`
  verdict with no exit code does not flag (pinned both ways).
- Scope reader now reads every changed-file list GhostScope
  writes (`changed_files`, `files`, `changed`, `analysis.changed`)
  and builds `risk_reasons_by_file` plus `risk_reason_entries`
  (entries as recorded; the same reason on two files counts
  twice). The summary cites the entry count, and REVIEW.md prints
  "Scope risk reason for `file`: ..." per file. `risk_reasons`
  (unique sorted) is kept for compatibility.
- Verdict summary caps its risk listing at the first 3 high/medium
  flags plus "and N more risk(s), listed in the Risks section
  below". review.json keeps the full list (pinned).
- REVIEW.md gains an "In plain words:" gloss under the verdict,
  one sentence per verdict word, in non-technical language.
- MCP `_capped` also caps changes at 50 (`changes_truncated` /
  `changes_total`) and each dependents list at 50
  (`dependents_truncated` / `dependents_total`).

## What was left alone, and why

- No-newline markers, plain renames, binary handling: probes
  showed them correct; a regression test locks the no-newline
  behaviour instead of changing code.
- Risk thresholds and wording for LARGE-DELETION /
  MANY-DEPENDENTS: details already name the threshold values and
  the probes showed the flags firing at the documented values.
- Symbol detection (symbols.py): no defect was demonstrated in
  this round's probes, so per demonstrate-then-fix it was not
  touched.
- Exit-code scheme and verdict vocabulary: unchanged.
- Examples' hand-written sample_output: unchanged; it is labelled
  SAMPLE SHAPE ONLY and is not a captured run.

## Secret discipline

Unchanged and re-verified: secret-shaped findings remain path +
line + type only. The polish suite adds a case where the
secret-shaped line is also the parser-collision case, asserting
the fake value appears in neither review.json nor REVIEW.md, and
the pre-existing suite's fake-secret assertions still pass.

## Verification

- `python3 -m pytest tests -q` in ~/workspace/ghostreview:
  **67 passed** (43 pre-existing, 24 new in tests/test_polish.py).
- Manual smoke: mixed_risky fixture with the real-shape Verify
  and Scope fixtures -> exit 1, verdict needs-attention, gloss
  printed, Scope cited with 5 risk reason entries (was 3 before
  the pass-2 reader fix), summary capped at 3 risks + "2 more",
  fake secret value absent from REVIEW.md and review.json.
