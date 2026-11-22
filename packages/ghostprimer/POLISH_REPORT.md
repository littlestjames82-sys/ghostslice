# GhostPrimer v0.1 - Polish report

Polish round Oct 14, 2026, at Ryan's "Polishing" direction, after the
parent-verified D1-D3 fix round. Sole folder ownership for this round.
In-tree only: no version bump (pyproject still 0.1.0), no push, no
publish, no announcements, no spend. Stdlib only.

## Test counts

```
PYTHONPATH=src python3 -m pytest tests -q
Before: 31 passed, 0 failed   (parent-verified baseline)
After:  36 passed, 0 failed   (31 pre-existing, untouched, + 5 new)
```

No existing test was edited, weakened, or deleted. All changes are in
`src/ghostprimer/scan.py`, `src/ghostprimer/bundle.py`, new files
under `tests/`, and documentation (below).

## What changed

### 1. JS/TS fan-in: parser-lite import graph (the seed candidate)

Was: fan-in counted Python imports only (`scan.python_fan_in`). JS/TS
files ranked by entry-point status then path order, and the manifest
recorded their `fan_in` as 0 even though nothing had measured it.

Now: `scan.js_fan_in` builds a parser-lite import graph for
.js/.ts/.tsx/.jsx/.mjs and `scan.import_fan_in` merges it with the
Python graph; `bundle.build_bundle` uses the merged map. Details:

- Specifier extraction covers static imports, side-effect imports,
  `export ... from` re-exports, `require(...)`, dynamic `import(...)`
  (quoted or template specifiers), and TS `import x = require(...)`.
- The scanner is string/comment aware: a state machine blanks comments
  and replaces string/template contents with placeholders before the
  import patterns run, so import-shaped text inside a comment or a
  string literal is never counted, while a real import's specifier is
  recovered through its placeholder. Regex literals are recognised
  (with a keyword-aware division heuristic) so a quote or `//` inside
  a regex cannot corrupt the masking.
- Resolution is relative-specifiers only (bare specifiers are
  packages, never project files) and handles extensionless imports,
  directory `index` files, and the NodeNext convention of writing
  `.js` for a `.ts` source (`.jsx` -> `.tsx` likewise). One count per
  importing file per target, mirroring the Python graph.
- Consequence, deliberate and matching the plan's selection rule
  ("entry points plus highest fan-in" and the D2 behaviour for
  Python): a JS/TS file with zero fan-in that is not an entry point
  is now excluded from the starter slice and named in the
  not-included list as unreferenced, instead of being included
  whenever it fit the budget.
- Manifest honesty: every file entry now also records
  `fan_in_method` ("ast" for Python, "parser-lite" for JS/TS, "none"
  for languages with no import graph), so a recorded 0 is never again
  ambiguous between "measured zero" and "not measured".

Demonstration: new fixture `tests/fixtures/js_project` with a
hand-computed import graph (written from the sources before the core
change), including three traps that mention `./ghost` (line comment,
block comment, string literal) and a regex literal containing a
quote. New `tests/test_js_fan_in.py` (5 tests) asserts, black-box
through the CLI and manifest: every included file's exact fan-in
(util 2, lib/helper 2, thing 2, lazy 2, polyfill 1, legacy-helper 1),
`fan_in_method` on JS entries and on a Python entry ("ast"), entry
point detection, exclusion plus not-included naming for the three
zero fan-in files (ghost, orphan, legacy), and the exact slice order
(entry first, then fan-in descending). A direct probe during the
round confirmed the extracted specifier lists per file matched the
hand computation exactly, traps included (no `./ghost` anywhere).

### 2. Stale honesty wording fixed

- README.md, Honest limits: added the fan-in disclosure above (exact
  for Python, parser-lite for JS/TS with the masking and resolution
  scope stated, no graph for other languages, `fan_in_method`
  explained). The README previously described the fan-in ranking with
  no method qualification at all.
- IMPLEMENTATION_A.md: appended a dated polish addendum correcting
  three stale statements instead of rewriting the historical record:
  (a) "fan-in counts Python imports only" (superseded by change 1);
  (b) "the fallback memory path blocks at file level" (already
  superseded by the D1 fix round's per-item blocking, FIX_REPORT.md);
  (c) "pip install . from the live tree was not run because README.md
  ... has not landed yet" (README has landed).
- For (c), the polish round verified the install itself: copied the
  current tree to /tmp, `pip install --no-build-isolation --target`
  succeeded ("Successfully installed ghostprimer-0.1.0") and the
  installed `ghostprimer` console script runs. Local install smoke
  only; nothing was published anywhere.

## What was deliberately left alone

- Version stays 0.1.0. Releases are Ryan-gated; polish is in-tree.
- The other documented limits from IMPLEMENTATION_A.md were reviewed
  and left as real limits, not polish-sized fixes: test-file
  exclusion by path prefix (a `test_*.py` inside `src/` is treated
  as code), the memory cap always keeping at least one item,
  entry-point detection heuristics, and the chars/4 fallback
  estimator when GhostSlice is not importable.
- Parser-lite boundaries accepted and now documented in code/README
  rather than engineered around: string-named imports
  (`import { "x" as y } from ...`) are not extracted, a regex literal
  immediately after a closing brace is read as division, and
  template-literal specifiers with `${}` expressions are not
  resolved (they are not statically resolvable anyway).
- PLAN.md, pyproject.toml, memory.py, secrets.py, slicer.py,
  tokens.py, doctor.py, cli.py, mcp_server.py: untouched.

## Files

- Changed: `src/ghostprimer/scan.py` (JS/TS graph added),
  `src/ghostprimer/bundle.py` (merged fan-in map, comment updated,
  `fan_in_method` recorded), `README.md` (limits disclosure),
  `IMPLEMENTATION_A.md` (polish addendum).
- Added: `tests/test_js_fan_in.py`,
  `tests/fixtures/js_project/` (package.json + 10 source files),
  this report.
