# GhostLift merge (Oct 18, 2026)

Merged tree built as a fresh copy of pristine `~/workspace/ghostlift/`
(no `__pycache__`/`.pytest_cache`), then lane changes applied in order
harden, polish, deepen. Pristine tree untouched; nothing pushed.
No `IMPROVE.md` in this tree (lane files only; verified).

## Test counts

Command for every tree (per the lanes' IMPROVE.md):
`PYTHONPATH=src python3 -m pytest tests -q`

| Tree | Result |
| --- | --- |
| Pristine baseline | 31 passed, 1 skipped (32 collected) |
| harden | 59 passed, 1 skipped |
| polish | 31 passed, 1 skipped |
| deepen | 44 passed, 0 skipped |
| **merged** | **72 passed, 0 skipped (72 collected)** |

Merged run three times, 72 passed each time. Arithmetic checks out:
32 baseline + 28 harden tests + 12 deepen tests = 72, and deepen's
contract change removes the 1 baseline skip (the previously skipped
core-JS test, `test_core_lifts_minified_js`, now passes; skips 1 -> 0
is expected per the deepen lane, not a regression). Zero new failures
versus every lane; merged passes more than the best single lane
(harden, 59).

## Files from only one lane (copied verbatim)

- harden: `tests/test_hardening.py` (new)
- polish: `src/ghostlift/__main__.py`, `src/ghostlift/pyc.py`,
  `src/ghostlift/reconstruct.py`, `examples/README.md`
- deepen: `src/ghostlift/jslift.py` (new), `tests/test_js_core_lift.py`
  (new), `tests/test_cli_contract.py`

## Files changed by multiple lanes (hand-merged)

- `src/ghostlift/core.py` (harden + polish + deepen): harden base
  (`_unique` generate-until-unused, per-artifact/per-write/manifest
  guards in `lift_path`); polish docstrings added for `LiftError`,
  `_sha256`, `detect_kind`, `inspect_artifact`,
  `_output_name_for_pyc`, `_unique`, `lift_path`; deepen changes on
  top (jslift import, `.js` in `SUPPORTED_SUFFIXES`, Tier 2 liftable
  JS inspect branch with function boundaries, `.js` in the
  no-artifacts error, new `javascript` lift branch with Tier 2
  manifest entry). Polish's JS inspect-note wording was superseded by
  deepen's replacement of that whole branch (expected, deepen is the
  later/intended behaviour). Polish's `lift_path` Raises text updated
  to `(.pyc / .map / .js)` to match deepen.
- `src/ghostlift/cli.py` (polish + deepen): polish base (help text,
  epilog, metavars, `main()`/`_print_inspect` docstrings) plus
  deepen's JS functions block in `_print_inspect`. One wording
  adjustment: polish's lift description said ".pyc and .map"; updated
  to ".pyc, .map and .js" so the help matches deepen's behaviour.
- `src/ghostlift/sourcemap.py` (harden + polish): harden logic
  (UNC/drive-prefix sanitising, generate-until-unused duplicate
  names, RecursionError -> SourceMapError) plus polish docstrings
  for the dataclasses, `sanitise_source_path`, `recover_source_map`.
  Disjoint regions; verified merged-vs-harden diff is docstrings only.
- `src/ghostlift/marshal_safe.py` (harden + polish): harden logic
  (`_float_text`/`_decode_text` error normalisation, unhashable
  set/frozenset handling, code-object validation) plus polish
  `_Reader`/`parse()` docstrings. Disjoint; verified docstrings-only
  diff vs harden.
- `examples/js_lift_demo.py` (harden + polish): harden's
  `_mask_strings_and_comments` boundary masking plus polish's
  `lift_minified_js` docstring and module-docstring rewrite. One
  wording adjustment: polish's module docstring said the core CLI
  reports JS "but not yet liftable", which deepen makes false, so it
  now says the core CLI lifts minified JS as Tier 2 directly.
- `examples/pyc_outline_demo.py` (harden + polish): harden's reader
  limits (negative sizes/counts refused, ref range/unfinished checks,
  depth cap 100, `read_object(depth)` signature) plus polish
  docstrings for `_Reader`, `read_object`, `load_code_object`.
  Disjoint; verified docstrings-only diff vs harden.
- `README.md` (polish + deepen): polish base (Quick start, CLI table,
  worked example) plus deepen's Tier 2 paragraph (core lifts `.js`
  directly, example remains a standalone reference). One wording
  adjustment: polish's new table row said JS was "Not in the core CLI
  yet", contradicting deepen; updated to "Yes: beautified, with
  function boundaries recovered."

## Merger-applied guard (noted, not a lane change)

Deepen's new `javascript` branch in `lift_path` wrote its output
unguarded, unlike the neighbouring branches. To preserve the harden
lane's invariant (one hostile artifact = recorded failure, never a
crash losing the whole lift and manifest), the JS lift/encode/write
steps are wrapped in the same try/except -> `failures.append` pattern
harden applied to the `.pyc` branch. Deepen's decode handling,
function-boundary recording, watermark, and manifest entry are
unchanged; all deepen tests pass.

## Conflicts / flagged

- No unresolvable conflicts. No harden fix was dropped: every harden
  hunk is present in merged (checked file-by-file against the harden
  tree; non-docstring diffs vs harden are exactly the deepen/polish
  additions listed above).
- Same-region, different-text collisions were only in documentation
  strings that deepen's behaviour change made stale (core.py JS note,
  README JS rows, cli.py lift description, js_lift_demo module
  docstring). Each was resolved in favour of the post-deepen truth,
  as listed above.
- Nothing suspicious found. No other files differ from pristine:
  merged-vs-pristine file list is exactly the union of the three
  lanes' changed/new files.
