# GhostRecall - Agent B Report (tests / README / examples)

Date: 2026-10-14. Scope owned: `tests/**`, `README.md`, `examples/**`,
this file. No edits to `src/**` or `pyproject.toml`. Gates respected:
stdlib only (tests use pytest + stdlib), no network, no push, no
publish, no spend.

## What was delivered

- `tests/conftest.py` - CLI runner (console script or
  `python -m ghostrecall`, PYTHONPATH=src), manifest loader with
  field-alias normalisation, bundle text scanners, fixture copiers.
  Tests target the public CLI and bundle format only; they never
  import ghostrecall internals.
- `tests/test_provenance.py` - verification bar 1.
- `tests/test_superseded.py` - verification bar 2.
- `tests/test_secrets.py` - verification bar 3.
- `tests/test_modes_and_bundle.py` - modes, pinning, combined bundle,
  fit budget, check (good / tampered file / tampered prompt).
- `tests/test_profile_and_boundary.py` - unknown profile key fails
  loudly, outside-project sources never imported, explain shows
  non-selected items, recall ranks with token costs.
- Fixtures: `tests/fixtures/provenance_project/`,
  `superseded_project/` (publish hold D-010 lifted by D-011),
  `secret_project/` (planted synthetic key in docs/private-note.md).
- `README.md` - product README incl. the documented DECISIONS.md
  format, modes table, profile, secrets guard, MCP tools, limits.
- `examples/` - `sample_project/` (decisions incl. a superseded pair,
  notes, changelog, citing code), `DECISIONS.example.md` starter,
  `examples/README.md` with walkthrough commands.

## Timing note

When this work started the tree held only `PLAN.md`. Agent A's core
(`src/ghostrecall/**`, `IMPLEMENTATION_A.md`) landed while the tests
were being written; the first full run overlapped the last core edits
and is superseded by the final run below (core file timestamps stable
from 13:05 UTC, final run 13:09-13:10 UTC).

## Final test result (honest)

`python3 -m pytest tests -q` -> **21 passed, 2 failed, 1 xfailed**
(exit 1). Both failures are one genuine core bug (F1). The xfail is
strict, so it will turn into a failure signal (XPASS) the day the
core fixes F4 - that is deliberate.

### Findings for Agent A / parent verification

- **F1 (FAIL, verification bar 2) - superseded decision served as
  current, and pinned.** In `superseded_project`, D-011 supersedes
  D-010, yet the bundle exports D-010 as a manifest item with
  `mode: full`, `status: "active"`, and `pinned: true` (it is tagged
  `rule`, and pinning wins over supersession), and its text appears
  in PROMPT.md with no superseded marking. PLAN: superseded items
  are "shown as superseded or excluded, never silently served as
  current." A superseded *standing rule* is the worst case: it will
  be pinned into every future bundle. Failing tests:
  `test_old_decision_never_served_as_current`,
  `test_old_decision_in_prompt_only_if_marked`.
- **F1b (observed) - spurious conflicts.** `recall` prints a
  `supersedes-in-bundle` CONFLICT line for decisions whose
  `Supersedes:` is `none` (seen on the examples project for D-001,
  D-002, D-004, and in a manual bundle run where a conflict entry
  read `current: D-010, superseded: none`). The conflict generator
  appears to fire per decision rather than per real supersession,
  which likely connects to F1's exclusion never being applied.
- **F4 (XFAIL strict) - `check` does not validate PROMPT.md.**
  `check_bundle` verifies exported files (sha256 + token totals)
  and PROMPT.md existence only; appending a line to PROMPT.md still
  returns "OK ... matches its manifest", even though the manifest
  carries `totals.prompt_tokens_estimate`. Test:
  `test_check_rejects_tampered_prompt`. The companion file-tamper
  test passes, so the manifest contract itself is enforced.
- **Design deviation noted, test adapted:** PLAN says the combined
  bundle "calls GhostSlice export for code". The core instead merges
  a pre-built Slice bundle supplied via `--slice-bundle`. That works
  and is arguably cleaner, but it is a contract change from PLAN.md;
  `test_combined_bundle_has_code_and_memory` builds a minimal
  GhostSlice-shaped bundle and passes it via `--slice-bundle`.
- **Secrets fixture calibration (test-side fix, recorded):** my
  first planted value contained the word FAKE and was exempted by
  the core scanner's placeholder filter (`fake`, `example`,
  `test-key`, ...), the same labelled-placeholder convention
  GhostSlice used for its own test keys. The fixture now plants a
  synthetic random-shaped value with no placeholder words (not a
  real credential), and all four secrets tests pass: the item is
  blocked/excluded, and the value appears in no bundle file, no
  manifest, and no CLI output.

## Assumptions (core contract the tests were written against)

- A1 CLI: `ghostrecall recall|bundle|check|explain`, module form
  `python -m ghostrecall`. (Matched the landed core; `explain` takes
  an extra positional `item` in the core, so the explain test falls
  back to `recall --explain`, which exists and passes.)
- A2 DECISIONS.md block format: `## D-nnn (YYYY-MM-DD)` + Decision /
  Reason / Supersedes / Status / Tags lines, `rule` tag = standing
  rule. (Matched the landed core's parser on all fixtures.)
- A3 Bundle: root `manifest.json` with the item list under `items`
  (aliases tolerated), merged `PROMPT.md` at bundle root. (Matched.)
- A4 Manifest item fields are per PLAN (source type, mode, original
  and sliced tokens, sha256) plus provenance and status; the loader
  tolerates alias names. (Matched; core status vocabulary is
  `active` where PLAN implies `current` - normaliser accepts both.)
- A5 Date is required in provenance for *decision* records; note/doc
  sections require source + line-or-commit only. This follows PLAN's
  wording ("every decision record carries provenance: source file,
  line or commit, date") and was narrowed from an earlier stricter
  reading after the core returned `date: None` for doc sections.
- A6 `--fit` follows GhostSlice discipline: fits, or writes the
  bundle and exits 1. The fit test accepts either.
- A7 `bundle` accepts `-o/--out`; combined code arrives via
  `--slice-bundle` (see deviation above).
- A8 MCP tools (`recall_search`, `recall_bundle`, `recall_explain`)
  are documented in the README from PLAN.md; they are not exercised
  by this test suite (no MCP harness in scope for Agent B).

## Not verified by Agent B

- Dashboard panel (PLAN item 5) and MCP server behaviour.
- Git-history sources (no fixture initialises a git repo; commit
  provenance is asserted only as the line-or-commit alternative).
- Performance on a large real project; the PLAN demo on GhostSlice's
  own audits/roadmap as corpus was not run as a test.
