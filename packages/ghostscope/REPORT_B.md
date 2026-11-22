# GhostScope - Agent B Report (tests / README / examples)
Date: Oct 14, 2026. Scope owned: tests/**, README.md, examples/**, REPORT_B.md.
No files in src/** or pyproject.toml were edited by Agent B.

## Deliverables
- `tests/fixtures/` - three planted fixture projects, each as a `base/`
  tree (committed as the git base in tests) plus a `change/` overlay
  and, where relevant, a `deletions.txt`:
  - `high_blast_radius/`: `compute_total` in `shared.py`, exported via
    `__all__`, called by 6 caller modules, with a covering test.
    Change: exactly one line in `shared.py`; `isolated.py` grows to
    222 lines with zero callers.
  - `signature_change_stale_caller/`: exported `format_name(first, last)`
    with two callers and a covering test. Change: signature gains a
    required `middle` parameter; no caller overlay exists, so both
    callers stay stale by construction.
  - `deleted_covering_test/`: `charge` in `billing.py`, one caller,
    covering test in base. Change: `billing.py` edited and
    `deletions.txt` removes `tests/test_billing.py`.
- `tests/test_fixtures_static.py` - 12 tests validating the fixtures
  themselves with stdlib `ast` (caller counts, one-line diff, 200+
  line isolated change, arity change 2 to 3, stale callers,
  deletion declared). Needs no core.
- `tests/test_pack_integration.py` - 13 tests implementing the PLAN.md
  Verification bar against the real CLI: riskiest-first ranking with
  caller count as the stated reason, completeness (all 6 direct
  callers in the pack, none excluded), factual signature-change /
  stale-caller note citing file + symbol, plain-words "no covering
  test / covering test deleted" honesty check, pack artifacts
  (REVIEW.md, scope.json, manifest.json), scope.json base/head,
  manifest totals reproduce, and an optional `ghostslice check`
  cross-check when ghostslice is on PATH.
- `tests/helpers.py` - git fixture builder (local git only), core
  discovery, pack runner, pack-artifact search, JSON flattening.
- `tests/conftest.py` - stops pytest collecting the fixture projects'
  own `test_*.py` files (they are GhostScope input data).
- `README.md` - interface as defined in PLAN.md: install, quickstart
  (`pack --base/--head`, `--staged`, `--diff`), pack layout, risk
  reasons, `.ghostslice.json` `scope.sensitive_paths` profile, `--fit`
  rule (changed files never downgraded, exit 1 when unfittable), what
  v0.1 does not do, MCP tools, test instructions.
- `examples/run_demo.sh` - builds the high-blast fixture as a local
  git repo and packs it if a core is importable; otherwise prints the
  expected outcome and exits 3.
- `examples/sample_pack/` (`scope.json`, `REVIEW.md`) and
  `examples/README.md` - the documented shape of a finished pack.
  Both sample files are labelled in-file as hand-written illustrative
  samples, NOT captured run output.

## Assumptions (core was not ready when Agent B built)
Recorded because Agent A (src/**) was building in parallel:
1. CLI form: `ghostscope pack <project> --base <ref> --head <ref>
   -o <outdir>` (module form `python -m ghostscope`). The test helper
   also tries `--output` and a bare invocation before failing.
2. Pack layout: GhostSlice-style bundle with `manifest.json`, plus a
   `scope.json` sidecar carrying base/head, per-file graph distance,
   mode, and risk reasons, plus `REVIEW.md` in riskiest-first order.
   Tests locate artifacts by recursive search, not exact paths, and
   search risk-reason text across both REVIEW.md and scope.json.
3. Risk reasons are textual and include a caller count (for example
   "6 callers"). Tests accept `6 callers`, `callers: 6` style variants.
4. Covering-test / stale-caller / signature notes are textual in
   REVIEW.md or scope.json and cite file + symbol, per PLAN.md
   section 4.
If Agent A's final interface differs (flag name, sidecar filename,
field names), the integration tests are the contract to reconcile
against: adjust `tests/helpers.py` discovery first.

## Honest test results (Agent B run, Oct 14, 2026)
Command: `PYTHONPATH=.:src python3 -m pytest tests -q`

- At run time the core was NOT ready: `src/ghostscope/` existed but
  was empty when testing started. Result: **12 passed, 13 failed**.
  - Passed: all 12 tests in `test_fixtures_static.py` (fixtures are
    valid and carry the planted properties).
  - Failed: all 13 tests in `test_pack_integration.py`, every one in
    setUp with "GhostScope core not found". This is deliberate: the
    integration tests fail rather than skip while the core is
    missing, so the combined tree cannot look greener than it is.
- During the same window Agent A's files began landing
  (`__init__.py`, `__main__.py`, `outline.py`, `profile.py`,
  `scanner.py`, `tokens.py` were present at last listing). At that
  listing `__main__.py` imports `.cli`, which was not yet present,
  and a `python -m ghostscope --help` probe during that in-flux
  period failed with `ModuleNotFoundError: No module named
  'ghostscope.cli'`. Agent B did not
  re-run the integration suite against the half-landed core; the
  numbers above are from the clean pre-core run.
- `examples/run_demo.sh` executed: built the fixture repo, found no
  importable core at that moment, printed the expected outcome, and
  exited 3 as designed.
- `examples/sample_pack/scope.json` validated as JSON.

## Parent verification steps (after Agent A handoff completes)
1. `cd ~/workspace/ghostscope && PYTHONPATH=.:src python3 -m pytest tests -q`
   Expected if the core matches the assumed contract: 25 passed
   (the ghostslice cross-check inside TestPackValidation skips only
   if ghostslice is not on PATH).
2. If integration failures are interface mismatches rather than core
   bugs, check the failure text first: artifact names, flag names,
   and reason wording are the three likeliest seams (see Assumptions).
3. `sh examples/run_demo.sh` should print a real REVIEW.md.

## Gates honoured
Local git fixtures only, no network, no push, no publish, no spend.
Nothing in this report claims the core works: as of Agent B's run,
the Verification bar is encoded and fixture-proven, and the core
half is still to be demonstrated.
