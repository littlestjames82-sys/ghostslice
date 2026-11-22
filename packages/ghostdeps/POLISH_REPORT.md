# GhostDeps v0.1 - Polish report

Polish round completed Oct 14, 2026. Scope: `~/workspace/ghostdeps/`
only, as sole folder owner for this round. No version bump: the
package remains `0.1.0` in both `pyproject.toml` and
`src/ghostdeps/__init__.py`. Stdlib only, local only, no network, no
push, no PyPI/publish, no announcements, no spend.

## Test counts

Command used for both counts, from `~/workspace/ghostdeps/`:

```
PYTHONPATH=src python3 -m pytest tests -q
```

- Before polish: **19 passed, 0 failed** (the parent-verified baseline
  after the F1/F2 fix round).
- After polish: **24 passed, 0 failed**.
- Difference: **5 new regression tests**, all in the new
  `tests/test_polish.py`. No existing test was edited, deleted, or
  weakened; the original 19 tests pass unchanged.

## Audit performed first

Read before changing anything: `PLAN.md`, `IMPLEMENTATION_A.md`,
`REPORT_B.md`, and `FIX_REPORT.md`, plus the current sources
(`manifests.py`, `imports_scan.py`, `xref.py`, `cli.py`, `names.py`)
and the existing suite. The audit confirmed the F1/F2 fixes were in
place and holding (build-system requires stay out of the declared
set; transitive lockfile pins stay compact and complete). Three
documented limits from `IMPLEMENTATION_A.md` were then probed with
throwaway fixtures under `/tmp` before any code changed:

1. **JS comment stripping vs strings.** Baseline probe: a fixture
   whose first line was
   `const marker = "// not a comment"; const axios = require('axios');`
   produced **no** imported-not-declared entry for axios. The naive
   line-comment strip treated the `//` inside the string as a comment
   and erased the rest of the line.
2. **No ignore-file support.** Baseline probe: a fixture with
   `generated/**` in `.gitignore` (plus a `!generated/keep.js`
   negation) and `fixtures/**` in `.ghostslice.json` still scanned
   all 4 JavaScript files, and the imports planted in the ignored
   files (`phantom`, `ghostpkg`) appeared as imported-not-declared
   findings.
3. **Nested manifests had no grouping.** Baseline probe: a fixture
   with `package.json` at the root, in `packages/api`, and in
   `examples/demo` produced correct global sections, but the manifest
   had no `source_groups` or `import_scan` fields and DEPS.md gave no
   location summary, so nested evidence could only be attributed by
   reading each source path in the flat list.

## What changed

### 1. String-aware JS/TS comment stripping

`src/ghostdeps/imports_scan.py`: the two regex comment substitutions
were replaced by `_strip_js_comments()`, a small lexical scanner.
It tracks ordinary strings, template literals (including nested
`${...}` expressions, nested templates, and object braces), regex
literals (including character classes and escapes), and line/block
comments. Comment characters are replaced with spaces and newlines
are preserved, so a comment marker inside a string, template, or
regex no longer erases the code after it, and commented-out imports
are still removed.

Demonstration: on the baseline probe fixture the pack now reports
axios as the only imported-not-declared entry, with `index.js` as
evidence, while the commented-out `phantom` and `blocked` requires
stay absent. The new regression test extends the fixture with a
template-literal require, a regex literal containing `//`, and a
division expression followed by another require; all declared
packages land in declared-and-used and axios is the sole finding.
Six additional direct spot checks of the stripper also passed
(apostrophe inside a line comment, URL string, nested template,
regex character class, division plus block comment, escaped quote).

### 2. Ignore rules for the import scan

New `src/ghostdeps/ignores.py`: an `IgnoreMatcher` that loads
hierarchical `.gitignore` files (root and nested, later rules win,
negations honoured) and the `ignore` list from the root
`.ghostslice.json`. Gitignore globs are translated segment-aware:
a single `*` or `?` does not cross a directory separator, while a
whole-segment `**` can span directories. GhostSlice profile patterns
keep GhostSlice's documented glob behaviour.

`scan_imports()` now applies these rules when choosing which source
files to scan, and records the outcome in a new additive manifest
field:

```
"import_scan": {
  "ignored_files": [...],
  "ignored_file_count": n,
  "ignore_sources": [...],
  "warnings": [...]
}
```

Two deliberate safety properties:

- Local-module names are still collected from **all** candidate
  files, including ignored ones, so ignoring a file does not turn a
  local module into a phantom third-party gap.
- The rules filter the **import scan only**. Manifest and lockfile
  discovery is unchanged, so an ignored directory's manifest is
  still recorded as evidence (pinned by test).

A malformed `.ghostslice.json` (or a non-list `ignore` value) does
not fail the run: the profile's patterns are not applied and a
warning is recorded in `import_scan.warnings` and shown by
`doctor`. This is pinned by a regression test.

Demonstration: the regression fixture (root `.gitignore` with a
negation, a nested `packages/.gitignore`, and a `.ghostslice.json`
ignore) reports exactly
`ignored_files = [fixtures/hidden.js, generated/skip.js, packages/demo/skip.ts]`,
scans 2 JavaScript files, and finds only the axios import from the
negation-rescued `generated/keep.js`. A separate segment-glob test
pins that `src/*.js` ignores `src/app.js` but not
`src/nested/app.js`; direct matcher spot checks for `build/`,
`**/*.snap`, and `docs/**/draft.md` also passed.

One defect was found by the new tests during this round and fixed
before landing: non-source files under an ignored directory (for
example `fixtures/package.json`) were initially listed in
`ignored_files`. Ignore evaluation now runs only over actual source
candidates (`.py`, JS/TS, and `.rs` extensions).

### 3. Nested-manifest grouping and summary

`src/ghostdeps/xref.py`: the manifest gains an additive
`source_groups` field grouping every source by its holding
directory, with the source count, file list, and per-status counts
for each directory (project root first). DEPS.md adds a compact
summary line when more than one location is present, for example:

```
Manifest locations: 3 (project root: 1; `examples/demo`: 1; `packages/api`: 1).
```

The cross-reference itself stays project-wide, as the plan scopes
it; the grouping is attribution, not a behaviour change to the
sections or exit codes. `doctor --json` now also exposes
`source_groups` and `import_scan`, and text `doctor` prints the
ignored-file count and any ignore warnings. The DEPS.md Limits
section and `README.md` were updated to describe the new ignore and
grouping behaviour and the improved comment stripping.

Demonstration: the nested regression fixture's manifest contains
exactly the three expected groups with one parsed source each, the
DEPS.md summary line names all three locations, and all three
declared packages still land in declared-and-used with exit 0.

### Files changed

- `src/ghostdeps/ignores.py` (new)
- `src/ghostdeps/imports_scan.py` (lexical comment stripper, ignore
  integration, ignore metadata on the import index)
- `src/ghostdeps/xref.py` (`source_groups`, `import_scan`, DEPS.md
  summary and limits wording)
- `src/ghostdeps/cli.py` (doctor surfaces the two new fields)
- `tests/test_polish.py` (new; 5 regression tests)
- `README.md` (behaviour and honest-limits wording)
- `POLISH_REPORT.md` (this file)

Additive-schema note: the new manifest fields add fixed metadata to
every pack. On the shipped Node example the pack total grew from
9,250 bytes (post-F2 measurement) to 10,028 bytes, with counts
unchanged (declared 3, pins recorded 43, transitive 40). The Python
example's counts are likewise unchanged (declared 3,
build requirements 1, pins recorded 4). Both examples still exit 1
on their planted imported-not-declared findings, as designed.

## What was deliberately left alone

- **No existing test assertions were touched.** All changes to the
  suite are the five additions in `tests/test_polish.py`.
- **No per-package cross-reference split.** Grouping is a summary
  only. Splitting sections or exit codes per nested package would
  change the plan's project-wide contract and mis-handle sibling
  imports in monorepos; the plan lists workspace resolution as out
  of scope for v0.1.
- **Manifest discovery was not ignore-filtered.** The seed candidate
  was scoped to the import scan, and filtering manifests could hide
  dependency evidence (including lockfiles a project chose to
  gitignore).
- **No full JS/TS parser.** The stripper is still parser-lite:
  grammar ambiguities that need a real parser (some regex-vs-division
  positions, JSX text) remain approximations, and computed
  specifiers and some re-export forms can still be missed. The plan
  labels this side parser-lite and the reports still say so.
- **Git ignore scope stays local to the tree.** `.git/info/exclude`,
  global gitignore files, and tracked-vs-untracked distinctions are
  not consulted; only `.gitignore` files in the tree and the root
  `.ghostslice.json` list are.
- **No change to F1/F2 behaviour, name mapping, local-name
  classification, Rust outline extraction, or lockfile handling.**
  No fixture-proven defect in those areas surfaced during this
  round, and the original tests pinning them pass unchanged.
- **Historical documents were not rewritten.** `PLAN.md`,
  `IMPLEMENTATION_A.md`, `REPORT_B.md`, and `FIX_REPORT.md` remain
  as originally written; this report is the polish record.
