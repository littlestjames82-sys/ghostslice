# GhostConvert v0.1 - Agent B report (tests, README, examples)

Date: Oct 14, 2026. Scope owned: `tests/**`, `README.md`, `examples/**`,
this report. No core files (`src/**`, `pyproject.toml`, `PLAN.md`) were
edited by Agent B.

## Final result

**58 passed, 0 failed, 0 skipped** - `python3 -m pytest tests -q` from
`~/workspace/ghostconvert`, run three times against Agent A's landed
core with identical results (36 to 47 seconds per run; the golden
bundle is rebuilt by the real GhostSlice once per session).

The suite is black-box: it drives the real CLI as a subprocess,
discovered via `$GHOSTCONVERT_CMD`, then `ghostconvert` on PATH, then
`python -m ghostconvert` with `PYTHONPATH=src` (the route used here).
It skips cleanly only when no CLI is discoverable at all.

## What the suite pins

- `tests/test_fixtures.py` (6 tests): the golden bundle is built by the
  real GhostSlice 1.0.6 from a fixture project with mixed modes
  (`src/app.py` full, `src/util.py` signatures, `vendor/blob.py`
  exclude, `tests/test_app.py` strip-tests by Slice default). Manifest
  entries carry token counts, `files/` bodies match their manifest
  sha256 values, and `PROMPT.md` section headers match the manifest.
- `tests/test_cli_contract.py` (8 tests): `targets` lists all four
  targets and artifact paths; `--version` reports 0.1.0; `inspect`
  prints the project name, the mode census, and the manifest totals
  and writes nothing; missing bundle, unknown target, missing `--to`,
  and no command all exit 2.
- `tests/test_convert_targets.py` (13 cases via parametrization): for
  agents, copilot, and generic, sections appear in exact manifest
  order, every body from `files/` appears verbatim, and every section
  header carries its mode label; document targets open with the
  GhostConvert header; Cursor writes one frontmatter `.mdc` per
  top-level directory group (globs naming the original paths), keeps
  manifest order inside each group, and places each body exactly once;
  `--to all` writes four subdirectories whose agents output is
  byte-identical to a standalone agents run; the excluded file's body
  appears in no artifact.
- `tests/test_immutability.py` (8 cases): sha256 of every file in the
  source bundle is identical before and after conversion for all five
  target settings (`agents`, `cursor`, `copilot`, `generic`, `all`),
  after `inspect`, and after a refused run; no artifact file names
  appear inside the bundle.
- `tests/test_losses.py` (13 cases): every target's `LOSSES.md` names
  the excluded file (`vendor/blob.py`), the per-file sha256 values,
  and the per-file token estimates; Cursor's note names the grouping;
  a crafted zero-loss generic conversion still writes `LOSSES.md` and
  says "No losses recorded"; a manifest file with no body anywhere is
  named in `LOSSES.md` and in `inspect`, absent from the artifact; an
  escaping manifest path (`../evil.py`) is skipped, named in both
  `LOSSES.md` and `inspect`, and the sentinel file outside the bundle
  is never read; a `symbols` entry's header lists its
  `symbols_included`; bodies are recovered from `PROMPT.md` when
  `files/` is absent entirely.
- `tests/test_safety.py` (10 tests): malformed manifest, missing
  manifest, manifest without a `files` list, bundle with no readable
  bodies, output equal to or inside the bundle, and a bundle path
  that is a file all exit 2 with nothing written; overwrite without
  `--force` exits 2, names the collision, and leaves the existing
  artifact untouched (including no partial writes when only
  `LOSSES.md` pre-exists); `--force` overwrites.

## Plan verification bar, checked one by one

- Golden bundle to all four targets, order and mode labels match the
  manifest: PASS (suite, per target).
- Losses test names the excluded file, the hashes, and the token
  estimates for each target: PASS (suite, per target).
- Immutability, sha256 before/after identical, no new file in the
  bundle: PASS (suite, all targets).
- Real-repo test: PASS, run manually by Agent B. A bundle exported by
  GhostSlice from the GhostSlice repo itself (143 manifest entries,
  96 with bodies, 569,561 to 190,227 estimated tokens) converted to
  all four targets with no error in under a second. The `AGENTS.md`
  output opens with the conversion header, and a programmatic check
  confirmed its 96 `## File:` sections match the manifest's
  body-carrying order exactly.

## Defects and observations (core territory, not fixed by Agent B)

No defect was found that fails a plan rule. Two observations, both
about wording rather than behavior:

1. **Sliced-to-empty files are reported as "no readable body."** A
   `strip-tests` entry in a real Slice bundle has `sliced_tokens: 0`
   and the empty-string sha256 by design: Slice deliberately emptied
   it, nothing is missing. GhostConvert reports such files under the
   `LOSSES.md` heading "Files with no readable body" ("No body was
   found in files/ or PROMPT.md for: tests/test_app.py") and as
   "Missing bodies" in `inspect`. The plan rule (missing bodies are
   converted as absent and named) is satisfied, and the file IS named
   rather than silently dropped, but the label conflates
   "deliberately emptied by Slice" with "body lost." A core-side
   refinement would distinguish entries whose manifest shows
   `sliced_tokens: 0` from entries that promise a body and lack one.
   Evidence: golden bundle conversion, any target's `LOSSES.md`;
   pinned as named-not-dropped by
   `test_bodyless_slice_entry_is_named_in_losses`.
2. **Unknown modes are carried, not flagged.** A manifest entry with a
   mode GhostConvert does not know (suite uses `banana-split`) is
   converted with its label printed verbatim in section headers and
   counted in `inspect`'s mode census. It is not silently dropped or
   relabelled, which satisfies the reporting rule at the visibility
   level, but no output line says the mode is unrecognized. An
   explicit "unknown mode" line in `LOSSES.md` or `inspect` would be
   a core enhancement. Pinned by
   `test_unknown_mode_is_reported_not_silently_dropped`.

## Examples

`examples/` holds one bundle converted to all four formats:
`sample_project/` (the fixture source), `sample_bundle/` (exported by
the real GhostSlice), and `converted/` (the `--to all` output, with a
`LOSSES.md` per target). `examples/README.md` documents the
regeneration commands and the points of interest (manifest order, the
signatures-mode warning, the stripped test file named in losses, the
excluded vendor file). GhostSlice's cache and history debris from the
export run was removed from the sample project so the example ships
clean.

## Gates held

Python standard library only (tests use pytest as the runner only),
local only, no network, no GitHub push, no PyPI or publish step, no
announcements, no spend. README and examples contain no em dashes.
