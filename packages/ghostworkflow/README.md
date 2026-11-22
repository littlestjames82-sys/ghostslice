# GhostWorkflow
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![CI](https://github.com/littlestjames82-sys/ghostworkflow/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostworkflow/actions/workflows/ci.yml)

**Run the Ghost ecosystem end to end on one project, and keep the receipt.**

GhostSlice builds the context bundle, GhostVerify checks it before
an agent run, GhostBench measures the task on it, and GhostConsole
renders the board a human opens. Until now, running that chain meant
running four tools by hand and assembling the story yourself.
GhostWorkflow is the thin orchestrator that runs the chain:

```sh
ghostworkflow run ~/work/app --task "Fix checkout totals using compute_total"
```

It invokes each engine through its own CLI (never by importing it),
lets each engine write its native reports into the project, renders
the board last, and writes one `workflow-report.json` next to it:
the evidence record for the run, carrying the shared evidence
contract fields (project, task, commit/tree hash, tool and engine
versions, timestamp, verdict, verification level, provenance) and a
per-step record with argv, exit codes, and timing.

GhostConsole stays read-only. This is the tool that runs things;
that separation is deliberate, and it is why the board can be
trusted.

By Ghost Developer Studio. MIT licensed. **Zero dependencies**
(Python standard library only), local-first, no network, no
telemetry.

## Install

Requires Python 3.10 or newer.

```sh
pip install .
ghostworkflow --help
```

Without installing, run it from a source checkout as a module:

```sh
PYTHONPATH=src python3 -m ghostworkflow --help
```

The four engines are found at run time: a console script on PATH
wins; otherwise a checkout tree (`ghostslice/`, `ghostverify/`,
`ghostbench/`, `ghostconsole/`) under `--engine-home`,
`GHOSTWORKFLOW_ENGINE_HOME`, or next to the ghostworkflow checkout.

## Quick start

```sh
# Full chain for one project and one task
ghostworkflow run ~/work/app --task "Fix checkout totals using compute_total"

# Execute the project's tests as part of the bench step (contained)
ghostworkflow run ~/work/app --task "..." --test-command "python3 -m pytest -q"

# Choose where the run's outputs land (default: <project>/.ghostworkflow/<run-id>/)
ghostworkflow run ~/work/app --task "..." --out /tmp/app-run
```

Each run directory holds `bundle/` (the GhostSlice bundle),
`verify/verify-report.json`, `bench/bench-report.json` + `BENCH.md`,
`board.html`, and `workflow-report.json`.

## Exit codes

- `0`: the run completed. Every step is ok or honestly attention:
  a `gaps_found` Verify verdict or a Bench run with failing tasks
  is a recorded outcome, not a crash.
- `1`: a step failed: an engine exited nonzero outside its stated
  verdicts, could not be found, timed out, or its expected report
  is missing or unreadable. Later engine steps are recorded as
  skipped, the Console render is still attempted, and the workflow
  report is still written.
- `2`: usage error (for example, the project is not a directory).

## The verdict and the level

The run's `verdict` is `failed` if any step failed, else
`attention` if Verify found gaps or Bench recorded failing tasks,
else `ok`. The `verification_level` is the strongest evidence the
run actually produced: `static-analysis` (bundle + static checks),
`tests-executed` (the project's own tests ran in GhostBench's
contained runner), `live-agent` (a real agent attempted the task;
nothing in v0.1 emits this yet), or `none`. Levels are read from the
engines' own reports, never inferred upward.

Full lifecycle, failure semantics, and report format:
[docs/WORKFLOW.md](docs/WORKFLOW.md). The report's JSON Schema is
[schemas/workflow-report.schema.json](schemas/workflow-report.schema.json).
Test state: [RESULTS.md](RESULTS.md).

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
