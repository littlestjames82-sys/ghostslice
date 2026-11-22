# GhostShard - Agent B Report (tests / README / examples)

Date: Oct 14, 2026. Scope owned: `tests/**`, `README.md`,
`examples/**`, this report. Nothing under `src/**` or
`pyproject.toml` was edited by Agent B.

## Core readiness (assumptions)

Agent A's core landed in parallel during this build and was
complete by test time: `src/ghostshard/{__init__, __main__, cli,
planner, project, taskfile, bundles, slicing, tokens}.py` plus
`pyproject.toml`. The tests therefore assert the core's REAL
documented contract rather than a guessed one:

- CLI: `python -m ghostshard plan <project> (--task | --task-file)
  [-o OUT] [--budget N] [--max-shards N] [--max-shared-fanout N]
  [--json]`; `check <folder> [--json]`; `export-bus <folder> [-o]`.
- Profile: `<project>/.ghostshard.json`, `shard` section or flat
  keys `budget_tokens / max_shards / max_shared_fanout`, defaults
  60000 / 12 / 8, CLI flags override.
- Task file: subtasks start at `## ` headings (title + free text);
  content before the first heading is an error.
- Modes are the strings `auto-clustered` and `user-split`, with a
  self-describing `mode_label` in `shards.json` and the mode named
  in `PLAN.md`.
- `shards.json` schema, bundle manifest schema, and
  `bus-manifest.json` schema exactly as written in
  `tests/helpers.py` (its module docstring is the contract the
  tests assert).

One planner behaviour shaped a fixture: in auto mode, lone files
sharing one top-level package are merged into a single
per-package shard. The disjoint fixture therefore puts its two
modules in separate packages (`alpha/alpha.py`, `beta/beta.py`);
a first flat-layout run confirmed they would otherwise merge
into one shard and the fixture could not prove disjointness.

Fixture harness note: only `*.py` sources are copied into temp
projects by the tests, because the scanner treats `.md`/`.txt` as
project text; fixture README/TASK files inside a fixture project
would pollute the graph being measured. Task text is passed via
`--task` or a `--task-file` kept outside the copied project.

## What was built

### tests/ (27 tests, all CLI-level via subprocess)
- `tests/helpers.py` - CLI runner (PYTHONPATH=src), fixture
  copiers, plan/check drivers, manifest loaders.
- `tests/test_plan_disjoint.py` (5 tests) - disjoint fixture:
  two shards, one owning `alpha/alpha.py`, one `beta/beta.py`,
  single parallel group, max parallelism 2, no dependencies,
  zero shared-owned files, bundles present on disk.
- `tests/test_plan_shared.py` (4 tests) - shared-symbol fixture:
  `shared_core.py` has exactly one owner; no file is doubly
  owned; the non-owner shard is sequenced after the owner
  (different parallel group) or the collision is named in
  `conflicts`; shared symbols arrive named when present.
- `tests/test_check_cycle.py` (8 tests) - the hand-built cycle
  fixture fails check with exit 1 and the printed cycle naming
  both shards (text and `--json` paths); structural rules
  (unknown dependency, duplicate ownership) fail; a minimal valid
  plan passes; missing `shards.json` fails; the source import
  cycle (a.py <-> b.py) is contracted into one shard and the
  resulting plan passes check.
- `tests/test_unfittable.py` (3 tests) - 20k-char single-file
  hub at `--budget 250`: the plan admits failure (exit 1 +
  `partial` true + shard `unfittable` true + a conflict naming
  `hub.py`), and the file is present whole in exactly one bundle
  (nothing silently dropped).
- `tests/test_reproduction_labelling.py` (7 tests, 3 subtests) -
  plan totals equal the sum of per-shard bundle manifests (both
  sliced and original), manifest row sums and shard ids match;
  generated plans for disjoint/shared/import-cycle pass `check`;
  auto and user-split modes are labelled in both `shards.json`
  and `PLAN.md`; the estimator string labels counts as estimates;
  every bus-manifest job has `dispatch: false` and a Seatbelt
  approval placeholder; `export-bus -o` writes a file and prints
  that nothing was sent.

### tests/fixtures/
- `disjoint/` - two independent packages + TASK.txt + README.
- `shared/` - `shared_core.py` imported by both `report.py` and
  `export.py`, pre-split `tasks.md`, README.
- `cycle/plan_folder/` - hand-built plan in the exact planner
  schema with a shard-a <-> shard-b dependency cycle; bundle
  hashes/token totals generated with the core estimator so the
  cycle is the ONLY check failure. `cycle/project/` - a.py <-> b.py
  import cycle. README explains both halves.
- `unfittable/` - generated `hub.py` (20,395 chars, 26 functions,
  all in one file) + TASK.txt + README.

### README.md
Full root README (also the file `pyproject.toml` points at as the
package readme): boundary statement (planner only, no dispatch,
no execution), install, quickstart, both split modes and their
labelling, ownership/sequencing rules, fit and caps, output
layout and schemas, the GhostBus file-only boundary, honest
limits (including the per-package merge behaviour and lexical
scoring), test instructions, layout.

### examples/
- `examples/README.md` - three runnable walkthroughs (auto plan,
  user-split plan, profile) plus the bus-manifest note.
- `examples/auto-task.txt`, `examples/user-split.tasks.md`,
  `examples/profile.ghostshard.json`.
- `examples/sample-output/` - a REAL captured run of the auto
  walkthrough (Oct 14, 2026): shards at 354 and 329 estimated
  tokens, total 683, one parallel group of 2. Not hand-written.

## Verification (honest results)

- `python3 -m pytest tests -q`: **27 passed, 3 subtests passed**
  (19.97s).
- `python3 -m unittest discover -s tests -t .`: **27 tests, OK**
  (20.99s).
- Manual spot runs, all as documented:
  - disjoint plan + `check`: exit 0, "check OK: 2 shard
    bundle(s), ownership unique, acyclic".
  - user-split example: `shard-01-report-view` owns `report.py` +
    `shared_core.py` (group 0); `shard-02-export-view` owns
    `export.py`, depends on shard-01, carries `shared_core.py`
    read-only (group 1); conflict string names the shared unit
    and both claimants.
  - cycle fixture: `check` exit 1, "dependency cycle detected:
    shard-a -> shard-b -> shard-a".
  - unfittable fixture at budget 250: `plan` exit 1, partial
    true, shard estimated 6,655 tokens, `unfittable: true`,
    conflict names `hub.py` and the file-granularity reason.

No failures at delivery time. Nothing was skipped: the
`skipUnless(core_available())` guard in each test module exists
only so the suite degrades to skips (rather than 27 import
errors) if run before the core exists; with the core present,
zero tests skipped under both runners.

## Gates honoured

Planner only (no agent work executed by any test; plans were the
only thing run), no network calls, no push, no publish, no spend.
File ownership respected: only `tests/**`, `README.md`,
`examples/**`, and this report were written.
