# GhostShard v0.1 - Implementation A (core builder)

Built Oct 14, 2026 from `PLAN.md`. Agent A ownership: `src/**`,
`pyproject.toml`, this file only. Tests/README/examples belong to Agent B.

## Boundary held
PLANNER ONLY. No dispatch, no agent execution, no merging, no GhostBus
relay contact, no network, no LLM, no subprocess/exec primitives in
`src/ghostshard/` (grep-verified: no urllib/requests/socket/subprocess/
os.system/http). GhostBus output is a JSON file with `"dispatch": false`
on every job. No push, publish, or spend.

## What was built
Python stdlib only, zero dependencies, Python >=3.10. Package
`src/ghostshard/` v0.1.0:

- `project.py` - scanner (respects `.gitignore` names + built-in ignores),
  Python `ast` symbols/imports/references, parser-lite imports/defs for
  JS/TS/other (seam basis recorded per shard), import graph, Tarjan SCC,
  cycle finder.
- `tokens.py` - GhostSlice-style raw token estimator. All counts are
  labelled estimates in every artifact.
- `slicing.py` - read-only context: Python signatures via `ast`
  (imports, defs/classes, first docstring line, constants); parser-lite
  definition lines for other languages.
- `taskfile.py` - user-split task file format (`## Title` sections;
  content before the first heading is an error) + slugify.
- `planner.py` - the planner:
  - SCC contraction, so a project import cycle can never become a
    shard dependency cycle (cycle members port/move together).
  - User-split: TF-IDF-flavoured scoring assigns each SCC unit to a
    subtask; near-tie claims (>=0.75 of best) become named conflicts -
    one owner, others sequenced after it.
  - Auto-clustered: weakly-connected components over task-relevant
    files, tiny singleton components merged per top-level package.
    Labelled `auto-clustered` in `shards.json` and `PLAN.md`, with the
    mode label spelled out as heuristic; user-split labelled likewise.
  - Ownership: each file/symbol owned by exactly one shard. Importers
    of another shard's file get it read-only at signatures and a
    `depends_on` edge to the owner.
  - Conservative rule (recorded in `rules_fired`): duplicate symbol
    names across shards, near-tie claims, and (auto mode) shared
    top-level package all force sequencing, never parallel.
  - Parallel groups = topological levels; `max_parallelism` = largest
    group, stated instead of implying more agents always helps.
  - Caps (`max_shards`, `max_shared_fanout`) and unfittable shards
    mark the plan `partial: true` and the CLI exits 1. Nothing is
    silently dropped.
- `bundles.py` - per-shard Slice-style bundles (`manifest.json` with
  per-file mode/original/sliced token estimates + sha256, `PROMPT.md`,
  `files/`), fit step (split owned set by halves; a single file over
  budget at full mode is unfittable with the reason recorded),
  `shards.json` + `PLAN.md` writers (shard table, Mermaid dependency
  graph, conflicts/rules), `check_plan()`, and the GhostBus-shaped
  manifest export (file only).
- `cli.py` - `ghostshard plan <project> (--task | --task-file) -o <out>
  [--budget] [--max-shards] [--max-shared-fanout] [--json]`,
  `ghostshard check <folder>`, `ghostshard export-bus <folder>`.
  Profile: optional `.ghostshard.json` in the project (`shard` section
  or flat: budget_tokens / max_shards / max_shared_fanout).

## Smoke test results (run by Agent A, fixtures in /tmp/gs-smoke)
- Compile: `python3 -m py_compile src/ghostshard/*.py` OK; `--help` OK;
  `pip install . -t /tmp/gs-smoke/pkgtest` produced the package.
- Disjoint, user-split (alpha/beta fixtures): 2 shards, same parallel
  group, max_parallelism 2, `check` OK, zero shared owned files.
  Plan total 52 estimated tokens = sum of bundle manifests exactly.
- Disjoint, auto-clustered: 2 shards, parallel, `check` OK.
- Shared symbol, user-split: `core/util.py` owned by Core shard only;
  Feature shard carries it in `shared_files_readonly`, lists
  `shared_symbols: [shared_util]`, `depends_on` Core, group 1 vs 0;
  conflict named in `shards.json`. Auto mode conservatively merged the
  connected files into one shard.
- Conservative ambiguity: two files defining the same symbol `run`
  with no import edge were sequenced (rule recorded), not paralleled.
- Cycle: hand-injected shard dependency cycle makes `check` FAIL with
  the cycle printed (shard-01 -> shard-02 -> shard-01), exit 1.
- Unfittable: `--budget 5` gives `partial: true`, exit 1, and an
  unfittable entry naming the single file and budget.
- Tamper: appending to a bundle file makes `check` FAIL on sha256 and
  sliced-token mismatch.
- Bus export: `export-bus` rewrites `bus-manifest.json` file only,
  jobs carry bundle path, task, depends_on, approval_class placeholder
  `placeholder-seatbelt-review`, `dispatch: false`.

## Known limits (stated for B / parent verification)
- Non-Python seams are import-level only (parser-lite), labelled.
- Auto-cluster task text is a labelled generated graph description,
  not a written prompt (by design; no invented sub-prompts).
- Fit-split can create `-partN` bundle ids whose `depends_on` still
  references the base plan edges recorded in `shards.json` for the
  split entries; exercised only in the over-budget path.
- Recall/Verify hooks from PLAN.md are format-level only: no Recall
  items are attached and no Verify verdicts are recorded in v0.1 core
  (no such companion output existed to consume yet). `shards.json`
  leaves room for both without breaking `check`.
