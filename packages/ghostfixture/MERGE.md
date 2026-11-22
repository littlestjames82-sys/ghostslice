# GhostFixture — MERGE report (2026-10-18)

Merged tree built from a fresh copy of the pristine tree
(`~/workspace/ghostfixture/`, never edited), with lane changes
applied in order: harden, then polish, then deepen. Method:
`diff -rq` per lane against pristine, single-lane files copied,
multi-lane files combined with a three-way merge
(`git merge-file`, pristine as base) and hand-checked file by file.

## Test counts

- Pristine baseline: 43 passed (stated in all three IMPROVE.md files)
- Harden lane: 63 passed (43 + 20 new in tests/test_hardening.py)
- Polish lane: 43 passed (no behavior changes)
- Deepen lane: 49 passed (43 + 6 new in tests/test_c_closure.py)
- **Merged: 69 passed (`python3 -m pytest -q`, 0 failed)**
  = 43 baseline + 20 harden + 6 deepen. Merged passes at least
  what the best lane passed (63), with zero new failures versus
  every lane.

## Files by lane

Copied from a single lane:

- Harden: `tests/test_hardening.py` (new)
- Polish: `examples/README.md`, `src/ghostfixture/__init__.py`,
  `src/ghostfixture/__main__.py`, `src/ghostfixture/bundle.py`,
  `src/ghostfixture/cli.py`, `src/ghostfixture/reports.py`
- Deepen: `tests/test_c_closure.py` (new),
  `tests/fixtures/c_project/` (new: `src/main.c`, `src/app.h`,
  `src/util/util.h`, `src/defs.h`, `src/api_keys.h`, `src/ghost.h`,
  `src/impl.c`, `stray.h`)

Hand/three-way merged (multiple lanes, different regions):

- `src/ghostfixture/build.py` — harden + polish. Harden: new
  `_path_shape_problem` validation, fully-resolved output
  validation / broken-symlink and non-directory refusals,
  `reserved-output-name` left-outs, manifest-structure validation
  in `check_fixture`. Polish: docstrings for `_sha256`, `_inside`,
  expanded `build_fixture` and `check_fixture`. Verified: merged
  vs harden differs only by the polish docstrings; merged vs
  polish differs only by the harden changes. No harden fix dropped.
- `src/ghostfixture/secrets.py` — harden + polish. Harden:
  `github_pat_`/`glpat-`/JWT shapes, gated env-style unquoted
  assignment detection, `_scan_text` refactor, UTF-16 scanning.
  Polish: `_is_placeholder` docstring only. Both present.
- `src/ghostfixture/mcp_server.py` — harden + polish, ONE
  conflict (see below). Harden: non-object JSON lines skipped,
  non-object `params` coerced, non-object tool arguments
  rejected. Polish: per-property schema descriptions, docstrings
  for `_summary`, `_call_tool`, `serve`, `_send`. All present.
- `src/ghostfixture/closure.py` — harden + polish + deepen.
  Harden: Go module cache keyed by (root, go.mod mtime_ns + size).
  Polish: docstrings for `closure_supported` and `language_of`.
  Deepen: `CPP_EXTS` / C-C++ closure (`_strip_c_comments`,
  `_c_imports`, quoted-include resolution, dispatch in
  `imports_of`, `c/c++` language and closure-note entries).
  All three present; polish docstring and deepen `c/c++` branch
  coexist in `language_of`.
- `README.md` — polish + deepen. Polish: Install section,
  Quick-start demo, Command reference and exit-code tables, MCP
  tool table. Deepen: Honest-limits paragraph now states C/C++
  closure via preprocessor includes and the
  angle-bracket/macro external-reference rule. Both present.

## Conflicts

1. `src/ghostfixture/mcp_server.py`, `_call_tool` head — the only
   real conflict. Harden inserted the
   `if not isinstance(args, dict): raise ValueError(...)` guard
   as the first statement; polish inserted a one-line docstring
   at the same spot. Resolution: BOTH kept, docstring first
   (so it remains the function's docstring), guard immediately
   after. No duplicate logic; the harden guard is intact.
   All other multi-lane files merged cleanly in disjoint regions.

No other conflicts. No harden fix was dropped anywhere.

## Repo-specific check: `__main__.py` docstring

VERIFIED CORRECT. The merged `src/ghostfixture/__main__.py` reads:

```python
"""Entry point for ``python3 -m ghostfixture``; see ``cli.py``."""
from .cli import main
```

That docstring belongs to GhostFixture (names `ghostfixture`
and this repo's `cli.py` entry point), not to any other product.
It matches the polish lane's restored final version; the
wrong-product scratch-file incident described in the polish
IMPROVE.md is not present in the merged tree. Pristine had no
docstring in this file, so this is the polish lane's intentional
addition.

## Housekeeping / suspicious items

- Lane `IMPROVE.md` files were not copied into the merged tree
  (verified: no `IMPROVE.md` at the merged root).
- No conflict markers remain anywhere in the merged tree;
  all `src/ghostfixture/*.py` pass `py_compile`.
- Nothing suspicious beyond the resolved `mcp_server.py`
  conflict above. Deepen's C-project fixture canary
  (`src/api_keys.h`) is included as in the deepen lane; its
  flagged-exclusion behavior is covered by the passing
  `test_c_closure.py` tests.
