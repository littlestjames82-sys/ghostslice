# How GhostWorkflow works

## What it does

`ghostworkflow run <project> --task "<text>"` performs one
end-to-end pass over a project with the four Ghost engines, in
order, and produces two things a human can open: a GhostConsole
board and a workflow report. It is a sequencer and a recorder. All
analysis belongs to the engines; all rendering belongs to
GhostConsole.

## Lifecycle

1. **Discovery.** Each engine is located before anything runs:
   first a console script on PATH, then a checkout tree under the
   engine home (`--engine-home`, else `GHOSTWORKFLOW_ENGINE_HOME`,
   else the directory containing the ghostworkflow checkout). A
   checkout is invoked as `python3 -m <engine>` with its `src/` on
   PYTHONPATH. Found engines are probed for their version
   (`--version`; GhostBench answers its `version` subcommand). The
   discovery result lands in the report's `engines` map whether the
   engine was found or not.
2. **Slice.** `ghostslice task <project> --task "<text>" -o <bundle>`
   when a task is given, else `ghostslice export`. The step is ok
   when the engine exits 0 and the bundle's `manifest.json` is
   present and readable.
3. **Verify.** `ghostverify pre <project> <bundle> [--task ...]
   --out-dir <verify>`. The verdict is read from
   `verify-report.json`, in GhostVerify's own vocabulary:
   `sufficient` is ok; `gaps_found` is **attention** (a recorded
   outcome; the run continues and exits 0); `could_not_verify` is a
   failure (GhostVerify's rule, adopted here: it is never a pass).
   An exit code that contradicts a `sufficient` verdict is not
   trusted as a pass.
4. **Bench.** A corpus for the project is reused when one is found
   (at `<project>/.ghostworkflow/corpus.json` or
   `<project>/corpus.json`) that records this project. Otherwise one
   is created at `<project>/.ghostworkflow/corpus.json` with
   `ghostbench add` (which records the project by tree hash and
   copies no code), and a starter task is added to it: the `--task`
   text as its prompt and `--test-command` as its test command.
   Then `ghostbench run <corpus> --out <bench>`, with `--run-tests`
   when a test command was configured (GhostBench executes tests in
   its contained runner). Verdict and verification level come from
   `bench-report.json`: failing tasks make the step attention; the
   step's level is the report's own `verification_level`.
5. **Console.** `ghostconsole build <project> -o <out>/board.html`.
   Always attempted, even after a failure: the board shows whatever
   reports exist, and absence is shown as absence.
6. **Report.** `workflow-report.json` is assembled, validated
   against the evidence contract (see below), and written next to
   the board. A report that fails validation is refused, not
   written.

Default output location is `<project>/.ghostworkflow/<run-id>/`;
`--out` overrides it. The corpus is the one artifact kept outside
the run directory (at `<project>/.ghostworkflow/corpus.json`) so
later runs reuse it.

## Failure semantics

- A step fails when its engine cannot be found, exits nonzero
  outside its stated verdicts, times out (per-engine `--timeout`,
  default 600s), or its expected report is missing or unreadable.
- A failed step stops the engine sequence: the remaining engine
  steps are recorded with status `skipped` and the reason named.
  The Console step is exempt from skipping; it is always attempted.
- The workflow report is written on every run that gets past
  argument validation, failures included, and the process exit code
  is 1 when any step failed.
- Attention is not failure. A run whose worst outcome is a
  `gaps_found` verdict or bench tasks failing exits 0 with verdict
  `attention`: the chain worked; the evidence is unflattering.
- Nothing is fabricated. A missing engine produces a failed step
  with the searched locations named, not a placeholder report; a
  tree hash that no engine recorded is `null` with a
  `tree_hash_source` that says why.

## The workflow report

`workflow-report.json` follows the shared evidence contract
(schema: `schemas/workflow-report.schema.json`):

- `project` (name + path), `task`, `timestamp` (run start, ISO
  UTC), `run_id`
- `commit` / `tree_hash`: taken from the GhostBench report's task
  rows (`project_commit` / `project_tree_hash`), falling back to
  the corpus record's tree hash; `tree_hash_source` states which,
  or why both are null. The GhostSlice manifest carries neither,
  and none is invented from it.
- `tool` / `tool_version`: ghostworkflow itself; `engines`: each
  engine's found flag, version (from its CLI), and how it was
  invoked (`path` or `checkout`)
- `verdict`: `ok` | `attention` | `failed`, derived as above
- `verification_level`: strongest level across the run's ok and
  attention steps (`none` < `static-analysis` < `tests-executed`
  < `live-agent`). Slice and Verify evidence is static; Bench
  raises the level when its tests actually ran.
- `provenance`: `live` (these reports come from real runs, never
  shipped samples)
- `steps[]`: name, status (`ok` | `attention` | `failed` |
  `skipped`), argv exactly as invoked, exit code, start/finish
  timestamps, duration, report paths, the engine's own verdict
  where it states one, the step's verification level, and a plain
  detail line.

Validation is a focused stdlib checker in
`src/ghostworkflow/evidence.py`, mirroring the schema's required
fields and types. It is not a general JSON-Schema engine.

## How Console renders the result

GhostConsole needs no workflow adapter in v0.1: the engines' native
reports land where Console already looks. The Slice history, the
Verify report, and the Bench report are under the project (the
Bench and Verify run outputs live under `.ghostworkflow/<run-id>/`,
inside Console's bounded search), so `ghostconsole build` shows
Slice, Verify, and Bench rows with their verification levels and
honest placement reasons. The workflow report itself is the
connective record across the rows; a dedicated Console row for it
is v0.2 work, deliberately not faked in v0.1.

## Out of scope in v0.1

Tier B live runs (GhostBench's `live` stays gated off), Verify
`fix`/`post` in the default path, hosted anything, scheduling, and
any write to an engine's code or reports beyond invoking its CLI.
