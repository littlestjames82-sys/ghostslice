# GhostExposure - Agent B Report (tests / README / examples)

Date: Oct 14, 2026. Ownership honoured: only `tests/**`, `README.md`,
`examples/**`, and this file were created or edited. No edits to
`src/**`, `pyproject.toml`, or `surfaces/**`. No network, no push, no
publish, no spend.

## Final result

**25 passed, 0 failed** - `python3 -m pytest tests -q` in
`~/workspace/ghostexposure` (11.22s, final confirmation run after this
report was written is recorded in the handoff).

## Run history (honest)

1. First run, while Agent A's core was still landing: **10 passed,
   15 failed**. Most failures were one root cause in my fixtures, not
   the core: my surface pack used a `dated` field where the core's
   validator requires `date`, it lacked the required `kind: "surface"`
   and `description` fields, and its `coverage_limits` was a string
   where the core expects a list.
2. I read the core (read-only) and aligned my fixtures and docs to its
   actual contract. Contract differences found and recorded below.
3. Two test-side fixes that were NOT core problems:
   - `basic_project/auth/login.py` originally imported
     `util/format.py`, which correctly makes that helper graph context
     (a callee of a surface file), contradicting the fixture's "OUT"
     intent. The fixture no longer imports it, so OUT is graph-correct,
     not asserted against the tool's own rule.
   - One docs assertion banned the phrase "certified compliant"
     anywhere in the README, including inside the required negated
     disclaimer. It now asserts the disclaimer exists and caps
     assurance-word occurrences instead.
4. Final run: **25 passed**.

## What was built

### tests/ (25 tests)
- `test_partition.py` - Verification bar #1: on the basic fixture,
  in + out + conflict equals the inventory exactly (disjoint, zero
  unaccounted); surface decisions for `auth/login.py` and
  `payments/charge.py` are IN, `util/format.py` and `docs/guide.md`
  are OUT; bundle payload contains no OUT file and does contain the
  surface files.
- `test_conflict.py` - `auth/session.py` in the conflict fixture is
  matched by the pack's `auth/**` glob and pinned out in
  `.ghostslice.json`: scan must list it as a conflict, and export must
  either refuse naming it or mark it `conflict` in `exposure.json`.
  (Core behaviour observed: export refuses without
  `--exclude-conflicts`, naming the file.)
- `test_planted_key.py` - Verification bar #3: the planted FAKE secret
  (a test-only literal in a secret shape, labelled as fake in the
  fixture) appears in zero files of a default export, a redaction
  record naming `secrets_config.py` exists in `exposure.json` or
  `manifest.json`, and the source project file is byte-identical
  after export.
- `test_tamper.py` - Verification bar #2: a clean bundle verifies;
  adding `added_extra.py` to the payload makes verify fail and name
  it; removing `auth/login.py` makes verify fail and name it.
- `test_limit_statements.py` - Verification bar #4: exported
  `EXPOSURE.md` contains both the coverage-limits statement and the
  cannot-prove statement (fragment-checked against the plan's ideas,
  so wording variants pass and omissions fail), verify output states
  the cannot-prove limit, and the sample docs carry both statements.
- `test_fixtures.py` - fixture self-tests (pack validity, real
  conflict in the fixture, exactly one fake secret, basic shape).
  These need no core and always run.
- `test_docs_examples.py` - README/examples guards (both audiences,
  evidence language, redaction default, valid example pack).
- `conftest.py` + `helpers.py` - CLI discovery (installed executable,
  else `python -m ghostexposure` with `src/` on PYTHONPATH) and a
  schema-tolerant `exposure.json` reader. CLI tests skip with "core
  not ready" if no core exists, so this suite stays meaningful while
  the core is absent.

### Fixtures (all invented, no real code)
- `tests/fixtures/basic_project/` - auth, payments (Stripe import),
  a caller in `app/main.py`, personal-data-shaped fields in
  `app/profile.py`, an unrelated helper, docs.
- `tests/fixtures/conflict_project/` - glob match + user pin-out on
  the same file.
- `tests/fixtures/planted_key_project/` - a surface project whose
  config file holds the planted fake secret.
- `tests/fixtures/surfaces/starter-surface.json` - the test surface
  pack, aligned to the core schema (below).

### README.md
Written for both sides of the hand-off as the plan requires: a sender
section (write a pack, pins, scan, export, redaction default and the
`--allow-unredacted` flag, what to send) and a receiver section
(verify first, read EXPOSURE.md, what verify proves and cannot prove).
Evidence language throughout; it states plainly that the tool is not
a security audit, does not certify anything, and cannot prove a
sender did not share other files by another channel.

### examples/
`README.md` walkthrough, `starter-surface.example.json` (valid
against the core schema), `mini_project/` (one auth file, one
unrelated helper), and `sample_EXPOSURE.md` containing both required
limit statements verbatim in spirit and checked by test.

## Core contract as observed (assumptions resolved)

My initial assumptions, written before the core landed, differed in
these places. The core's choices were adopted; core code was not
changed by Agent B:

| Topic | My assumption | Core (actual) |
|---|---|---|
| Pack date field | `dated` | `date` (required) |
| Pack required fields | id, version, patterns | also `kind: "surface"`, `description`, `coverage_limits` (list) |
| Pin keys in `.ghostslice.json` | `pin_in` / `pin_out` | `pinned_in` / `pinned_out` |
| Unredacted flag | unnamed in plan | `--allow-unredacted`, recorded in `exposure.json` |
| Conflict at export | refused or marked | refused by default; `--exclude-conflicts` records an explicit out decision |
| exposure.json schema | `files[]` with path/decision | matches, and also mirrors the list under `partition` |
| Bundle layout | `files/` + manifest + exposure.json + EXPOSURE.md | matches, plus `PROMPT.md` |

## Not covered / risks for parent verification

- `scan --json` output shape and the `packs` subcommand are not
  asserted; tests use the text CLI and exported artifacts.
- The tests use Agent B's surface pack, not `surfaces/starter.json`
  (Agent A). Its glob style differs (`*auth*` vs `auth/**`); a parent
  pass may want one test run against the shipped starter pack too.
- Graph-context assertions are limited to payload/partition
  consistency. Whether distance-1 neighbours are exactly right for
  non-Python files is the core's parser-lite limit, stated in the
  README, and not deeply asserted here.
- If the core CLI changes argument names, `conftest.py` is the one
  place that needs updating.
