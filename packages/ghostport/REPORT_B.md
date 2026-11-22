# GhostPort - Agent B Report (tests / README / examples)

Date: Oct 14, 2026. Scope owned: `tests/**`, `README.md`, `examples/**`,
this report. Nothing under `src/**`, `pyproject.toml`, or `patterns/**`
was edited by Agent B. No network, no push, no publish, no spend.

## Result at a glance

**Suite: 24 tests, 22 PASS, 2 FAIL.** Both failures are deliberate,
documented known-gap tests against Agent A's pack v1.0.0 (see below);
the fixes live in `patterns/**` / `src/**`, outside B's ownership.
Everything else, including all of PLAN.md's verification-bar items that
B owns, passes against the real core.

Run: `python3 -m unittest discover -s tests` from the repo root.

| File | Tests | Result |
|---|---|---|
| test_fixtures_integrity.py | 11 | PASS |
| test_scan_patterns.py | 4 | PASS |
| test_ordering.py | 2 | PASS |
| test_cycle.py | 1 | PASS |
| test_ledger_status.py | 3 | PASS |
| test_bundle.py | 1 | PASS |
| test_pack_gaps.py | 2 | **FAIL (known pack gaps, below)** |

## What was built

### Tests (`tests/`, stdlib unittest only)

Two layers, in `_helpers.py` terms:

- **Layer 1, fixture integrity** (runs with or without the core):
  pins the fixtures to the plan's verification bar so a core failure
  cannot be a fixture failure in disguise. All pattern fixtures parse
  as Python; positives contain their triggers; look-alike negatives do
  not; every pattern (and the one proposed pattern) is dated and
  referenced in `fixtures/patterns/expected.json`.
- **Layer 2, core black-box**: copies fixtures to a temp dir and drives
  the real CLI (`scan` / `plan` / `bundle` / `status`, module entry
  point with `src/` on PYTHONPATH, `--json` where the plan implies a
  machine view). Fixtures are never mutated by a run; one test asserts
  scan leaves a project byte-identical, another asserts bundle leaves
  source `.py` files byte-identical (planner-only rule).

Coverage of PLAN.md's verification bar:

- **Per-pattern positive + look-alike negative for the first pack**:
  all 12 patterns of pack v1.0.0 (`PYUP001`-`PYUP012`), one positive
  file that must be hit with its pattern id and one negative file that
  must produce no hit for that id. PASS for all 12.
- **Ordering fixture**: `ordering_project` (app -> mid -> leaf import
  chain, each touched). Plan must sequence leaf, mid, app; covering
  tests attach by import graph (the fixture test file really imports
  the leaf). PASS.
- **Cycle fixture**: `cycle_project` (x <-> y, both touched). Plan must
  combine both files into exactly one unit and name the cycle. PASS.
- **Resume-from-ledger fixture**: `resume_project` seeds a ledger with
  planned / bundled / **ported-claimed** events and a minimal
  `port-plan.json`; no entry references a Verify report. `status`
  shows verified 0, counts planned 1 / ported-claimed 1 (latest state
  per unit), and next unit `unit-pkg-app`. PASS: a claim is not
  verification.
- **Clean/honesty fixture**: modern Python project plus a JavaScript
  file. Scan reports zero hits, keeps the "hits for pack ... does NOT
  mean ready to upgrade" honesty phrasing, and names javascript as not
  covered. PASS.

### README.md

Full README in the GhostSlice house style: quickstart for
scan/plan/bundle/status, the 12-pattern table aligned to pack v1.0.0,
the ledger/"verified" rules, the profile section, and explicit
non-goals (no codemods, no test running, never "ready to upgrade").
It states v0.1 is in build rather than claiming a release.

### Examples (`examples/`)

- `demo_project/`: 3-file legacy project, one hit per file, real
  dependency chain (storage + plugin_loader leaves, report on top).
  Verified by hand against the real core: scan reports exactly the 3
  documented hits (`PYUP006`, `PYUP004`, `PYUP003`).
- `sample_port_plan/`: clearly-labelled sample `PORT_PLAN.md`,
  `port-plan.json`, and a `UNIT.md` checklist using core's real unit-id
  form (`unit-legacy-storage`, ...).
- `ghostslice-profile-snippet.json`: the `port` profile section;
  parses as JSON, pack set to `python-upgrade`.
- `examples/README.md`: walkthrough.
- Note: `examples/fixture/**` was created by Agent A in parallel and
  was left untouched by B.

## Known gaps found in core/pack (the 2 failing tests)

Pinned in `tests/test_pack_gaps.py`, unskipped on purpose:

1. **PYUP005 distutils from-import form missed.** The pattern's
   `import_module` matcher matches `from X import ...` only when the
   module equals `distutils` exactly, so the idiomatic
   `from distutils.core import setup` yields 0 hits. (The positive
   fixture also carries a plain `import distutils`, which does hit, so
   the per-pattern test passes; this gap test isolates the from-form.)
2. **PYUP007 misses `Thread.isAlive()`.** The matcher's name list has
   currentThread / activeCount / isDaemon / setDaemon but not isAlive,
   which was removed in Python 3.10 on the same cleanup the pattern
   cites.

Suggested fixes for the core owner: treat `import_module` ImportFrom
modules as a prefix match (`distutils`, `distutils.*`), and add
`isAlive` (and consider `isSet`/`setName` era aliases) to PYUP007.

## Assumptions made, and how they resolved

B started before the core landed, so the suite was first written
against PLAN.md's contract (CLI names from the plan, pack id
`python-upgrade`). When Agent A's core appeared mid-build, B read it
(read-only) and reconciled everything B owns to the real thing:

- **Pattern ids**: B's first draft guessed hyphenated ids
  (`PYUP-001`...) and a different pattern set. Superseded by A's
  authoritative pack: 12 patterns, ids `PYUP001`-`PYUP012`, no hyphen.
  `expected.json`, README, examples, and fixture docstrings were all
  rewritten to match `patterns/python-upgrade.json` v1.0.0.
- **Unit ids**: core form is `unit-<slug-of-path>` (combined cycle
  units `unit-cycle-...`); examples and the resume fixture use it.
- **Ledger/status shape**: status counts are latest-state-per-unit and
  need a `port-plan.json` in the project; the resume fixture ships a
  minimal one in core's shape and the expected counts are written in
  those terms.
- **`fractions.gcd`**: B's draft included it as a pattern; pack v1.0.0
  does not. Its fixture pair is kept as a **proposed** pattern in
  `expected.json` (clearly marked, no core hit expected), not silently
  dropped and not presented as shipped.
- Core also ships `claim` and `verify` commands (beyond the plan's
  four); B's README describes the ledger rules they implement but does
  not document their flags in the quickstart.

## Not done by B (by design / ownership)

- The plan's ground-truth demo (hand-checking the first 20 hits on a
  real Ryan repo) belongs with the core build report (Agent A /
  parent verification), not this report. B's equivalent check is the
  demo project above: 3/3 documented hits, hand-verified.
- Fixing the two pack gaps (files outside B's ownership).
- No `ghostslice check` validation of Port bundles was attempted:
  core bundles are GhostSlice-*shaped* with their own manifest, and
  PLAN.md's "validates with ghostslice check" wording should be
  re-checked by the parent against what core actually emits.
