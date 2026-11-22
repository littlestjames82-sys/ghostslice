# GhostFixture v0.1 - Agent B report (tests, README, examples)

Ownership respected: only `tests/**`, `README.md`, `examples/**`,
and this file were written. No edits to `src/**`, `pyproject.toml`,
or `PLAN.md`. No core defects were fixed by Agent B; none were
found against the final core (see the process note below).

## Final results against the real core

Command: `python3 -m pytest tests -q` from the repo root, CLI
discovered as `python -m ghostfixture` with `PYTHONPATH=src`.

- Full suite: **32 passed, 0 failed** (two consecutive full runs,
  9.99s and 20.15s).
- Per file:
  - tests/test_fixtures.py: 6 passed
  - tests/test_cli_build.py: 10 passed
  - tests/test_cli_safety.py: 5 passed
  - tests/test_cli_check.py: 6 passed
  - tests/test_mcp.py: 1 passed
  - tests/test_docs_examples.py: 4 passed
- Examples walkthrough run by hand against the real CLI: build
  exit 0 (3 files, 414 bytes, cap stated as 2097152, keys.py
  excluded-flagged as [stripe-key]), check exit 0, and the fake
  example canary is absent from the built fixture tree.

## What the suite pins (PLAN.md verification bar + hard rules)

- Closure: the repro fixture's main.py imports helper.py, which
  imports util_math.py; neither is in the bundle. Both land in
  the fixture with reason `import-closure` and their importers
  named in the manifest.
- Planted secret: `app/secrets_store.py` is bundle-referenced
  and carries a fake Stripe-shaped canary
  (`sk_live_FIXTURECANARY...`, test-only, never a real
  credential). Default build excludes it, records it under
  `excluded_flagged` with path + pattern types, and the canary
  string appears in no byte of the output tree and not in CLI
  output. `--include-flagged` includes it and the manifest
  still records the flag with `included_by_override`.
- No-touch: source project tree hashes (sha256 per file) are
  identical before and after a build; a build aimed inside the
  project is refused and the project is unchanged; an existing
  non-empty output directory is refused and its contents are
  untouched.
- Unreferenced files (unrelated.py, notes.txt) are absent from
  the fixture tree and from the manifest's included list.
- A manifest entry at mode `exclude` is never copied, even
  though a seed file imports it (config.py case).
- A referenced file deleted from the project is left out with
  reason `missing-in-project`; the build still exits 0.
- Size cap: the big fixture's referenced files total about
  5.1 KB; with `--max-bytes 3000` the build keeps
  pkg/__init__.py, pkg/alpha.py and pkg/beta.py, leaves
  pkg/gamma.py and pkg/delta.py out with reason `size-cap`,
  keeps `totals.bytes_copied` at or under 3000, and states the
  cap in both the manifest (`max_bytes`) and the CLI output.
- Symlinks: a referenced symlink resolving outside the project
  is left out with reason `symlink-escapes-root` (the test also
  accepts `outside-root`); a symlink pointing inside the project
  is copied as content, not as a link.
- Check round trip: fresh fixture exits 0; editing a copied
  file exits 1; an unexplained extra file exits 1; planting
  the excluded flagged file into the tree exits 1; restoring
  the original bytes returns to 0; a missing directory exits 2.
- MCP: stdio initialize + tools/list returns `build_fixture`
  and `check_fixture`.
- Docs: README states the trust rules and honest limits, no em
  dashes in README.md or examples/README.md, walkthrough files
  and premises verified.

## Process note (transient failures, not defects)

The first full-suite run showed 3 failures
(test_build_succeeds_and_writes_manifest_and_summary,
test_secret_flagged_file_excluded..., and
test_manifest_exclude_mode_is_never_copied). Evidence: Agent A
was still editing the core during that run - `src/ghostfixture/
build.py`, `bundle.py`, `reports.py` and `secrets.py` all carry
13:35 mtimes, inside the run window - so the suite exercised a
half-updated core. Both failing tests passed in isolation
immediately after, and the full suite has passed twice since
with no test changes in between. Recorded here so the parent
does not have to take the green result on faith: rerun the
suite and it should read 32 passed.

## Assumptions

- The CLI contract is PLAN.md's, confirmed against the landed
  `src/ghostfixture/cli.py`: `build <project> <bundle> -o <out>`
  (project first), `--max-bytes`, `--include-flagged`,
  `check <fixture-dir>`, `mcp`. Only the command prefix is
  discovered (GHOSTFIXTURE_CMD env, PATH, then
  `python -m ghostfixture` with PYTHONPATH=src); CLI tests skip
  cleanly if none responds.
- Test bundles are built at test time by tests/helpers.py
  (GhostSlice-shaped: manifest.json with per-file sha256 and
  totals, PROMPT.md, files/ copies), so manifest roots and
  hashes are honest for each test's temp copy of a fixture
  project. Fixture token counts use a chars/4 estimate; internal
  consistency is asserted, not parity with Slice's estimator.
- The size-cap kept-set assertion assumes bundle order (which
  is also path order for the big fixture) drives the
  deterministic keep order, as the plan states
  bundle-referenced files first in deterministic order.

## Gates held

Stdlib only (tests, examples and docs use nothing outside the
standard library plus pytest as the runner), local only, no
network, no GitHub push, no PyPI/publish, no announcements,
no spend.
