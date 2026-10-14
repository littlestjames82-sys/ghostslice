# G19 Audit — CI pack: `ghostslice ci` + Action sample (v0.24.0)

Goal: one command a CI pipeline runs to gate a repo's agent-context
health (`ghostslice ci`: budget, lint, secrets, fit, duplicates),
a copy-paste GitHub Action sample that installs GhostSlice from
GitHub (it is not on PyPI), a PR-comment Markdown mode, and a
dogfood workflow running the command on this repo. Baseline:
v0.23.0, 728 tests passed.

## Build summary

- `src/ghostslice/ci.py` (new): `run_ci()` composes the existing
  machinery over ONE shared scan snapshot (the checks judge the
  same tree): budget totals use the exporter's per-mode accounting
  on the resolved modes (the `check-budget` basis; verified equal
  to `check-budget`'s printed totals on this repo, 442,560 ->
  136,395), lint reuses `lint_project` + `lint_exit_code` with the
  scan/dups/secrets precomputed (the G6 "duplicates computed
  twice" cost is not repeated here), secrets reuses
  `scan_scan_result`, fit reuses `fit_modes` in memory (nothing is
  written; the fit check's `before_tokens` was probe-verified
  equal to the totals' sliced count), duplicates reuses
  `find_duplicates` with a floor of 500 recoverable estimated
  tokens per group (DUP_FLOOR_TOKENS; this repo's one group, the
  prices.json pair at 379, sits deliberately under it).
- The five checks, in order: budget, lint, secrets, fit,
  duplicates. Each returns pass / warn / fail / skipped plus a
  one-line evidence string and a details dict. Budget and fit SKIP
  (never fail) when no budget is configured anywhere, with the
  evidence naming the remedy (profile budget_tokens, --budget, or
  `ghostslice init`).
- Secrets decision: findings FAIL the secrets check by default.
  A CI gate for agent context exists to keep secrets out of that
  context; a warn-by-default gate trains people to ignore it.
  `--allow-secrets` downgrades to warn, and `--fail-on-secrets`
  is accepted as an explicit spelling of the default. The flag
  speaks for the whole run: under `--allow-secrets` the lint
  check runs with its L005 rule (the same findings under a rule
  number) turned off via a merged copy of the profile's lint
  config, so the downgrade cannot be undone through the side
  door; the lint details record `l005_disabled_by_allow_secrets`
  and the evidence says so when findings exist. The profile
  object itself is never mutated.
- Isolation: every check runs under a wrapper that converts an
  exception into that check FAILed with `check errored: ...` as
  evidence; the two shared derivations checks depend on (selection
  totals, duplicates) are precomputed under the same stored-error
  discipline and re-raised inside their dependent check. The
  shared scan itself may still raise filesystem-shaped errors,
  which the CLI layer maps to exit 2 (usage), never a traceback.
- Exit semantics: 0 = no failed check (warnings and skips do not
  fail), 1 = any check failed, 2 = usage/config errors (bad
  --budget, missing project, invalid profile, an --out report
  that cannot be written). `--json` emits one payload whose
  `exit_code` field is the process exit code; a test battery pins
  payload/exit/status agreement across scenarios. `--pr-comment`
  prints the compact Markdown table (mutually exclusive with
  --json, argparse-enforced exit 2). `--out FILE` writes the HTML
  report (report.py) after the checks; the payload gains a
  `report` block, and an unwritable target exits 2 while the
  checks' own verdict stays visible in the payload.
- Read-only: run_ci never opens the content cache, writes no
  bundle, and appends no ledger record (pinned by an fs-snapshot
  test that includes a pre-existing ledger file).
- Samples: `examples/github-action/ghostslice-ci.yml` (+ README)
  checks out the USER's repo, installs from
  `git+https://github.com/littlestjames82-sys/ghostslice` with an
  explicit "not on PyPI" note, runs ci with the budget from a
  workflow env var, uploads the JSON + comment Markdown + HTML as
  artifacts, and shows an optional PR-comment step using
  actions/github-script with only the built-in GITHUB_TOKEN.
  `.github/workflows/ghostslice-ci.yml` dogfoods the command on
  this repo from the checked-out source (PYTHONPATH=src, like
  ci.yml) with `--budget 180000` on the command line: the v0.24
  local sliced total is 136,395, so the margin is ~30%. No
  `.ghostslice.json` was added to this repo (it would change
  every command's behaviour repo-wide); `ghostslice ci .` here
  exits 0 with budget/fit skipped, lint warn (5 warnings, 0
  errors), secrets pass, duplicates pass.
- Tests: tests/test_v24_ci.py, 29 new (728 -> 757). Fixtures are
  engineered per check from probe-verified behaviour (see the two
  build-phase catches below).

### Build-phase self-catches (found by probing fixtures, before Audit #1)

- The canonical AWS example key (AKIA + IOSFODNN7EXAMPLE) is NOT
  flagged by the guard: it is the documented example value and the
  scanner treats it as placeholder-shaped. The secrets fixture
  therefore uses a random-shaped AKIA key assembled from parts
  (which the guard does flag), and this test file contains no
  contiguous literal either way.
- Lint's L001 only fires on files held at FULL mode; the
  lint-error fixture pairs a profile full-mode glob with a
  profile-raised L001 severity + lowered threshold, so the lint
  check fails without touching the secrets check.
- A fit failure logically implies a budget failure (fit starts
  from the default selection; an already-fitting selection is
  trivially fitted). The unfittable fixture pins the pair rather
  than pretending the fit check can flip alone.

## Audit #1 — adversarial review of the build

### F1 [MED] The sample workflow breaks exactly when the gate fails
GitHub `run:` steps execute with `bash -e`: in the sample's
"Run GhostSlice CI" step, when the first `ghostslice ci` exits 1
(the gate doing its job), the second invocation never runs, so
`ghostslice-ci-comment.md` is never created. The upload step then
warns about the missing file and the PR-comment step throws on
`readFileSync`. `continue-on-error: true` keeps the job alive but
cannot fix the missing artifact; and the obvious patch
(`|| true` on both lines) would flip `steps.ghostslice.outcome`
to success and disarm the enforce step. Fix (Improve #1):
capture the exit code (`|| code=$?`), publish it as a step
output (`exit_code` via GITHUB_OUTPUT), drop continue-on-error,
and enforce from the captured output. Both report files are then
always produced before any step can fail.

### F2 [LOW] An --out report written into the project is scanned by later runs
Probe: `--out report.html` at a fixture's root is written after
its own run's checks (within-run totals are unaffected), but the
NEXT run scans it as a file: fixture totals grew 23 -> 1,016
original estimated tokens (the report alone is ~993 at full
mode). A gate that quietly feeds on its own output drifts.
Fresh CI checkouts never accumulate artifacts, so the sample and
dogfood are safe as run in Actions; the exposure is repeated
local runs with --out inside the tree. Fix (Improve #1):
document it (README CI section + a comment in the sample), and
add the dogfood artifact names to this repo's .gitignore (the
scanner honours .gitignore, so local dogfood runs stay clean).

### Checked, no defect
- Exit-code honesty battery: payload exit_code == CLI return ==
  (any check failed) across clean / over-budget / fittable /
  secret / allowed-secret / strict scenarios; JSON summary counts
  recomputed independently in the test and compared.
- Fit/totals agreement: the fit check's before_tokens equals the
  budget totals' sliced_tokens on probe fixtures (both derive
  from resolve_modes over the same scan).
- Crash isolation beyond the unit test: with the totals
  derivation monkeypatched to raise, the budget check fails with
  the stored error, totals serialize as null, the other four
  checks complete, exit 1, no traceback.
- `ghostslice ci <file>`: exits 0 judging the single file. That
  matches the scanner's long-standing file-root semantics (the
  same behaviour `scan` and `slice` have for a file path), so it
  is consistent, not a defect.
- Failing checks + a writable --out: exit stays 1 (the report
  failure path to 2 does not swallow check verdicts, and a check
  failure does not block the report).
- The dogfood command from the workflow file, run locally
  verbatim (PYTHONPATH=src, --budget 180000, --json): exit 0,
  all five checks pass or warn (lint warn only). The CI checkout
  differs from this tree by the untracked ledger file and the
  just-added workflow/sample files; the budget margin (~30%)
  absorbs the difference in both directions.
- PR-comment output: statuses and totals render from the same
  payload as --json (one renderer input, two renderers), pipes
  in evidence are escaped, and the Markdown contains no em
  dashes.

## Improve #1 — fixes applied for F1–F2

- F1: the sample's run step now captures the verdict
  (`|| code=$?` per invocation, so a failing first run cannot
  starve the second), publishes it as the step's `exit_code`
  output via GITHUB_OUTPUT, drops `continue-on-error`, and the
  enforce step fires on `steps.ghostslice.outputs.exit_code
  != '0'`. Both report files are therefore always produced
  before any step can fail. A structural test pins the new
  needles and the ABSENCE of continue-on-error. Verified by
  executing the step's shell logic locally against a failing
  fixture: both files + the HTML written, code captured as 1.
- F2: the self-inclusion behaviour is documented in the README
  CI section and in a comment in the sample workflow, and this
  repo's .gitignore gained the two dogfood artifact names
  (ghostslice-ci.json, ghostslice-report.html) with a comment
  explaining that the scanner honours .gitignore. A regression
  test pins the mechanism: the same report file inflates totals
  when visible and disappears from them once gitignored.
- Docs landed with this round: README "CI pack" section and the
  CHANGELOG [0.24.0] entry; their claims (check set, floor,
  exit semantics, secrets default) were written from the code
  and re-read against it in Audit #2.
- Regression tests: +2 in tests/test_v24_ci.py (31 total):
  totals-crash isolation pin, gitignored-report pin. Full suite
  after Improve #1: the v24 file passes 31/31; full-suite count
  recorded at goal close.

## Audit #2 — re-review after Improve #1

### Probes run
- Workflow shell simulation (the F1 scenario, executed locally):
  failing fixture -> ghostslice-ci.json, ghostslice-ci-comment.md
  and ghostslice-report.html all produced, captured code 1, and
  the fixture's secret literal appears 0 times in both outputs
  (redacted forms only). Passing fixture -> code 0.
- Dogfood verbatim: the workflow file's exact command
  (PYTHONPATH=src, --budget 180000, --json, --out) run in this
  repo: exit 0, payload exit_code 0, report block written:true,
  checks budget pass / lint warn / secrets pass / fit pass /
  duplicates pass. Artifacts removed afterwards; both names are
  gitignored, so even a leftover could not pollute later runs.
- YAML structure: both workflow files have no tabs, no
  odd-indent lines, and the expected top-level keys (sample:
  name/on/env/jobs; dogfood: name/on/jobs). Action pins are the
  versions this repo's ci.yml already uses (checkout v4,
  setup-python v5, upload-artifact v4) plus github-script v7 for
  the optional comment step.
- Plugin discipline inherited: a profile naming a missing
  plugin file makes `ci` exit 2 with the loader's message before
  any check runs (the central CLI plugin block covers ci like
  every other slicing command).
- Budget boundary: budget == sliced total passes both budget
  and fit; budget == sliced - 1 fails budget while fit still
  reaches it. Pinned as a test in Improve #2.
- Docs vs behaviour re-read: README/CHANGELOG/sample claims
  (five checks, 500-token floor, exit semantics, secrets default
  + the --allow-secrets run-wide scope, skip semantics, the
  --out note) each traced to the code path that implements them.

### Findings
None. No new defects surfaced; the two Audit #1 findings stay
fixed under re-probe.

## Improve #2 — closing pins

- Boundary test (budget == sliced / sliced - 1) added to
  tests/test_v24_ci.py (32 total in the file).
- This audit completed; ROADMAP_20.md G19 marked done with the
  progress entry.

## Standing limitations (accepted, documented)

- ci judges the DEFAULT selection (profile modes/ignores/entry
  points). It has no --mode/--preset/--symbols surface: it is a
  gate for the project's configured context, and task/export
  variants keep their own commands.
- The duplicates check's floor (500 recoverable estimated
  tokens) is a constant, not a profile option; lint's L004 rule
  remains the tunable surface for duplicate sensitivity.
- `--allow-secrets` turns lint's L005 off for the CI lint check
  only; a plain `ghostslice lint` on the same tree still errors
  on the findings, which is the intended difference between a
  gate run with an explicit waiver and the lint tool itself.
- The HTML report is produced by report.py on the live tree
  after the checks complete; on a tree that changes mid-run the
  report can reflect slightly newer bytes than the checks did.
  CI checkouts do not change mid-run.
- The sample workflow runs `ghostslice ci` twice (JSON+HTML,
  then --pr-comment) because the CLI prints one format per run;
  each run is read-only and seconds-cheap on typical repos.
