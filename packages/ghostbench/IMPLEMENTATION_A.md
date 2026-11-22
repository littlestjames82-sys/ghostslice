# GhostBench v0.1 - Implementation Record (Agent A, core)

Built Oct 14, 2026 from ~/workspace/ghostbench/PLAN.md.
Scope of this agent: src/**, pyproject.toml, this file only.
Tests, README and examples are Agent B's surface (not edited here).
Gates honoured: Python stdlib only, no network, no live agent runs,
no model/API spend (none was made), no push / publish / release.

## What was built

Package `src/ghostbench/` (version 0.1.0):

- `tokens.py` - estimator parity per plan: imports GhostSlice's
  estimator when GhostSlice is importable (reports stamp
  estimator_version `ghostslice-estimator-v2`, source `ghostslice`,
  slice_version detected, 1.0.6 in the smoke env), otherwise a
  formula-compatible fallback implementing the same BPE-like split
  and family calibration factors (stamped `fallback-estimator-v2-compatible`).
  Smoke confirmed the fallback yields identical totals on the fixture.
- `prices.py` - local dated price table: GHOSTBENCH_PRICES env, else
  installed/sibling GhostSlice `prices.json` (date 2026-10-12 found
  in smoke), else a dated built-in snapshot. Unknown model = cost
  None, stated rather than guessed. All costs labelled estimates.
- `corpus.py` - corpus format + loader with full validation
  (duplicate project/task ids, bad budgets, missing paths all raise
  CorpusError naming the problem). Corpus JSON: name, version
  (`corpus_version` accepted as alias), projects[] with id, path,
  optional commit, optional tree_hash (computed as a deterministic
  sha256 over relpath+content hashes when absent; code is recorded
  by hash, never copied into Bench). Tasks: prompt, expected_files,
  expected_symbols, recorded_patch (path) or patch_text (inline),
  test_command (str or list), budget_tokens, verify_report, variants
  (bundle_dir / manifest / explicit tokens per variant).
- `scoring.py` - deliberately boring scoring per plan: static patch
  parsing (files touched, lines +/-, sha256), files-touched score
  with `informational_only: true` (extra files listed, never
  auto-failures), manifest token/hash extraction for bundle
  traceability, and tolerant normalisation of GhostVerify reports
  (verdict + hard/soft gaps from several key shapes).
- `runner.py` - Tier A static runner. Per task: full variant
  (project scan, or a provided full bundle manifest); sliced variant
  (provided bundle manifest when supplied, otherwise derived from
  expected_files and labelled source `derived:expected-files` in the
  row, never passed off as a GhostSlice bundle); verified/recalled/
  proxied variants only from provided manifests/totals, gated by
  --suite. Verify hard gaps, fit vs budget_tokens, and recorded-patch
  outcome decide pass/fail/unknown; a variant with tokens for only
  some tasks is totals-flagged `partial` with no cross-total saving
  percentage invented. Optional `--run-tests` runs a task's test
  command in a temp copy only (patch applied via `git apply` when
  present; apply failure is reported, not hidden).
  Appends a stamped record per run to `.ghostbench-history.jsonl`
  (ledger helpers append/read included).
- `report.py` - BENCH.md + bench-report.json writers. The writer
  refuses a report with no per-task rows (a summary percentage with
  no rows is not a valid Bench report). BENCH.md carries: corpus
  name/version, labelled SUBSET notice when a task filter was used,
  GhostSlice version, estimator version + source, price table date,
  honest-scope box (Tier A, what was not measured), totals, per-task
  table including sliced manifest sha256, and an all-failures list.
  Compare mode: per-task sliced deltas, status changes, totals, and
  an estimator-mismatch warning (differing estimator versions =
  not directly comparable). Compare accepts report files or run
  directories.
- `tierb.py` - Tier B code path, gated OFF by default. Preflight
  (agent claude-code only, per-task full-context estimates, both
  arms counted, price date, cap echoed). `run_live` gate order:
  budget required (positive) -> explicit confirm required ->
  GHOSTBENCH_ENABLE_LIVE=1 required -> an injected executor is
  required. In this build no built-in executor exists: every path
  raises TierBRefusal stating no model was called and nothing was
  spent. `check_budget` helper + `mark_flaky` (divergent re-runs are
  flagged flaky, not hidden) are present for the future executor.
- `demo.py` + CLI `demo-corpus` - generates the starter adversarial
  corpus in a user-chosen directory (widely-called helper in an
  easy-to-exclude file, near-duplicate modules, an unused legacy
  module, one good recorded patch, and one task whose patch touches
  no expected file with a Verify report predicting a hard gap, so a
  first run has a visible failure - the plan's honesty test).
- `cli.py` - `run`, `compare`, `add` (records a project by
  tree_hash into a corpus file, no code copied), `live` (Tier B
  preflight + gates), `demo-corpus`, `version`.

`pyproject.toml` - setuptools, zero dependencies, requires-python
>=3.10, console script `ghostbench = ghostbench.cli:main`,
readme points at README.md (Agent B's file; the in-repo install
check below used a stub README in a /tmp copy only).

## Smoke test (Tier A, fixture in /tmp, no spend, no network)

Commands run with PYTHONPATH=src:<ghostslice>/src unless noted:

1. `ghostbench demo-corpus /tmp/ghostbench-smoke/demo` then
   `ghostbench run .../corpus.json --out /tmp/ghostbench-smoke/run1`
   Result: run 20261014T130647Z-0eac40e6cc72, tasks=2, pass=1,
   fail=1, unknown=0, full=498 estimated tokens, sliced=82,
   saving 83.5%, fit success 100%, hard gaps predicted 1.
   (`fix-helper` passes; `fix-helper-missing-context` fails with
   both stated reasons: Verify predicted 1 hard gap, and its
   recorded patch touches no expected file.) BENCH.md and
   bench-report.json written, ledger record appended to the corpus
   dir `.ghostbench-history.jsonl`.
2. Re-run + `compare run1 run2`: per-task sliced delta 0 for both
   tasks, no estimator warning. Installed-package run (pip install
   of a /tmp copy into a venv, stub README in the copy only)
   reproduced identical totals (498 -> 82, same content fingerprint).
3. Manifest variant: a task variant with `bundle_dir` pointing at a
   manifest with 30 sliced tokens produced tokens=30, source
   `bundle-manifest`, manifest sha256 recorded. Partial-totals
   handling fixed during smoke (a missing variant total no longer
   inflates the corpus saving percentage; it is flagged PARTIAL).
4. `--task fix-helper` subset run: 1 task, and BENCH.md carries the
   labelled line "SUBSET RUN (labelled): tasks fix-helper".
5. `--run-tests` on a fixture whose task has a test_command: the
   command ran in a temp copy with the recorded patch applied,
   exit 0, task status pass.
6. Tier B gate battery (all refused, exit 2, no spend): no budget ->
   refusal (budget required); budget without --confirm -> refusal
   (explicit confirmation required); budget + --confirm -> refusal
   (live execution gated OFF, GHOSTBENCH_ENABLE_LIVE unset);
   GHOSTBENCH_ENABLE_LIVE=1 + budget + --confirm -> refusal (no live
   executor wired in this build).
7. Error paths: invalid corpus JSON shape and a missing corpus
   file both exit 2 with a named error. Fallback estimator (run
   without GhostSlice on the path) produced totals identical to the
   GhostSlice-estimator run (498 / 82), stamped as fallback.

## Cross-check against Agent B's suite (read-only here)

`python3 -m pytest tests -q` in ~/workspace/ghostbench against this
core, final state during this build: 28 passed, 1 skipped, 0 failed.
The skip is B's documented one (mid-corpus cap stop needs a stub
executor injected into run_live; the CLI exposes no executor
injection and no live runs are allowed in this build - see
REPORT_B.md on their side). Mid-build there was a transient extra
failure in B's examples (GhostBus corpus path depth in their
examples/corpora/ghostbus/corpus.json, resolving outside the real
~/workspace/ghostbus tree); B corrected it during the build
(verified: path is now ../../../../ghostbus and the test passes).
No tests/**, examples/**, or README.md files were edited by Agent A.

## Honest limits

- Tier B does not execute in this build by design (gate above). The
  plan's live-demo verification item remains open for a later,
  separately approved cycle with a wired executor.
- The shipped GhostBus starter corpus is Agent B's examples
  surface; the core's starter/demo corpus is generated by
  `ghostbench demo-corpus` and was the smoke fixture.
- Derived sliced totals (expected-files) are an interim stand-in for
  real GhostSlice bundle manifests; rows are labelled with their
  source so a derived number can never be mistaken for a bundle
  measurement. Supplying real bundles upgrades the same rows to
  manifest-traced numbers with no format change.
- Test-command execution is opt-in and trusts the corpus author's
  command, run in a temp copy with a 120s timeout; it is not a
  sandbox.
