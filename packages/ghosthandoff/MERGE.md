# MERGE.md - GhostHandoff improvement merge (Oct 18, 2026)

Merger worker output. Pristine tree `~/workspace/ghosthandoff/` was
never edited. Lanes applied in order: harden, then polish, then
deepen. Nothing pushed. Stdlib only, no version bump (0.1.0 in both
`pyproject.toml` and `__init__.py`, verified).

## Test counts

Test command used (both trees, plain, per protocol):
`python3 -m pytest -q`

- Baseline (pristine copy at the same depth,
  `../pristine-check/`): **43 passed, 1 failed** (44 collected).
  The 1 failure is the known time-bombed fixture test
  `test_pack_since_window_widens_with_duration` (hard-coded
  2026-10-11 old-commit date aged out of the `--since 4d` window).
- Harden lane (per its IMPROVE.md): **52 passed, 0 failed**
  (44 pre-existing + 8 new in `tests/test_hardening.py`; the
  baseline failure fixed by its relative-date fixture change).
- Polish lane (per its IMPROVE.md): **43 passed, 1 failed**
  (44 collected, no new tests, no behaviour change; the same
  pre-existing baseline failure, untouched by that lane).
- Deepen lane (per its IMPROVE.md): **50 passed, 0 failed**
  (44 pre-existing + 6 new in `tests/test_in_progress_operation.py`;
  baseline failure fixed by the same relative-date fixture change).
- Merged (this tree): **58 passed, 0 failed**.

Merged count is exactly baseline 44 + harden 8 + deepen 6 = 58,
and the repo-specific acceptance holds: the merged tree shows
0 failures (the time-bomb failure is fixed by the harden/deepen
relative-date fixture change). No deviation to explain.

## Multi-lane files and how each conflict was resolved

Merges were done as explicit three-way merges (pristine as base)
per file, in lane order, and every result was checked for conflict
markers and for the presence of each lane's key changes.

1. `src/ghosthandoff/gitfacts.py` - harden + polish + deepen.
   Both three-way merges were textually clean (0 conflicts).
   Harden's logic (base/since option-injection guards, unborn-branch
   header parsing, commit-author redaction via `clean_line`),
   polish's docstrings (module entry-points list, `collect_git`
   return shape), and deepen's `detect_operations()` plus the
   unmerged status split all survive; verified by grep for each
   lane's markers in the merged file.
2. `src/ghosthandoff/scan.py` - harden + polish. Three-way merge
   clean (0 conflicts). Harden's `_contained_file` symlink
   containment gates the marker scan and all report discovery, and
   its verdict redaction is present; polish's docstrings survive.
3. `src/ghosthandoff/mcp_server.py` - harden + polish. Three-way
   merge clean (0 conflicts). Harden's malformed-request robustness
   (non-dict `params`/`arguments` coerced, non-object JSON lines
   skipped, tool exceptions returned as `isError` results) and
   polish's docstrings both survive.
4. `src/ghosthandoff/pack.py` - polish + deepen. Three-way merge
   clean (0 conflicts). Polish's docstrings and deepen's
   in-progress-operation / unmerged-files open loops, first-priority
   next steps, State-now rendering, and coverage line all survive.
   One stale sentence in a polish docstring was corrected by the
   merger (see "Merger-authored changes" below).
5. `README.md` - polish + deepen. Three-way merge clean
   (0 conflicts). Polish's full restructure is the merged README;
   deepen's edits landed in the corresponding polished sections:
   in-progress operation detection and the unmerged split in the
   pack-contents description, the new open-loop kinds, and the
   crashed-git stale-marker caveat in Honest limits.
6. `tests/helpers.py` - harden + deepen. The only textual conflict
   (2 hunks), and it is comment wording only: both lanes make the
   identical code change,
   `OLD_COMMIT_DATE = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")`.
   Resolved by keeping the harden version outright, so deepen's
   fix is fully present in substance; only deepen's alternate
   comment phrasing was not kept, and keeping both lanes' import
   lines would have duplicated the `datetime` import (the lanes
   added it at different positions). No harden or deepen behaviour
   was lost.
7. Cross-file (not same-file): `examples/README.md` (polish) vs
   `examples/make_fixture_repo.py` (harden). Polish's walkthrough
   described the demo's old commit as fixed at 2026-10-11; harden
   changed the fixture script to date it 3 days before build time,
   which made polish's date claim false in the merged tree (its
   `--since 30d` widen step itself still works). Resolved with
   merger-authored wording edits (below): the four fixed-date
   mentions now say the commit is dated 3 days before the demo is
   built; polish's 30d step is retained.

Files changed by only one lane were copied outright:
harden - `examples/make_fixture_repo.py`, `tests/test_hardening.py`
(new); polish - `examples/README.md`, `src/ghosthandoff/__init__.py`,
`src/ghosthandoff/__main__.py`, `src/ghosthandoff/cli.py`,
`src/ghosthandoff/redact.py`; deepen -
`tests/test_in_progress_operation.py` (new).

## Merger-authored changes

No merger-authored code or logic. Two documentation reconciliations
only, both marked here:

- `examples/README.md`: four phrases updated from the fixed date
  2026-10-11 to the relative "3 days before the demo is built"
  wording, to match harden's fixture-script change (item 7 above).
- `src/ghosthandoff/pack.py`: in polish's `derive_next_steps`
  docstring, the stated priority order now begins "in-progress git
  operation and its unmerged files first, then failing
  verification, ..." to match deepen's actual step order in the
  same function. Docstring text only; no code touched.

## Flags

- None unresolved. No lane fix or behaviour was dropped.
- For the record: harden's IMPROVE.md flagged (and left alone) the
  porcelain conflict-state double-count; deepen's core capability
  intentionally supersedes that in `gitfacts.py`/`pack.py` by
  listing unmerged paths separately, so that flagged item does
  not carry into the merged tree. Harden's other flagged items
  (no `-n` cap on the files-touched `git log` call; `show`/MCP
  reading caller-named paths by design) are unchanged, as both
  lanes left them.
- A pristine copy at the same depth as this tree was kept at
  `../pristine-check/` for the baseline comparison above.
- No `IMPROVE.md` files are present in this tree; this MERGE.md is
  the only new file at the merged root.

## Verdict

CLEAN
