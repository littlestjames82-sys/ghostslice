# GhostRecall
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostrecall/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostrecall/actions/workflows/ci.yml/actions)

**Give your agent the project's memory, sliced like its code.**

GhostSlice gives an agent the code, sliced to what a task needs. It
says almost nothing about *why* the code is that way: decisions made
last month, routes already tried and rejected, standing rules that
live in a founder's head. GhostRecall slices that project memory -
decisions, notes, changelogs, git history - with the same discipline:
token costs up front, modes per item, provenance on everything, and a
manifest you can verify.

By Ghost Developer Studio. Working name (PLAN.md). Design target:
zero dependencies, Python standard library only, local-first: no
network, no embeddings, no telemetry, your project memory never
leaves the machine.

Position in the Ghost stack: GhostSlice governs what an agent reads
about the *code*, GhostRecall governs what it reads about the
*project*, GhostVerify checks the combined bundle was enough, Agent
Seatbelt governs what an agent *does*.

## Install and quick start

Requires Python 3.10 or newer. There is nothing else to install:
GhostRecall has zero dependencies.

```bash
# From a checkout of this repository
pip install -e .

ghostrecall --version          # ghostrecall 0.1.0
ghostrecall --help             # every command, with a worked example list

# Without installing, from the repository root:
PYTHONPATH=src python3 -m ghostrecall --help
```

Then point it at any project directory:

```bash
# 1. See what memory the project has, and what it would cost
ghostrecall scan path/to/project

# 2. Rank that memory for the task at hand
ghostrecall recall path/to/project --task "How does local storage work?"
```

`examples/sample_project/` is a complete tiny project you can run
those two commands against right away; see `examples/README.md`.

## What it reads (project-local only)

- `DECISIONS.md` in the documented format below (parsed into
  individual decision records)
- Markdown / text notes, ADRs, `docs/` trees, `CHANGELOG.md`
- Build / audit / roadmap reports the project itself saved
- Local git history (commit messages; local git only, no hosting API)

Boundary rule, not a setting: GhostRecall only reads inside the
project root you point it at. It never imports an assistant's private
memory, chat transcripts outside the project, or email. If a source
is outside the project, it is not a source.

## The DECISIONS.md format

```markdown
## D-001 (2026-01-15)
Decision: The demo shop ships orders every weekday at 4pm.
Reason: The carrier pickup is scheduled for 4:30pm.
Supersedes: none
Status: current
Tags: rule, shipping
```

One decision per `## ` heading. The heading carries the decision id
and its date (`## D-<number> (<YYYY-MM-DD>)`); the fields are plain
`Key: value` lines. Recognised fields are `Decision`, `Reason`,
`Supersedes`, `Status`, `Tags`, `Date` (only needed when the heading
has no date), and `Rule` (`true` / `yes` pins the decision like the
`rule` tag). Any other lines in the block are kept as part of the
record. `examples/DECISIONS.example.md` is a copyable starter file.

- Tag a decision `rule` and it becomes a standing rule: pinned into
  bundles for its scope even when ranking would have skipped it, and
  marked pinned in the manifest (never disguised as a ranked hit).
- A newer decision names what it replaces in `Supersedes:`; the old
  one is then shown as superseded or excluded, never silently served
  as current. Contradictions inside one bundle are flagged as
  conflicts, not quietly resolved.
- That flagging also covers *unlinked* contradictions: two active
  decisions whose decision lines share a topic (at least two content
  terms) but say opposite things - one negates a term the other
  asserts, or they use an opposite directive pair such as
  enable/disable or open/close - are reported in the manifest and
  `RECALL.md` as a `possible-contradiction` conflict naming both
  items, the shared terms, and the opposing terms. Both decisions
  stay in the bundle; Recall flags, a human settles it. Detection is
  deterministic and reads the decision line only, so an option that
  was considered and rejected in a `Reason:` is not a contradiction.
- Every record carries provenance: source file, line, date. A
  decision with no provenance is not exported.

Freeform notes still work as plain sources; they just do not get
per-decision structure.

## Modes (per memory item)

| Mode | What is kept |
|---|---|
| `full` | Whole note / decision with reason |
| `decision-only` | Decision line + date only, reason stripped (cheap default for settled rules) |
| `headings` | Headings + first paragraph under each (same treatment as GhostSlice Markdown) |
| `recent` | Last N decisions / entries for a file or topic, N from the profile |
| `exclude` | Kept out, and recorded as excluded in the manifest so the absence is auditable |

## Usage

| Command | What it does |
|---|---|
| `scan <project>` | List every memory item found, largest estimated token cost first (`--json` for JSON) |
| `recall <project> --task "..."` | Rank memory items for a task; pinned rules always included, superseded items never selected, secret-blocked items never exported |
| `explain <project> <item> --task "..."` | Explain one item for a task, as JSON: selected or not, and why |
| `bundle <project> -o <dir>` | Build a bundle folder (layout below); `--task`, `--fit <tokens>`, `--mode`, and `--slice-bundle <dir>` refine it |
| `check <bundle>` | Verify a bundle folder against its manifest; exit code 1 and one `FAIL:` line per problem |
| `panel <project> --task "..."` | Print the dashboard panel HTML fragment for a task |
| `mcp` | Run the stdio MCP server (see MCP below) |

Every command has its own `--help` with the meaning of each option.

```bash
# Ranked, task-focused memory with token costs
ghostrecall recall <project> --task "How does local storage work?"

# Show what was NOT selected, and why (misses stay visible)
ghostrecall recall <project> --task "How does local storage work?" --explain

# Explain a single item: <item> is its id, exact title, or source path
ghostrecall explain <project> decision-d-001-2026-01-15 \
  --task "How does local storage work?"

# Combined code + memory bundle under one token budget.
# Code comes from GhostSlice; memory downgrades to decision-only
# before anything is dropped. The default budget split is
# 80% code / 20% memory - a default, not a finding.
ghostrecall bundle <project> --task "..." --fit 20000 -o <bundle>

# Verify a bundle against its merged manifest
ghostrecall check <bundle>
# OK: <bundle> matches its manifest
```

A bundle is written to the folder named by `-o` / `--out`, whether it
holds memory only or memory merged with a GhostSlice bundle
(`--slice-bundle`). Its layout:

```text
<bundle>/
  manifest.json        merged manifest (below)
  PROMPT.md            one merged prompt: code context, then project memory
  RECALL.md            human report: selected / not selected / conflicts, with reasons
  files/               the sliced memory items, one file per item
  slice_manifest.json  copy of the GhostSlice manifest (only with --slice-bundle)
```

The merged `manifest.json` records, per item: source type (`code` /
`decision` / `note` / `commit`), mode, original tokens, sliced
tokens, sha256, and - for memory items - provenance and status.
Items that were not exported are listed under `excluded` with the
reason, so an absence is auditable too. Token counts in the bundle
and in `scan` / `recall` output are estimates (see Honest limits).

## Profile

GhostRecall extends the project's existing `.ghostslice.json` with a
`recall` section (no second config file to drift). Unknown keys in
that section fail loudly, the same rule as GhostSlice profiles. A
project with no `.ghostslice.json` (or no `recall` section) simply
gets the defaults.

```json
{
  "recall": {
    "default_mode": "full",
    "memory_budget_fraction": 0.2,
    "max_items": 50,
    "recent_n": 5,
    "include_git": true,
    "git_limit": 200,
    "pinned_rules": []
  }
}
```

| Key | Default | Meaning |
|---|---|---|
| `default_mode` | `full` | Mode used by `bundle` when `--mode` is not given; one of the modes under Modes above |
| `memory_budget_fraction` | `0.2` | Share of a `--fit` budget given to memory when a Slice bundle is merged; must be in (0, 1] |
| `max_items` | `50` | Most non-pinned items a selection may return |
| `recent_n` | `5` | How many items the `recent` mode keeps (last N by date) |
| `include_git` | `true` | Read local git history as a source |
| `git_limit` | `200` | Most recent commits to read |
| `pinned_rules` | `[]` | Item titles or ids to pin in addition to `rule`-tagged decisions |

## Secrets guard

Every memory source is scanned with the GhostSlice secrets guard
before export. Memory files are *more* likely than code to contain
keys and private notes, so a finding blocks that item by default.
Findings are reported as path + line + type only - the value is
never printed, logged, or exported.

## MCP

Run `ghostrecall mcp` to start the server. Same stdio pattern as the
GhostSlice MCP server (JSON-RPC, one request per line), capped
payloads: item text is truncated and result lists are limited.

- `recall_search` - ranked memory items for a task
- `recall_bundle` - build a combined bundle
- `recall_explain` - why an item was included, pinned, or left out

## Honest limits

- Selection is TF-IDF keyword ranking (the method proven in
  `ghostslice task`), not semantic search. It will miss paraphrases;
  `explain` exists so a miss is visible instead of silent.
- Memory goes stale in a way code does not. Dates, superseded
  handling, and provenance are core features for that reason.
- Extractive only: GhostRecall never summarises with a model and
  never writes decisions for you. A human (or an agent acting under
  Agent Seatbelt approval) writes `DECISIONS.md`.
- Token counts are estimates from the GhostSlice estimator; costs
  come from the same local, dated price table and are labelled
  estimates.

## Examples and tests

- `examples/sample_project/` - a tiny project with rules, notes, a
  changelog, and a superseded decision pair. See `examples/README.md`
  for commands to run against it and what to look for in the output.
- `tests/` - pytest suite against the CLI and bundle formats,
  including the PLAN.md verification bar: provenance completeness,
  superseded decisions never served as current, and a planted-secret
  note fixture that must be blocked and redacted everywhere.
  Run it with `python3 -m pytest -q` from the repository root.

## Status

v0.1 in build (Oct 2026). No public release, no PyPI publish, and no
announcement - those are separate gates, same as GhostSlice.
Pricing is not decided: the design target is an MIT core CLI in the
GhostSlice / Agent Seatbelt / Ghost Hands pattern.

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
