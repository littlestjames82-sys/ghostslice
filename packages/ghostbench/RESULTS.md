# GhostBench - Test Results

Reproducible record of a full-suite run. Regenerate on every
release-grade change; counts quoted anywhere else must match this
file or be removed.

## Run of Oct 18, 2026 (budget cap restored)

- Date (UTC): 2026-10-19T03:32Z
- Platform: Linux 7.0.0-39-generic x86_64
- Python: 3.12.3
- pytest: 9.1.1
- Tree: ghostbench v0.1.0, live-agent build + budget cap gate
- Command:

```sh
cd ghostbench
PYTHONPATH=src python3 -m pytest tests -q
```

- Result: **109 passed, 0 skipped** (8.04s) - the 102 of the
  live-agent build below plus 7 new tests in
  `tests/test_budget_gate.py`.

### What changed: the budget cap is back, as a second gate

Per Ryan's direction, the v0.1 budget cap returns on top of the
`GHOSTBENCH_AGENT_CMD` configuration gate, in `check_budget`'s
native semantics: the surviving utility compares a TOKEN count
against `budget_tokens` - it prices nothing in currency and the
price table plays no part. `ghostbench live --budget TOKENS` now:

- after the configuration check (unconfigured still refuses
  first, exactly as before) and before any agent runs, estimates
  the run's context size as the sum of the per-task full-context
  token estimates from Bench's estimator - the same numbers a
  run reports as `full_tokens` (a unit test pins the estimate
  against both `check_budget` and a real run's totals);
- refuses when the estimate exceeds the cap and `--confirm` is
  absent: exit 2, the estimate and the cap printed with the exact
  `--confirm` invocation, and nothing written (no report, no run
  folder, no ledger entry - asserted by test);
- with `--confirm`, proceeds; the report records `budget_cap`,
  `budget_estimate`, and `budget_confirmed` at report level, and
  BENCH.md shows the cap line (with a "cap exceeded - run
  proceeded under --confirm" note when applicable). With no
  `--budget`, behavior is exactly the live-agent build's, and the
  report records the cap as unset (null).

The estimate is Bench's own and is labelled as such everywhere it
appears (help, refusal, BENCH.md): the cap bounds the estimate in
tokens, NOT the configured agent's real cost, which is whatever
the agent itself charges inside the user's own program. Bench
does not meter the agent and the cap does not bound its billing.

### CLI proof (stand-in agent, one-task probe corpus)

- No `--confirm`, `--budget 10` against a 36-token estimate:
  exit 2, "budget cap exceeded: this live run is estimated at 36
  context tokens, over the --budget cap of 10 tokens", the exact
  re-run line `ghostbench live <corpus> --budget 10 --confirm`
  printed, and the output directory listing confirms nothing was
  written.
- Same command with `--confirm`: exit 0, task passes; the CLI
  prints "budget: cap 10 tokens, estimated run context 36 tokens
  (cap exceeded, confirmed)"; the report carries
  `budget_cap: 10, budget_estimate: 36, budget_confirmed: true`,
  and BENCH.md's budget line ends "Cap exceeded - run proceeded
  under --confirm".

## Run of Oct 18, 2026 (live-agent build)

- Date (UTC): 2026-10-19T02:52Z
- Platform: Linux 7.0.0-39-generic x86_64
- Python: 3.12.3
- pytest: 9.1.1
- Tree: ghostbench v0.1.0, live-agent build (Tier B report writer:
  `ghostbench live` runs a configured agent per task and emits
  `verification_level: "live-agent"` reports)
- Command:

```sh
cd ghostbench
PYTHONPATH=src python3 -m pytest tests -q -rs
```

- Result: **102 passed, 0 skipped** (5.89s)

This supersedes the evidence-contract run below as the current
count. The delta is the Tier B redesign, not silent churn: the 5
old budget-gate tests and the 1 skip pinned a gate model that no
longer exists (see the design note), and were replaced by 3 new
gate tests in `tests/test_budget_gate.py`, 2 rewritten gate tests
in `tests/test_hardening.py`, and 11 new tests in
`tests/test_live_agent.py`.

### What the live-agent build is

The evidence contract's top level, `live-agent`, was defined in
v0.1 but nothing could emit it: Tier B was a gate-only stub (one
hardcoded `--agent claude-code` behind a `--budget` cap, a
`--confirm` flag, and `GHOSTBENCH_ENABLE_LIVE=1`, with no executor
wired). That model is replaced:

- The agent command comes ONLY from the environment variable
  `GHOSTBENCH_AGENT_CMD` (a shell-style command line, split with
  shlex and executed directly - no shell). Bench hardcodes no
  vendor, has no default agent, and makes no network calls itself.
- **Refusal behavior:** with `GHOSTBENCH_AGENT_CMD` unset, empty,
  or unparseable, `ghostbench live` exits 2 with a plain message
  naming the variable and how to set it, BEFORE anything runs; no
  report, run folder, or ledger record is written. The CLI test
  asserts all three absences.
- Per task, the agent runs in a contained copy of the project (the
  Tier A machinery: `_copy_project_safely`, `_scrubbed_env`,
  POSIX rlimits; escaping symlinks skipped and recorded). It
  receives the copy path in `GHOSTBENCH_TASK_DIR` and as the final
  argument, the task id in `GHOSTBENCH_TASK_ID`, and the prompt in
  `GHOSTBENCH_TASK_PROMPT`. The timeout is `--agent-timeout`
  (default 300s). Bench then measures the file-level diff against
  a pristine copy and runs the task's test command in the agent's
  copy, contained exactly like Tier A.
- Verdict: a task passes only when the agent produced changes AND
  the contained tests pass. A crash, a timeout, or no changes is a
  failed row with the reason shown; a nonzero exit is rescued only
  by changes that pass the tests (the exit code is recorded either
  way). A task with no test command scores `unknown`.
- Hygiene: only the command's first token is recorded as
  `agent_name`. The full command line - which may carry keys in
  its arguments - appears nowhere in a report; a test asserts a
  planted `--key SECRETVALUE` is absent from the whole report JSON,
  and a planted parent-env secret is absent from the environment
  an agent process actually receives (the Tier A probe pattern,
  applied to the agent's env dump).
- Honest scope, extended for live runs: the agent runs with the
  user's permissions outside an OS sandbox. Bench directs its
  work at the task copy by making that copy its working directory,
  but host writes elsewhere are NOT prevented and network access
  is NOT blocked. Every live row and the report carry the
  `sandbox` block stating exactly this.

### Proof run (stand-in agent, stated plainly)

**No real vendor agent was run for this build.** No agent is
configured in this environment (`GHOSTBENCH_AGENT_CMD` unset), so
the mechanism was proven end-to-end through the real CLI with a
scripted stand-in agent; the level semantics are real, and no
vendor agent was exercised. Proof, on a temp corpus whose one
task's test fails before the fix and passes after:

- pristine project test: `AssertionError: add is broken`, exit 1;
- `ghostbench live` with no agent configured: exit 2, the refusal
  message above, and no output folder created;
- `GHOSTBENCH_AGENT_CMD='python3 <stand-in>' ghostbench live
  corpus.json`: exit 0, `pass=1 fail=0`, report `tier: "B"`,
  `verification_level: "live-agent"` on the report and the row,
  `agent_name: "python3"` (first token only),
  `agent_exit_code: 0`, `agent_timed_out: false`,
  `files_changed: 1` (`calc.py`), `test: "pass"`;
- the pristine project's test still fails afterwards - the agent
  worked in a copy, never in the real tree.

The same behaviours are pinned by `tests/test_live_agent.py`
(fixing agent passes; do-nothing agent fails on the no-change
rule even when the tests already pass; crash records exit code 3;
a 1s timeout against a 60s sleeper records `timed_out`; symlink
escape skipped and recorded).

### Known limits of this run

- No vendor agent has ever been run under the live path; the first
  real agent run is still to come, by whoever configures one.
- The mid-corpus budget-cap stop the old suite skipped is gone
  with the budget gate itself: the configured agent is the user's
  own program and its spend happens outside Bench, so Bench has
  no spend of its own to cap. `tierb.check_budget` remains as a
  utility for callers wrapping a run with their own accounting,
  and its unit test still passes.
- Live containment is application-level, like Tier A's: scrubbed
  env, contained copy, POSIX rlimits, timeouts. Host writes and
  network by the agent process are not OS-enforced; reports say so.

## Run of Oct 18, 2026 (evidence-contract build)

- Date (UTC): 2026-10-18T20:50Z
- Platform: Linux 7.0.0-39-generic x86_64
- Python: 3.12.3
- pytest: 9.1.1
- Tree: ghostbench v0.1.0, evidence-contract build (sandbox hardening
  + verification_level), working tree identical to the GitHub push
  that carries this file
- Command:

```sh
cd ghostbench
PYTHONPATH=src python3 -m pytest tests -q -rs
```

- Result: **93 passed, 1 skipped** (2.81s; count updated later on
  Oct 18, 2026 after the PYTHONUSERBASE fix below landed and this
  exact command was re-run)

The one skip, stated by the test itself
(`tests/test_budget_gate.py:75`): the mid-corpus budget-cap stop in
`tierb.check_budget` can only be exercised end-to-end with a stub
executor injected into `run_live`, which the CLI does not expose; the
CLI-level gate cannot reach it without a live run, and live runs are
gated off in this build. See REPORT_B.md.

## Evidence-contract probes (known-answer set, in the suite)

`tests/test_evidence_contract.py` (23 tests) encodes the sanity gate:
a passing test command scores pass; a failing one scores fail; a
planted parent-env secret (`GHOSTBENCH_PROBE_SECRET`) does not reach
the test process; a patch escaping the temp copy (`../`, absolute, or
through a patch-created symlink) is refused before `git apply`; a
project symlink to an outside file is skipped and recorded, never
followed. Parent re-verification on Oct 18, 2026 reproduced the
secret probe independently of the suite: output `SECRET_IS: ABSENT`.

## Fix recorded Oct 18, 2026 (dogfood finding)

The first ghostworkflow dogfood run executed this suite inside
Bench's contained runner and the test process died with
`No module named pytest`: the scrubbed environment redirects HOME
into the temp area, which also hides the user site-packages where
test tooling lives. The runner now passes `PYTHONUSERBASE` (the
parent's user base, a code location, not a secret) through the
scrub, pinned by the regression test
`test_user_site_packages_stay_importable`. After the fix, the same
contained run executes the full suite: 92 passed, 1 skipped, and 1
failure that is environmental by construction
(`test_ghostbus_corpus_points_at_the_real_tree_and_copies_nothing`
resolves a relative path from the project's real location, which a
temp copy is not). At the real location that test passes, as the
93-passed run above shows.

## Known limits of this run

- Tier B (live-agent) did not run: it is gated off by design, and no
  code path in v0.1.0 emits a `live-agent` report yet.
- Test execution containment is application-level (scrubbed env,
  contained patch/copy, POSIX rlimits, timeout). Host filesystem
  writes and network access by a test process are not OS-enforced;
  every report's `sandbox` block says so.

## Addendum, Oct 18, 2026 (CI)

CI added (GitHub Actions, Python 3.10/3.11/3.12 on push) with two
jobs, mirroring GhostVerify: a standalone job (the GhostBus corpus
test skips there, since the example corpus deliberately points at
the real GhostBus tree outside this repo) and an integration job
that checks out GhostBus at the workspace root so the corpus path
resolves and the test runs for real. Local counts: dev tree 102
passed; standalone simulation 101 passed + 1 skipped.
