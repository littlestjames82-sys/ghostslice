# GhostRecipes merge - Oct 18, 2026 improvement run

Merger: hand-merged harden, then polish, then deepen onto a fresh
copy of the pristine tree (`~/workspace/ghostrecipes/`, never edited).
Nothing pushed. Python stdlib only. No version bumps anywhere
(pyproject and `__version__` remain 0.1.0).

## Test counts

Test command (same in every tree): `python3 -m pytest -q`

- Baseline (pristine copy at the same depth,
  `../pristine-check/`): 42 passed, 0 failed
- Harden lane: 61 passed (42 baseline + 19 new in
  `tests/test_harden.py`), 0 failed
- Polish lane: 42 passed (no new tests, no behavior change), 0 failed
- Deepen lane: 65 passed (42 baseline + 23 new in
  `tests/test_outputs.py`), 0 failed
- Merged: 84 passed, 0 failed

Merged count is exactly baseline + harden additions + deepen
additions (42 + 19 + 23 = 84), with polish contributing no tests.
Merged failures are the empty set, a subset of the baseline failure
set (also empty), verified against the pristine copy at the same
depth (`pristine-check/`, sibling of `merged/`) rather than the
original tree, so sibling-relative-path effects are controlled for.

## Single-lane files (copied outright)

- Harden only: `tests/test_harden.py` (new)
- Deepen only: `tests/test_outputs.py` (new)
- Polish only: `examples/WALKTHROUGH.md`,
  `src/ghostrecipes/__init__.py`, `src/ghostrecipes/__main__.py`,
  `src/ghostrecipes/authoring.py`

## Multi-lane files and how each conflict was resolved

All multi-lane overlaps were in disjoint regions of each file, so
every lane's changes survive verbatim; the "removals" visible in a
lane-vs-merged diff are only the single lines that another lane's
expanded version supersedes (a docstring's first line, the
pre-harden unsafe line, or the pre-polish parser lines), each
checked by hand.

- `src/ghostrecipes/recipe.py` (harden + polish + deepen):
  Harden base kept in full: `strict_json_loads`, defensive
  `summary_line`, utf-8-sig read with clean `GhostRecipesError`
  handling, input `description` type check, and the `.recipe.md`
  filename/id mismatch warning. Polish docstrings added at their
  four sites (`Recipe`, `validate_data`, `default_library_dirs`,
  `resolve_recipe`). Deepen added on top: `outputs` in `TOP_KEYS`
  plus `OUTPUT_KEYS`, the `Recipe.outputs` property, the full
  outputs validation block (inserted after the steps loop, using
  the already-collected `seen_steps` for `from_step` checks), and
  output descriptions in the placeholder scan (scan comment updated
  to the deepen wording). The harden `description` check inside the
  inputs loop does not collide with deepen's separate outputs-loop
  `description` check; both are present.
- `src/ghostrecipes/cli.py` (harden + polish + deepen):
  Harden base kept in full: empty `--steps` segments dropped in
  `cmd_create`, defensive tools/inputs/steps printing in `cmd_show`,
  and the `OSError` to exit-2 mapping in `main`. Polish applied
  around it: expanded module docstring, a one-line docstring on
  every `cmd_*` handler, `build_parser`, and `main`, and the whole
  `build_parser` body replaced with the polish help-text version
  (harden never touched the parser, so nothing of harden's was in
  the replaced text). Deepen's `show` outputs section was inserted
  verbatim between harden's defensive inputs section and harden's
  defensive steps section, so the order in `show` output is inputs,
  outputs, steps.
- `src/ghostrecipes/packio.py` (harden + polish):
  Harden base kept in full: strict manifest loading as utf-8-sig
  with clean errors and non-object rejection, the
  `<id>.recipe.json` / `<id>.recipe.md` manifest-entry name check,
  and the symlink write-through refusals in both export and import.
  Polish docstrings for `export_pack` and `import_pack` added at
  the function heads; no logic lines touched.
- `src/ghostrecipes/render.py` (polish + deepen):
  Polish docstrings for `resolve_values`, `substitute`, and
  `render_recipe` added. Deepen's `## Outputs` table block inserted
  verbatim after the steps loop and before the notes section,
  exactly where the deepen lane placed it.
- `README.md` (polish + deepen):
  Polish README is the base (restructured top, Quickstart, commands
  table, first-recipe walkthrough, Troubleshooting). Deepen's two
  insertions applied at their anchors, which polish did not move:
  the `outputs` lines in the recipe-format JSON example, and the
  `outputs` bullet immediately after the "Step ids are unique"
  bullet.

## Merger-authored code

None. Every code and prose line in the merged tree is verbatim from
pristine or from one of the three lanes; the merger only chose
placement at the seams listed above. (The deepen `show` outputs
loop is kept exactly as the deepen lane wrote it; it assumes dict
outputs, as deepen's validator reports non-dict outputs as errors
after printing. Making it defensive in harden's style was
considered and deliberately not done, to keep merger-authored code
at zero and lane behavior byte-faithful.)

## Flags

None. No conflict required dropping or altering any lane's fix or
behavior, and no lane documented a known non-regression or watch
item that the merge affects:

- Harden's intended fail-closed change (duplicate JSON keys now
  rejected everywhere, including manifests and Markdown blocks)
  is preserved, and deepen's validator runs through the same
  strict loader via `validate_data`.
- Deepen's note that `from_step` is only cross-checked when valid
  step ids were collected is preserved (the validation block is
  verbatim and still reads `seen_steps`).
- Polish's note that `pyproject.toml` still points `readme` at
  `PLAN.md` is pre-existing in pristine and was left untouched by
  all lanes and by this merge.
