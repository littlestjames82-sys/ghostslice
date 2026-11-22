# GhostShard
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostshard/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostshard/actions/workflows/ci.yml/actions)

**Plan the packets. Shard never runs the work.**

GhostShard takes one large task on one large project and produces
an ordered set of per-shard context bundles: which shard owns
which files, which shards must run after which, which can run in
parallel, and what each packet is estimated to cost. It is the
multi-agent companion to GhostSlice (one bundle for one task) and
the planning front-end for GhostBus (which owns transport and
dispatch, at a separate gate).

By Ghost Developer Studio. MIT licensed. **Zero dependencies**
(Python standard library only), **local-first**: no network, no
telemetry, and **no execution of any kind**: GhostShard does not
run agents, dispatch jobs, contact any relay, approve actions, or
merge results. Its only outputs are files.

Position in the Ghost stack: GhostSlice governs what one agent
reads for one task. GhostShard plans what many agents would each
read for one large task. Agent Seatbelt governs what agents do.
Ghost Hands is the governed browser body.

## At a glance

| GhostShard does | GhostShard does not |
|---|---|
| Read a project and a task | Run agents or any project code |
| Decide file ownership, order, and parallel groups | Dispatch jobs (every manifest job is `"dispatch": false`) |
| Write per-shard bundles, `shards.json`, and `PLAN.md` | Contact GhostBus, a relay, or any network service |
| Validate a plan folder with `check` | Approve actions or merge shard results |
| Estimate per-shard token cost (labelled estimates) | Call an LLM to split, judge, or write subtasks |

If you only read one more section, read **The two split modes**
(next-but-one below): every plan is labelled with the mode that
made it, and the label tells you how much to trust the split.

Contents: [Install](#install) · [Quickstart](#quickstart) ·
[Split modes](#the-two-split-modes-always-labelled) ·
[Ownership and sequencing](#ownership-sequencing-parallelism) ·
[Schedule analysis](#schedule-analysis) · [Fit and caps](#fit-and-caps) · [Output layout](#output-layout) ·
[GhostBus boundary](#the-ghostbus-boundary) ·
[Reading a plan](#reading-a-plan-in-60-seconds) ·
[Troubleshooting](#troubleshooting) · [Honest limits](#honest-limits) ·
[Tests](#tests)

## Install

No install needed to try it from a checkout:

```bash
cd ghostshard
PYTHONPATH=src python3 -m ghostshard --help
```

Or install it (still zero dependencies):

```bash
pip install .
ghostshard --help
```

Requires Python 3.10 or newer.

## Quickstart

```bash
# auto-clustered: one freeform task, the graph does the split
ghostshard plan ~/my-project --task "Add an alpha summary report and a beta CSV export" -o /tmp/shards-out

# user-split: you pre-split the work in a task file (see below)
ghostshard plan ~/my-project --task-file tasks.md -o /tmp/shards-out

# validate a plan folder (bundles, ownership, dependency graph)
ghostshard check /tmp/shards-out

# re-write the GhostBus-shaped manifest (a file; sends nothing)
ghostshard export-bus /tmp/shards-out
```

Which command do you want?

| Goal | Command |
|---|---|
| Split one freeform task by the dependency graph | `ghostshard plan <project> --task "..." -o <out>` |
| Split work you have already divided yourself | `ghostshard plan <project> --task-file <file> -o <out>` |
| Verify a plan folder someone handed you | `ghostshard check <folder>` |
| Re-write the GhostBus-shaped manifest file | `ghostshard export-bus <folder>` |

Add `--json` to `plan` or `check` for a machine-readable summary
instead of the text summary. Run `ghostshard --help`, or
`ghostshard plan --help` (likewise `check` / `export-bus`), for
the full flag reference.

Exit codes: `plan` exits 1 when the plan is **partial** (a cap was
hit or a shard is unfittable), 0 for a complete plan, 2 for usage
errors. `check` exits 0 when valid, 1 with every failure printed.
`export-bus` exits 0 when the manifest is written, 2 when
`shards.json` is not found in the folder.

## The two split modes, always labelled

Every artifact (`shards.json`, `PLAN.md`) states which mode made
the split. No plan presents a heuristic split as a designed one.

- **user-split**: you write the subtasks in a task file, one
  `## Heading` per subtask with free text under it. Text before
  the first heading (other than `#` comment lines) is an error.
  GhostShard assigns project files to your subtasks by relevance
  scoring; the assignment is heuristic and `PLAN.md` says so.
- **auto-clustered**: one `--task` string. GhostShard selects the
  relevant files, clusters the import/call graph (weakly connected
  components, strongly connected components contracted into one
  unit), and generates shard descriptions from the graph. The
  shard task text in this mode is a generated graph description,
  labelled generated, never an invented prompt.

No LLM is used in either mode. Subtask text is never invented.

A minimal user-split task file (`tasks.md`) looks like this:

```markdown
# Lines starting with '#' before the first heading are ignored.

## Report view
Show normalized records in the report using build_report in report.py

## Export view
Write normalized records to the export using build_export in export.py
```

Each `## Heading` starts one subtask and the free text under it
is that subtask's task text, kept verbatim. Name the files,
functions, or symbols each subtask touches: assignment is lexical
relevance scoring, so a subtask that names nothing in the project
matches no files and is reported as an `empty-shard` conflict.
See `examples/user-split.tasks.md` for a runnable version.

## Ownership, sequencing, parallelism

- A file or symbol is **owned by exactly one shard**. Other
  shards that need it get it read-only, at signatures level, in
  their bundle.
- A shard that imports a file owned by another shard
  **depends_on** that owner. Dependencies form the parallel
  groups: group 0 has no dependencies, each later group waits on
  the ones before it. The plan states the max useful parallelism
  (the largest group) rather than implying more agents always
  help.
- Conservative rule: ambiguous evidence sequences, never
  parallelises. Ambiguity in v0.1 means duplicate symbol names
  across shards, two user subtasks strongly claiming the same
  unit (a near-tie), or auto-cluster shards sharing a top-level
  package. When the rule fires it is recorded per shard in
  `rules_fired`, and collisions are named in `conflicts`.
- Cycles: an import cycle inside a project is contracted into a
  single shard, so it can never become a shard-dependency cycle.
  A dependency cycle inside a `shards.json` is a `check` failure
  with the cycle printed, never a scheduling problem.

## Schedule analysis

Every plan also carries an `analytics` block in `shards.json`
(rendered as a section in `PLAN.md`): total work, the critical
path (the dependency chain with the largest summed estimated
tokens, in dependency-first order), the makespan lower bound
under unlimited parallelism, the parallel speedup versus doing
all work sequentially, the bottleneck (largest) shard, and the
per-parallel-group makespan. Estimated tokens are only a relative
work proxy, labelled as such, never a wall-clock prediction.
`ghostshard check` recomputes the block from the shards and fails
on any mismatch, so a hand-edited schedule cannot pass as a plan.
This is analysis of the plan only: nothing is run or dispatched.

## Fit and caps

Per-shard budget (default 60000 estimated tokens) and caps
(default max 12 shards, max shared fan-out 8) come from the
profile `<project>/.ghostshard.json`:

```json
{"shard": {"budget_tokens": 20000, "max_shards": 6, "max_shared_fanout": 4}}
```

(Flat top-level keys work too, e.g. `{"budget_tokens": 20000}`.
Precedence: CLI flags override the profile, which overrides the
defaults of 60000 tokens, 12 shards, and fan-out 8.)
A shard over budget is split once by owned-file halves. A single
file whose full content alone exceeds the budget cannot be split
below file granularity: it is marked `unfittable` with the reason,
the plan is marked `partial`, and `plan` exits 1. Hitting any cap
also marks the plan partial. Nothing is ever silently dropped to
make the numbers fit. Token counts are **estimates** from the
GhostSlice-style raw estimator, labelled as such in every
artifact, not exact tokenizer counts.

## Output layout

```
<out>/
  shards.json       the plan (schema below)
  PLAN.md           human view: shard table, Mermaid dependency
                    diagram, conflicts and rules fired, totals
  bus-manifest.json GhostBus-shaped jobs file (dispatch: false)
  <shard-id>/
    manifest.json   per-file path/mode/original_tokens/
                    sliced_tokens/sha256 + totals (Slice-style)
    PROMPT.md       the shard task + its bundle contents
    files/<rel>     owned files full, shared files at signatures
```

`shards.json` per shard: `id`, `title`, `task`, `owns_files`,
`owns_symbols`, `shared_files_readonly`, `shared_symbols`,
`depends_on`, `parallel_group`, `rules_fired`, `seam_basis`
(`python-ast` for Python, import-graph/parser-lite otherwise, so
the basis of every seam is stated), `bundle`, `estimated_tokens`,
`original_tokens`, `unfittable`. Plan totals equal the sum of the
per-shard bundle manifests; shared read-only files are counted
once per shard that carries them, and the totals block says so.

`ghostshard check` validates: every bundle manifest against its
files (sha256 and token totals), unique shard ids, ownership
uniqueness, every `depends_on` target exists, the dependency
graph is acyclic, and `shards.json` estimates match the bundle
manifests.

## The GhostBus boundary

`bus-manifest.json` is a **file only**: one job per shard with
`bundle_path`, `task`, `depends_on`, an
`approval_class: placeholder-seatbelt-review`, and
`"dispatch": false`. GhostShard never sends it, never contacts
the GhostBus relay (hosted or local), and never will in this
line: execution belongs to GhostBus under Agent Seatbelt, and is
a separate decision after the plan format is proven by hand.

## Reading a plan in 60 seconds

1. Open `PLAN.md` first: mode, partial flag, shard table,
   dependency diagram, and every conflict or rule fired, in that
   order.
2. If `partial` is true, stop and read `conflicts` in
   `shards.json`: a cap was hit or a shard is unfittable, and the
   plan is honest about it rather than silently truncated.
3. Check the parallel groups: shards in group 0 can start first;
   each later group waits on its `depends_on`. The stated max
   useful parallelism is the largest group, not the shard count.
4. Run `ghostshard check <folder>` before handing bundles to
   anyone: it proves structure (ownership, acyclicity, manifest
   integrity), not that the split is a good one.

## Troubleshooting

- **`plan` exits 1 and prints "plan is PARTIAL"**: not a crash.
  A cap was hit or a shard is unfittable. The reason is named in
  `conflicts` in `shards.json` and in `PLAN.md`. Raise the limit
  (`--budget`, `--max-shards`, `--max-shared-fanout`, or the
  profile), split the oversized file by hand, or accept the
  partial plan knowingly.
- **`error: project not a directory` (exit 2)**: the first
  argument to `plan` must be an existing project directory.
- **`error: task file: content before first '## ' subtask
  heading` (exit 2)**: move any preamble into `#` comment lines,
  or give the first block of text its own `## Heading`.
- **A subtask matched no files (`empty-shard` conflict)**: the
  subtask text named nothing the scanner can find lexically.
  Mention the file, function, or symbol names it should touch.
- **`check` reports a sha256 or token mismatch**: a bundle file
  was edited after planning. Re-run `plan` to regenerate the
  bundles; do not hand-edit files inside a plan folder.
- **`check` reports a dependency cycle**: the `shards.json` was
  edited by hand (the planner contracts project import cycles
  into one shard, so it cannot emit one). Restore a
  planner-written `shards.json` or break the named cycle.

## Honest limits

- Graph quality bounds plan quality. Python gets full `ast`
  edges; other languages are import-level (parser-lite) seams,
  stated per shard via `seam_basis`.
- Relevance scoring is lexical (TF-IDF-flavoured). A subtask that
  names nothing in the project may match no files; that is
  reported as an empty-shard conflict, not hidden.
- Lone files that share a top-level package are merged into one
  miscellaneous shard per package in auto mode. Two unrelated
  modules in one folder will be planned as one shard.
- A plan being well-formed does not mean the split is good.
  `check` proves structure (ownership, acyclicity, manifest
  integrity), not judgement. Read `PLAN.md` before handing
  bundles to anyone.

## Tests

```bash
python3 -m pytest -q
# or
PYTHONPATH=. python3 -m unittest discover -s tests -t .
```

The suite drives the real CLI as a subprocess against fixtures in
`tests/fixtures/`: disjoint subgraphs that must parallelise, a
shared symbol that must sequence or name a conflict, a
hand-built dependency cycle that must fail `check`, an
import-cycle project that must be contracted into one shard, and
a single-file project that must report itself unfittable at a
tiny budget. See `examples/` for runnable walkthroughs and a
captured sample plan.

## Layout

```
src/ghostshard/
  cli.py       plan / check / export-bus commands + profile load
  planner.py   graph clustering, ownership, ambiguity sequencing,
               parallel groups, caps
  project.py   project scan, Python ast + parser-lite imports,
               SCC + cycle detection
  taskfile.py  user-split task file parser (## headings)
  bundles.py   per-shard bundles, shards.json / PLAN.md /
               bus-manifest writers, plan check
  slicing.py   signatures slicing for read-only shared files
  tokens.py    token estimator (labelled estimates)
tests/         Agent B suite (CLI-level, fixture-driven)
examples/      runnable walkthroughs + a captured sample plan
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
