# GhostBench - Agent B Report (tests / docs / examples)

Builder: Agent B, tests/docs side only. Date: Oct 14, 2026.
Ownership respected: `tests/**`, `README.md`, `examples/**`, and this
file only. Nothing under `src/**` was edited, no `pyproject.toml`
was touched. Gates respected: no live (Tier B) run, no spend, no
network, no push, no publish.

## What was delivered

- `tests/` - 29 tests in 5 files (28 passed, 1 skipped, see below):
  - `test_corpus_format.py` (8) - every shipped corpus matches the
    core loader's shape; task fields present; bundled fixture files
    exist; the GhostBus corpus resolves to the real tree; the SAMPLE
    report pairs follow the core report format, are labelled SAMPLE,
    are traceable row-to-BENCH.md, and their totals match their rows.
  - `test_fixtures_adversarial.py` (6) - the planted traps are really
    planted: exact duplicate is byte-identical, near-duplicate line
    Jaccard >= 0.85 (GhostSlice threshold), `helpers.py` is really
    imported/called by `router.py`, the broken patch really references
    the non-existent `dispatch_v2`, the good patch's removed lines
    really exist in `helpers.py`, DECISIONS.md carries SUPERSEDED and
    CURRENT decisions.
  - `test_tier_a_runner.py` (6) - black-box CLI runs on the mini
    corpus: traceable report (stamps, tree hash `sha256:`, sliced
    source labelled `derived:expected-files`), token determinism on
    re-run, adversarial run surfaces adv-002 as fail with >= 1 hard
    gap while adv-001 passes, BENCH.md has per-task rows plus the
    Honest scope and Failures sections, a bogus corpus exits 2, and
    the ledger lands next to the corpus file with version stamps.
  - `test_budget_gate.py` (6, one skipped) - the Tier B refusals,
    below.
  - `test_compare.py` (3) - the sample pair really differs by -100
    sliced tokens on adv-001, `ghostbench compare` on the two report
    FILES reports that delta in both Markdown and JSON out, and the
    sample format keeps files-touched `informational_only: true` with
    no failures recorded on passing rows.
- Starter corpora:
  - `examples/corpora/ghostbus/corpus.json` - GhostBus described, not
    copied: project path `../../../../ghostbus` to the real checkout
    (observed v0.5.10, test command `node test.mjs`), 3 tasks against
    the real `src/*.mjs` modules. The GhostSlice reference totals for
    the tree (129,555 full / 45,770 sliced, calibrated estimates) are
    recorded in the corpus description as reference, not as results.
  - `examples/corpora/adversarial/` - the bundled adversarial project
    (Python shop) with both patches and `verify/adv-002-gap.json`, a
    GhostVerify-shaped report predicting the hard gap for adv-002.
  - `examples/corpus-template/corpus.json` - copy-and-fill starter.
  - `tests/fixtures/mini/` - the tiny deterministic corpus the runner
    tests use.
- `examples/runs/sample-tier-a-run-{a,b}/` - report pairs in the
  core's exact format, carrying `"sample": true` and a sample note in
  both files. Illustrative numbers only, never results.
- `README.md` - install, the two tiers and the four-step Tier B gate,
  quickstart, the corpus and report formats as the core actually
  writes them, the command table, scoring, and the verification bar.

## Test result (final run, this machine)

```
python3 -m pytest tests -q     ->  28 passed, 1 skipped in 7.31s
```

Skipped (1), by design: `test_live_stops_at_cap_mid_corpus_and_reports_partial`.
The core's mid-corpus cap helper (`tierb.check_budget`) is only
reachable end-to-end through an injected executor, which the CLI does
not expose, and reaching it any other way would need a live run.
Skipped with the reason recorded in the test, not silently dropped.

## Budget-refusal record (required gate)

All Tier B tests exercise refusals only. Results, all PASS:

| Test | Core behaviour observed |
|---|---|
| `live` with no `--budget` | Exit 2, "Tier B refused: a positive --budget token cap is required" after the preflight prints |
| `live --budget 20000` with no `--confirm` | Exit 2, "explicit confirmation is required after reviewing the preflight" |
| Preflight-before-refusal | Stdout shows the preflight: tasks, estimated costs, and `budget cap: 20000`, before the refusal |
| `live --budget 20000 --confirm` with `GHOSTBENCH_ENABLE_LIVE` removed from env | Exit 2, gated OFF refusal stating no model was called and nothing was spent |
| `live --agent some-other-agent` | Exit 2, Tier B v0.1 supports one agent only (claude-code) |

No test passes `--confirm` together with the live env gate enabled,
and the core wires no executor in v0.1, so no live run was possible
from this suite by construction. No spend occurred.

## Manual spot runs (Tier A only, outputs in /tmp, not shipped)

- Adversarial corpus: exit 0, 4 tasks, pass 1 / fail 1 / unknown 2,
  full 9,088 estimated tokens vs sliced 510 (94.4%). adv-001 pass,
  adv-002 fail (Verify predicted 1 hard gap), adv-003 and adv-004
  unknown (no recorded patch / test result Tier A can score; shown as
  failures-visible notes in the report, which is the core's honest
  behaviour, not a pass).
- GhostBus corpus: exit 0, 3 tasks all unknown (descriptive starter
  tasks carry no recorded patches), per-task full 129,895 estimated
  tokens with the core's **fallback estimator** (`slice_version`
  stamped `None`, `estimator_source: fallback...`). Note for the
  parent: that 129,895 is the fallback estimator's figure for the
  whole tree, close to but not the GhostSlice G5 figure (129,555);
  when GhostSlice is importable the core stamps its version instead.
  This is exactly the estimator-stamping distinction the plan wants
  visible, and the report shows it.
- Both runs appended ledger records next to their corpus files; those
  runtime artifacts were deleted from `examples/` after the spot
  runs so the shipped corpora stay clean.

## Assumptions, stated

1. **Interface alignment happened mid-build.** When this build
   started, `src/ghostbench` did not exist, so the first draft of the
   tests/docs assumed a directory-style corpus and a different report
   shape. Agent A's core landed during the build; Agent B re-read
   the actual core (`cli.py`, `corpus.py`, `runner.py`, `report.py`,
   `tierb.py`, `scoring.py`, `demo.py`) and rewrote the B-side files
   to the real contract: corpus = one JSON file with a `projects`
   list, `run`/`live` take the corpus file path, `compare` takes two
   `bench-report.json` files, confirmation is the `--confirm` flag
   (no interactive prompt in the core), and report rows live under
   `tasks` with status pass/fail/unknown. The first aligned run was
   18 passed / 8 failed / 1 skipped (all 8 failures were B-side
   format mismatches, including one wrong relative-path depth,
   `../../../` for `../../../../`, in the GhostBus corpus). Final:
   28 passed / 1 skipped. No core file was edited by Agent B.
2. Confirmation contract: PLAN.md says "confirmed by the user"; the
   core implements that as the `--confirm` flag after a printed
   preflight. The tests and README document the flag mechanism.
3. The adversarial adv-002 failure is driven by the shipped
   GhostVerify-shaped report (`verify/adv-002-gap.json`), which is
   the signal PLAN.md says Bench compares. The patch's missing symbol
   is additionally pinned by a fixture test.
4. Sample runs in `examples/runs/` are format samples generated by
   Agent B, not core output; they replicate the core writer's shape
   field for field (verified by the format tests and by feeding both
   files to the core's real `compare`, which accepted them).

## Not covered / open for the parent

- Mid-corpus cap stop end-to-end (skipped test, above) needs either
  a CLI-exposed stub executor or a core unit test from Agent A.
- Tier B flaky-arm marking (`tierb.mark_flaky`) has no B-side test:
  it needs repeated live rows, which the no-live gate forbids here.
- The GhostBus starter tasks are unscored in Tier A by design
  (unknown). Giving one of them a recorded patch would let the first
  published GhostBus run show a pass/fail, at the parent's call.
- `--run-tests` mode of the Tier A runner is untested on the B side:
  the mini/adversarial test commands point at pytest but the fixture
  projects ship no pytest files of their own, so a `--run-tests` run
  would report on the corpus folders, not on the fixture packages.
  Flagged rather than papered over with a fake passing command.
