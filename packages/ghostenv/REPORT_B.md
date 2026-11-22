# GhostEnv v0.1 - Agent B Report (tests / docs / examples)

Status: COMPLETE. Final result against Agent A's finished CLI:
**29 passed, 0 failed, 0 skipped** under pytest, and **29 tests OK**
under plain `python -m unittest discover -s tests`.

Ownership respected: only `tests/**`, `README.md`, `examples/**`,
and this `REPORT_B.md` were created. No edits to `src/**`,
`pyproject.toml`, or `PLAN.md`. Local only: no push, no publish,
no announcements, no spend.

## What Agent B built

- `tests/helpers.py` - black-box CLI discovery (GHOSTENV_CMD,
  PATH executable, or `python -m ghostenv` with PYTHONPATH=src,
  probed via `--help`), help-driven subcommand discovery with
  candidate fallback, lenient check/generate runners (multiple
  argument shapes), and TEST-side reference parsers (env-file
  names/duplicates/malformed, Python + JS code usage) so fixture
  tests can validate the fixtures without importing the product.
- `tests/fixtures/` - four invented projects, all values FAKE and
  labelled fake:
  - `clean_project/` - Python + JS; code usage == .env names ==
    .env.example names (verified: core and reference parser both
    find the same 5 names).
  - `missing_project/` - one name in each drift class:
    REQUIRED_IN_CODE_ONLY (hard), IN_ENV_NOT_EXAMPLE,
    STALE_IN_EXAMPLE, UNUSED_IN_ENV, SHARED_OK.
  - `canary_project/` - the leak fixture, see below.
  - `malformed_project/` - a no-equals line, a nameless `=value`
    line, and DUPLICATED_NAME defined twice.
- `tests/test_fixtures.py` (10) - fixture validity with no CLI:
  clean/missing set differences are exactly as intended, canaries
  are really planted (each on its own surface, none hiding in
  another file), malformed + duplicate are reference-detectable,
  and every fixture env value is fake-labelled or empty.
- `tests/test_cli_check.py` (6) - clean exits 0; missing exits
  non-zero and names REQUIRED_IN_CODE_ONLY and IN_ENV_NOT_EXAMPLE;
  FAKE fixture values never appear in output; malformed is
  reported (duplicate named) rather than silently passing; check
  modifies no pre-existing project file; a missing project path
  is an error, never a pass.
- `tests/test_cli_example.py` (3) - generated example lists all
  used names, carries no real values (every value empty or a
  labelled placeholder), includes CANARY_API_KEY by name only,
  and generation never touches the project's real .env.
- `tests/test_leak.py` (7) - THE leak test, below.
- `tests/test_docs_examples.py` (5) - README states the
  names-only rule and documents check + generate, no guarantee /
  certified wording; the example mini project is self-consistent
  under the reference parsers; every example value is empty or
  fake-labelled.
- `README.md` - install (pip + PYTHONPATH), quickstart, the
  three-set comparison, findings table, the names-only rule
  stated plainly, limits (dynamic lookups invisible, a clean
  check is evidence not proof an app will run, platform-injected
  names), v0.1 scope, tests, layout.
- `examples/` - mini project (app.py + .env.example with empty
  placeholders + a clearly labelled `.env.fake` showing shape
  only) and a walkthrough that breaks the example on purpose in
  a copy and regenerates it.

## The leak test

Three FAKE canaries, one per surface in the plan's verification
bar: a distinctive value in the fixture `.env`, a distinctive
literal in a code default argument (core records a has_default
boolean only), and a distinctive string in an `.env.example`
comment (generated examples regenerate comments from names
alone). The test runs scan, scan --json, check, check --json,
example -o, example --stdout, --help, and --version; captures
stdout/stderr; diffs a pre-run hash snapshot to read only files
the run created or changed; and asserts none of the three
canary strings appears anywhere. It also asserts scan DOES list
CANARY_API_KEY by name, so the pass is about values, not about
the tool saying nothing. Fixture tests prove each canary is
really planted, so the leak pass is not vacuous.
**Result: no leak on any surface.**

## Assumptions (written while Agent A's core was still landing)

1. The suite was started before PLAN.md existed, so helpers
   discover subcommands from `--help` with candidate lists
   (check/scan/doctor/... and example/generate/...). When Agent
   A's CLI landed it matched the primary guesses exactly:
   `scan <project> [--json]`, `check <project> [--json]`,
   `example <project> [-o path] [--stdout] [--force]`, exit
   0/1/2. The lenient discovery stays, harmlessly.
2. Reports: the plan writes no report files for scan/check
   (terminal/JSON only), so tests assert on stdout/stderr plus
   any file a run creates or changes, found by hash diff rather
   than by an assumed report filename.
3. Generated-example values: accepted when empty OR a clearly
   labelled placeholder. The shipped core emits strictly empty
   values, which passes the stricter reading too.
4. Malformed semantics are not pinned beyond duplicate
   reporting (the core parser silently skips unparseable lines
   by design), so the malformed test requires the duplicate to
   be visibly reported or a non-zero exit, never a silent pass.
   Observed core behaviour: duplicate named with both line
   numbers, exit 1.

## Test runs (honest timeline)

- First full run against the landed core: **28 passed, 1
  failed**. The failure was Agent B's own fixture guard: it
  demanded every `.env` value be fake-labelled, including the
  malformed fixture's intentionally nameless `=VALUE_WITH_NO_NAME`
  line. The guard now skips lines with no valid name (they are
  the malformed case, checked elsewhere). No core bug.
- Final: **pytest 29 passed** and **unittest discover 29 OK**.
- Manual spot checks matching the tests: clean fixture check
  exit 0 ("contract complete: no missing names found by static
  scan"), missing fixture exit 1 naming both planted gaps,
  scan on the canary fixture lists all 3 names with no canary,
  `example --stdout` on the missing fixture emits the full union
  as grouped `NAME=` lines only.

## One quirk flagged for the parent (Agent A's surface)

On a duplicate-only project (malformed fixture), `check` exits
1 - per IMPLEMENTATION_A.md, duplicates count toward exit 1 -
while its verdict line still reads "contract complete: no
missing names found by static scan". The verdict wording is
scoped to missing names, but a reader seeing exit 1 next to
"contract complete" may be confused. Agent B's tests accept the
behaviour (duplicate visibly reported); whether to reword the
verdict is Agent A's / the parent's call, not changed here.
