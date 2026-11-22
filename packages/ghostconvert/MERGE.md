# GhostConvert — merge of harden + polish + deepen lanes

Merged tree built 2026-10-18 from the pristine tree
(`~/workspace/ghostconvert/`, never edited), applying lanes in order
harden → polish → deepen. Multi-lane files were combined with 3-way
merges (`git merge-file`, base = pristine); every merge completed
cleanly (exit 0, no conflict markers). No IMPROVE.md is present in
this tree.

## Test counts

Command (the documented one; bare `pytest` at repo root mis-collects
`examples/sample_project/tests/`): `PYTHONPATH=src python3 -m pytest tests -q`

| Tree | Result |
|---|---|
| Pristine baseline (per all three IMPROVE.md files) | 63 passed |
| harden lane | 71 passed (63 + 8 new) |
| polish lane | 63 passed (no tests added) |
| deepen lane | 76 passed (63 + 13 new) |
| **merged** | **84 passed, 0 failed** (63 + 8 harden + 13 deepen) |

Merged passes the best lane's count plus every other lane's added
tests, with zero new failures versus any lane.

## Files by lane

Copied from a single lane:

- harden: `tests/test_harden.py` (new)
- polish: `examples/README.md`, `src/ghostconvert/__main__.py`
- deepen: `src/ghostconvert/verify.py` (new), `tests/test_verify.py` (new)

Hand-/3-way merged (multiple lanes):

- `src/ghostconvert/bundle.py` — harden (manifest validation in
  `load_bundle`: non-object top level, non-string `root`, per-entry
  type checks, no silent entry drops) + polish (docstrings on
  `BundleFile`, `Bundle`, `included`/`excluded`, `load_bundle`).
  Disjoint regions; both survive intact.
- `src/ghostconvert/convert.py` — harden (Cursor group-slug collision
  disambiguation with `-2`, `-3` suffixes in `render_cursor`) +
  polish (renderer/grouping docstrings). Disjoint regions.
- `src/ghostconvert/cli.py` — all three lanes. Harden: `--to all`
  all-or-nothing planning/pre-flight in `_cmd_convert` and `OSError`
  handling in `_write_artifacts` (clean exit 2, no traceback).
  Polish: help text, epilogs, `--to TARGET` metavar, and docstrings.
  Deepen: `verify` subcommand, `_cmd_verify`, `verify_target` import.
  The module docstring merged cleanly on its own: deepen's title
  (`convert | inspect | targets | verify`) and exit-1 line both
  survive alongside polish's Examples block.
- `README.md` — polish (bundle definition, try-it, target-picker,
  Troubleshooting table, Development note) + deepen (verify Quick
  start line, "Verifying a conversion" section, exit code 1 in the
  exit-code list). Both survive; sections coexist in order.

## Conflicts and resolutions

- No file-level merge conflicts: all 3-way merges were clean.
- One hand adjustment in `cli.py` after the mechanical merge:
  polish's `main()` docstring and `--help` epilog described only exit
  codes 0 and 2 (correct for polish alone, which had no `verify`).
  With deepen's subcommand merged in, those two texts now also state
  exit 1 (verify found an output that does not match its bundle), so
  the help output agrees with the module docstring and README. This
  is a wording-only reconciliation; no lane logic was altered and no
  harden fix was touched.
- Deepen's `verify` subparser was kept verbatim (shorter help style
  than polish's subparsers); no polish-style description was invented
  for it.

## Verification beyond the suite

- `--help` renders with all four subcommands and the reconciled
  exit-code epilog; `verify --help` renders cleanly.
- Smoke check: `verify examples/sample_bundle
  examples/converted/agents --to agents` reports the committed
  example's LOSSES.md as stale and exits 1. This is NOT a merge
  artifact: the deepen lane alone produces the identical result on
  its own tree (the committed example output predates the current
  renderer). Noted here as pre-existing, left as-is.

## Suspicious / notes

- Nothing else suspicious. No harden fix was dropped or weakened;
  merged-vs-lane diffs were audited and contain exactly the other
  lanes' changes for every shared file.
- Pristine tree untouched; nothing pushed to GitHub.
