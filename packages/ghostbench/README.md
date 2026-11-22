# GhostBench
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![CI](https://github.com/littlestjames82-sys/ghostbench/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostbench/actions/workflows/ci.yml)

**Prove what GhostSlice saves, on tasks, not just on tokens.**

GhostSlice's headline number is real but narrow: on the GhostBus tree the
calibrated estimator measures 129,555 tokens full vs 45,770 sliced. That
proves a bundle is smaller. GhostBench proves the rest: that an agent
still completes the task with the slice, that the saving holds on *your*
repo and *your* tasks, and that a new GhostSlice version did not quietly
get worse. Same tasks, same projects, full vs sliced vs verified vs
recalled vs proxied, scored the same way every time.

By Ghost Developer Studio. MIT licensed. **Zero dependencies** (Python
standard library only), **local-first**: no network calls in Tier A, no
telemetry, ever.

Position in the Ghost stack: GhostSlice slices, GhostVerify checks a
slice, GhostRecall adds memory, GhostProxy applies slicing live.
GhostBench *measures* all four. Bench owns no slicing logic of its own:
if Bench and Slice disagree on a token count, that is a bug to surface,
not a number to average.

> Build status: v0.1. The corpus format, report format, and CLI
> contract in this README describe the shipped core
> (`src/ghostbench/`). Test results are recorded in `RESULTS.md`;
> the earlier build phases and the gaps they recorded are in
> `REPORT_B.md` (Agent B) and `IMPLEMENTATION_A.md` (core).

## Contents

- [Install](#install)
- [The two tiers](#the-two-tiers) - Tier A (static, free) vs Tier B (live, gated)
- [Quickstart](#quickstart) - first run in about a minute
- [Corpus format](#corpus-format) - the one JSON file that describes a bench
- [Report format](#report-format) - `BENCH.md` + `bench-report.json`
- [Commands](#commands) - every subcommand and its flags
- [Your own corpus in three steps](#your-own-corpus-in-three-steps)
- [Scoring](#scoring-deliberately-boring)
- [Exit codes](#exit-codes)
- [Troubleshooting](#troubleshooting)
- [Verification bar](#verification-bar-from-planmd), [Out of scope](#out-of-scope-for-v01), [Layout](#layout)

New here? Read Install, The two tiers, and Quickstart, run the
adversarial example, then read the `BENCH.md` it writes. Everything
else is reference.

## Install

From a checkout, no install needed:

```bash
cd ghostbench
PYTHONPATH=src python3 -m ghostbench --help
```

Or install it (still zero dependencies):

```bash
pip install .
ghostbench --help
ghostbench version   # smoke check: prints "ghostbench 0.1.0"
```

Requires Python 3.10 or newer. There is nothing to configure for
Tier A: no API key, no account, no network. (Tier B runs only when
you configure an agent command in `GHOSTBENCH_AGENT_CMD`; see The
two tiers.)

## The two tiers

| Tier | What it does | Model? | Spend? | Default |
|---|---|---|---|---|
| A | Static bench: bundle sizes, GhostVerify verdicts, recorded-patch checks, fit behaviour | No | No | Yes |
| B | Live bench: runs the agent command you configure on each task in a contained copy, measures what it changed, then scores the task's test command in the same copy | The agent's | The agent's (Bench spends nothing itself) | **Off** - refuses until configured |

The tiers are kept separate in every report. A Tier A number is never
presented as a live outcome.

**Tier B hard rule: Bench never runs an agent it was not configured
to run.** The agent is a command line you supply in the environment
variable `GHOSTBENCH_AGENT_CMD` - Bench hardcodes no vendor, has no
default agent, and makes no network calls itself. If
`GHOSTBENCH_AGENT_CMD` is unset or empty, `ghostbench live` refuses
before anything runs and writes nothing. Per task, the command is
split shell-style and executed directly (no shell) inside a contained
copy of the project, with the Tier A containment discipline (safe
copy, scrubbed environment, POSIX rlimits, timeout); it receives
the copy path in `GHOSTBENCH_TASK_DIR` and as its final argument,
the task id in `GHOSTBENCH_TASK_ID`, and the prompt in
`GHOSTBENCH_TASK_PROMPT`. Only the command's **first token** is
recorded in reports - a command line may carry keys in its
arguments, so the full line is never written down. The containment
is honest, not total: the agent runs with your permissions outside
an OS sandbox, so host writes outside the task copy are directed
there by the working directory but **not prevented**, and network
access is **not blocked**; every live report's `sandbox` block
states this. Tier B is never run on a schedule or in CI by default;
CI gets Tier A.

**Budget cap (second gate, opt-in): `live --budget TOKENS`.** After
the configuration gate and before any agent runs, Bench estimates
the run's context size - the sum of the per-task full-context token
estimates from its own estimator, the same numbers the report shows
as `full_tokens` - and checks it against the cap with
`tierb.check_budget` (estimated tokens <= cap). Over the cap, the
run refuses (exit 2, nothing written) unless `--confirm` is given;
a confirmed run proceeds and its report records `budget_cap`,
`budget_estimate`, and `budget_confirmed`. The cap is in tokens and
bounds Bench's estimate only: the configured agent's real cost is
whatever the agent itself charges, inside your own program - Bench
does not meter the agent, and the cap does not bound its billing.

## Quickstart

All of the commands below are Tier A or read-only unless marked
Tier B. Tier A calls no model and spends nothing. Examples assume
you are in the repository root and `ghostbench` is on your `PATH`
(or replace `ghostbench` with
`PYTHONPATH=src python3 -m ghostbench`, see Install).

**1. Run the bundled adversarial corpus (about a minute):**

```bash
ghostbench run examples/corpora/adversarial/corpus.json --out /tmp/bench-adv
cat /tmp/bench-adv/BENCH.md
```

What you should see: a one-line summary on stdout (task counts and
the sliced saving), plus two files in `/tmp/bench-adv/`:
`BENCH.md` (human report) and `bench-report.json` (machine report).
The run also appends one record to
`examples/corpora/adversarial/.ghostbench-history.jsonl`; pass
`--no-ledger` if you do not want that side effect.

**Expect failures in this report, on purpose.** The adversarial
corpus plants traps (see Corpus format below): a correct first run
is **not** all-green, and one task must surface as a visible failure
or hard gap. Zero failures anywhere means the corpus or the harness
is wrong, not that everything is perfect.

**2. Try the small test-suite corpus:**

```bash
ghostbench run tests/fixtures/mini/corpus.json --out /tmp/bench-mini
```

**3. Compare two reports:**

Compare is most meaningful for two runs of the *same* corpus (for
example before and after a GhostSlice change). It also accepts a
run folder instead of the JSON file itself:

```bash
# The two labelled SAMPLE reports bundled only to show the format
ghostbench compare examples/runs/sample-tier-a-run-a examples/runs/sample-tier-a-run-b

# Two real runs of the same corpus (B - A deltas)
ghostbench compare /tmp/bench-adv/bench-report.json /tmp/bench-adv-2/bench-report.json
```

**4. Other entry points:**

```bash
# Record your own project in a corpus file (by tree hash, copies no code in)
ghostbench add my-corpus.json --project ~/my-project --id my-project

# Write the core's starter demo corpus somewhere you choose, then run it
ghostbench demo-corpus /tmp/ghostbench-demo
ghostbench run /tmp/ghostbench-demo/corpus.json --out /tmp/bench-demo

# Tier B, opt-in only: runs the agent command YOU configure, per task,
# in a contained copy. Without one configured it refuses, writes nothing.
GHOSTBENCH_AGENT_CMD='my-agent --non-interactive' \
  ghostbench live examples/corpora/adversarial/corpus.json --out /tmp/bench-live
```

Run `ghostbench --help` or `ghostbench <command> --help` at any
point: every flag is documented there.

## Corpus format

A corpus is **one JSON file**. Projects and their tasks live inside it;
paths resolve relative to the corpus file.

```json
{
  "name": "adversarial",
  "version": "0.1.0",
  "projects": [
    {
      "id": "adversarial",
      "path": "project",
      "tasks": [
        {
          "id": "adv-001-fix-missing-route",
          "prompt": "Change the fallback handler name for an unknown route.",
          "expected_files": ["shop/helpers.py"],
          "expected_symbols": ["dispatch"],
          "recorded_patch": "patches/good-patch.diff",
          "test_command": "python3 -m pytest project -q"
        }
      ]
    }
  ]
}
```

Field notes:

- `path` (per project) is the project root, relative to the corpus
  file or absolute. Bench records repo state by `commit` (optional,
  recorded, never fetched) or a computed `tree_hash`
  (`sha256:` over sorted file hashes). Adding a project with
  `ghostbench add` records its tree hash and **never copies its code
  into the corpus**.
- Every task carries `id` and `prompt`, plus optional
  `expected_files` / `expected_symbols` (scoring hints, see Scoring),
  `recorded_patch` (a diff file, resolved relative to the corpus file
  or the project; or inline `patch_text`), `test_command` (string or
  list), `budget_tokens` (per-task fit budget), `verify_report` (a
  GhostVerify report file whose hard gaps Bench compares against what
  actually failed), and `variants` (provided bundles by `bundle_dir`,
  `manifest`, or explicit `tokens` for the sliced / verified /
  recalled / proxied arms).
- Project and task ids must be unique inside the corpus; the loader
  rejects duplicates, missing paths, and non-positive budgets.

Starter corpora, in `examples/corpora/`:

- **ghostbus** - the GhostBus demo tree as a corpus whose project path
  points at the real checkout (relative path, tree hash stamped by the
  loader). Tasks target the real modules (`src/tools.mjs`,
  `src/core.mjs`, `src/handler.mjs`, `src/cli.mjs`), test command
  `node test.mjs`. No GhostBus code is copied into this repo.
- **adversarial** - a small bundled Python project with planted traps:
  a byte-identical duplicate pair, a near-duplicate pair, a small
  generic-looking file (`shop/helpers.py`) that every routing call
  goes through, a recorded patch referencing a missing symbol paired
  with a Verify report predicting a hard gap (it must surface as a
  visible failure), and a superseded decision for Recall runs. A
  correct first run of this corpus is **not** all-green.

## Report format

Every Tier A run writes a run folder containing `BENCH.md` (human,
shareable) and `bench-report.json` (machine), and appends a stamped
record to `.ghostbench-history.jsonl` next to the corpus file. A
summary percentage with no per-task rows is not a valid Bench report:
the report writer refuses a report with no rows.

`bench-report.json` keys (written by the core, see
`src/ghostbench/runner.py` for the authoritative writer):

- Header: `tool`, `tool_version`, `tier`, `suite`, `run_id`,
  `created_utc`, `corpus` (`name`, `version`, `file`), `subset`
  (labelled when `--task` filtered the run).
- Version stamps on every report: `slice_version`,
  `estimator_version`, `estimator_source`, `price_table_date`, and a
  `cost_note` stating costs are estimates, never billed amounts.
- `totals`: `full_tokens`, `tasks`, `pass`, `fail`, `unknown`,
  `hard_gaps_predicted`, `expected_symbols`, `symbols_found`,
  `symbol_coverage_pct`, `tasks_with_missing_symbols`, and
  per-variant `tokens`, `saving_pct_vs_full`, `fit_success_rate`.
- `tasks`: one row per task with `project`, `task`, `status`
  (pass / fail / unknown), `full_tokens`, per-variant tokens +
  `manifest_sha256` + `source`, `verify` (normalised verdict and
  gaps), `patch` (files touched, sha256), `files_touched_score`,
  `symbols_score` (expected symbols found / missing in the expected
  files, plus the informational patch added-lines check), `test`,
  `failures`, and `flaky`.
- `honest_scope`: what Tier A measured and what it did not (live
  agent completion, answer quality).
- `failures_visible`: every failure, by project and task.

Traceability rule: every number in `BENCH.md` comes from the
estimator stamped in the header or from a bundle manifest whose
sha256 is in the same run's `bench-report.json`. Token counts are
**estimates from the GhostSlice estimator method** (or the core's
formula-compatible fallback, named in `estimator_source`), and costs
come from a local dated price table. Estimates are labelled as
estimates in every report, never presented as billed amounts.

Tier B reports carry the same shape, with `tier: "B"`, an `agent`
header block (the recorded first token, the timeout, and the
command source), and per-row live fields: `agent_name`,
`agent_exit_code`, `agent_timed_out`, `agent_output_tail`,
`files_changed` with `files_changed_paths` / `files_added` /
`files_deleted` / `files_modified`, a `sandbox` block stating the
live containment honestly, and the contained `test` outcome against
the agent's edits. `verification_level` is `live-agent` on the
report and every row. Tier B reports also record the budget gate at
report level: `budget_cap` and `budget_estimate` (both null when no
`--budget` was given) and `budget_confirmed`. Bench records no agent
token usage in Tier B: the configured agent reports none to Bench,
and none is estimated or blended in.

The sliced arm, when a task supplies no bundle, is derived from the
task's `expected_files` and labelled in the row as
`source: derived:expected-files`. Bench does not pretend that is a
GhostSlice-produced bundle.

Two labelled SAMPLE report pairs live in `examples/runs/` purely to
show the format and to exercise compare mode. They carry
`"sample": true` and a sample note, their numbers are illustrative,
and they must never be quoted as bench results.

## Commands

| Command | What it does |
|---|---|
| `ghostbench run <corpus.json> [--suite slice\|verify\|recall\|proxy] [--out <dir>] [--task <id> ...] [--run-tests] [--model <id>] [--ledger <path>] [--no-ledger] [--strict]` | Tier A run. `--run-tests` is opt-in and runs task test commands in a temp copy only. `--strict` exits 1 when any task fails |
| `ghostbench live <corpus.json> [--out <dir>] [--task <id> ...] [--agent-timeout <seconds>] [--budget <tokens>] [--confirm] [--ledger <path>] [--no-ledger] [--strict]` | Tier B live run. The agent command comes only from `GHOSTBENCH_AGENT_CMD`; without one configured, live refuses before anything runs. Per task the agent attempts the task in a contained copy (receiving `GHOSTBENCH_TASK_DIR` / `GHOSTBENCH_TASK_ID` / `GHOSTBENCH_TASK_PROMPT` and the copy path as final argument), Bench measures the changed files, and the task's tests run in the same copy. `--agent-timeout` defaults to 300s; `--budget` caps the run's estimated context tokens (refuses over the cap unless `--confirm`); `--strict` exits 1 when any task fails |
| `ghostbench compare <run-a.json> <run-b.json> [--out <file>]` | Per-task token and status deltas (B - A). `.json` out writes the compare object, anything else writes Markdown. Warns when estimator versions differ |
| `ghostbench add <corpus.json> --project <path> --id <id> [--name <name>]` | Record a project in a corpus file by tree hash |
| `ghostbench demo-corpus <dir>` | Write the core's starter adversarial corpus into a directory you choose |
| `ghostbench version` | Print the version |

## Your own corpus in three steps

1. **Start from the template.** Copy `examples/corpus-template/`
   somewhere of your own and edit its `corpus.json`, or create a
   fresh corpus by recording a project:
   `ghostbench add my-corpus.json --project ~/my-project --id my-project`.
   Either way, no project code is copied into the corpus file; the
   project is recorded by path plus tree hash.
2. **Write real tasks.** Give each task an `id`, a `prompt` written
   the way you would ask an agent, and the `expected_files` a correct
   fix should touch. Add a `recorded_patch`, a `test_command`, a
   GhostVerify `verify_report`, or provided bundle `variants` only
   where you have them; all are optional (see Corpus format). A task
   with no recorded patch and no test result scores `unknown` in
   Tier A, honestly, rather than pass.
3. **Run and read the failures first.**
   `ghostbench run my-corpus.json --out /tmp/my-run --strict`.
   `--strict` makes the command exit 1 when any task fails, which is
   what CI wants; the report itself always lists every failure.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success. For `run`, also: no `--strict` failure. |
| 1 | `run --strict` / `live --strict` only: at least one task failed. The report is still written. |
| 2 | Usage error, corpus error (missing file, invalid JSON, duplicate id, missing project path, non-positive budget), or a Tier B refusal. For Tier B, the refusal message states the reason - no agent configured, or the estimated run context over the `--budget` cap without `--confirm` - and that nothing was run. |

Running with no subcommand prints the help text and exits 2.

## Troubleshooting

- **`error: corpus file not found`** - the first argument is the
  corpus JSON file itself (for example
  `examples/corpora/adversarial/corpus.json`), not its folder.
- **`error: project ...: path is not a directory`** - project paths
  resolve relative to the corpus file, not to your current directory.
  Check the `path` value in the corpus, or record the project again
  with `ghostbench add` from the machine that holds it.
- **The GhostBus corpus does not run** - its project path is the
  relative path `../../../../ghostbus` to a sibling GhostBus
  checkout (see `examples/corpora/ghostbus/README.md`). If your
  GhostBus checkout lives elsewhere, do not edit the starter in
  place; record it in your own corpus with `ghostbench add`.
- **A task scores `unknown`** - Tier A had nothing to score it with:
  no recorded patch and no test result. Add a `recorded_patch`, or
  re-run with `--run-tests` and a task `test_command`.
- **The adversarial run shows failures** - that is the designed
  outcome, not a broken install. See Quickstart step 1.
- **`Tier B refused: ...`** - no agent is configured, the
  configured command could not be parsed, or the run's estimated
  context is over your `--budget` cap. Read the message: for an
  agent problem it names `GHOSTBENCH_AGENT_CMD` and shows how to
  set it; for a budget problem it prints the estimate, the cap,
  and the exact `--confirm` invocation. Nothing ran and nothing
  was written either way.
- **Compare warns that estimator versions differ** - the two runs
  were measured with different estimators, so their totals are not
  directly comparable. Re-run one side so both reports carry the
  same `estimator_version`.

## Scoring (deliberately boring)

- Task success: in Tier A, the recorded-patch check outcome (or the
  test outcome under `--run-tests`). In Tier B, the agent must
  produce changes in the task copy **and** the task's test command
  must pass against those changes in the same copy: a crash, a
  timeout, or no changes at all is a failed row with the reason
  shown, and a task with no test command scores `unknown` because
  nothing verified the agent's work. A nonzero agent exit is rescued
  only by changes that pass the tests; the exit code is recorded on
  the row either way. **No LLM judge in v0.1.**
- Files-touched is informational only. Extra files are not
  auto-failures; real fixes touch unexpected files.
- Expected symbols are checked lexically (whole-word, full dotted
  name or its last component) against the task's `expected_files`.
  When the sliced arm is derived from those files, an expected symbol
  absent from them is a symbol the slice cannot contain, so the task
  fails visibly, like a Verify hard gap. When the sliced arm is a
  provided bundle Bench cannot inspect, the check is reported
  descriptively and does not gate the task. Which expected symbols a
  recorded patch's added lines mention is recorded informationally
  in `symbols_score`, never as a failure on its own. This is a static
  lexical check, not AST or import resolution.
- Flakiness is reported, not hidden: a Tier B task that passes one arm
  and fails the other on a re-run is marked flaky.
- Every report shows corpus version, GhostSlice version, estimator
  version, price table date, per-task rows, and **all** failures. Full
  corpus results are the default; a subset run is labelled a subset.

## Verification bar (from PLAN.md)

- A stranger following this README re-runs Tier A on the GhostBus
  corpus and gets the same per-task token numbers at the same Slice
  and estimator versions, which the report states.
- The adversarial corpus produces at least one visible failure or hard
  gap in the first published report.
- Tier B refuses to start until `GHOSTBENCH_AGENT_CMD` names an
  agent command, runs that agent only inside a contained copy, and
  scores the outcome with the task's own tests: a stand-in agent
  that fixes the task passes, and one that does nothing, crashes,
  or overruns its timeout fails with the reason recorded.
- Every `BENCH.md` number traces to a manifest hash + a report row.

## Out of scope for v0.1

Hosted leaderboards, public rankings, other people's submitted
results, telemetry, LLM-as-judge scoring, human-rating workflows,
multi-agent Tier B, and competitor comparisons. Bench measures Ghost
tools on stated corpora.

## Layout

```
src/ghostbench/     the core (Agent A): corpus loader, Tier A runner,
                    Tier B live-agent runner (GHOSTBENCH_AGENT_CMD),
                    compare, reports
tests/              format + fixture tests (run without the core) and
                    black-box CLI tests for run / live-refusal / compare
examples/
  corpora/ghostbus/      starter corpus description for the GhostBus tree
  corpora/adversarial/   bundled adversarial project + recorded patches
  corpus-template/       copy-and-fill corpus for your own project
  runs/                  labelled SAMPLE report pairs (format only)
PLAN.md             the v0.1 plan this build follows
REPORT_B.md         tests/docs build report: honest pass/fail + assumptions
```

---
<!-- ghost-studio-footer -->
## More from Ghost Developer Studio

Ghost Developer Studio builds developer tools, AI-agent safety software, and practical apps, and sells by showing working software, not slide decks.

- [Roadmap board](https://github.com/littlestjames82-sys/ghost-roadmaps): where every studio product stands
- [Agent Seatbelt](https://github.com/littlestjames82-sys/agent-seatbelt): deterministic guardrails for AI coding agents
- [Ghost Hands](https://github.com/littlestjames82-sys/ghost-hands): governed, recorded, replayable agent hands
- [GhostSlice](https://github.com/littlestjames82-sys/ghostslice): agent context and prompt optimizer
- [GhostIDE](https://github.com/littlestjames82-sys/ghostide-android): fully offline AI code editor for Android
- [All studio projects](https://github.com/littlestjames82-sys?tab=repositories)
