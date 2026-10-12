# GhostSlice

[![CI](https://github.com/littlestjames82-sys/ghostslice/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostslice/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/littlestjames82-sys/ghostslice)](https://github.com/littlestjames82-sys/ghostslice/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**See what your agent will read, before it runs.**

Developers running autonomous CLI agents (Claude Code, Aider, OpenClaw) burn
tokens feeding whole files, `node_modules`, and stale docs into context.
GhostSlice shows you the bill first: a visual token-cost tree, an AST slicer
that keeps only the surface you need, a pre-flight cost estimate, and a
one-click `.claude_context` bundle you can drop straight into your agent.

By Ghost Developer Studio. MIT licensed. **Zero dependencies** (Python
standard library only), **local-first**: no network calls, no telemetry,
your code never leaves the machine.

Position in the Ghost stack: Agent Seatbelt governs what an agent *does*,
GhostSlice governs what an agent *reads*.

## Install

No install needed to try it from a checkout:

```bash
cd ghostslice
PYTHONPATH=src python3 -m ghostslice --help
```

Or install it (still zero dependencies):

```bash
pip install .
ghostslice --help
```

Requires Python 3.10 or newer.

## Usage

### Scan: rank files by estimated token cost

```bash
ghostslice scan ~/my-project
ghostslice scan ~/my-project --model claude-sonnet
ghostslice scan ~/my-project --json
```

The scanner respects `.gitignore`, skips built-in junk (`node_modules`,
`.git`, `dist`, build/cache dirs, binary files), and flags test files and
lockfiles separately.

### Slice: keep only the surface

```bash
# one file
ghostslice slice src/app.py --mode signatures -o /tmp/sliced
# a whole tree (mode applies to Python / TypeScript / JavaScript files)
ghostslice slice ~/my-project --mode signatures -o /tmp/sliced-tree
```

Modes, per file:

| Mode | Python (`ast`) | TypeScript / JavaScript (parser-lite) |
|---|---|---|
| `full` | unchanged | unchanged |
| `signatures` | imports, constants, function/class signatures with first docstring line, no bodies | imports, interfaces/types in full, function and class method signatures, no bodies |
| `interfaces` | classes, type aliases, Protocol/ABC-style defs | `interface` / `type` / `enum` declarations only |
| `strip-tests` | source with `test_*` / `Test*` definitions removed; a test file slices to empty | source with `describe`/`it`/`test` blocks removed; a test file slices to empty |
| `exclude` | empty | empty |

### Export: one-click agent bundle

```bash
ghostslice export ~/my-project -o ~/my-project-context --model claude-sonnet
ghostslice check ~/my-project-context
```

Defaults: code files get `signatures`, test files get `strip-tests`,
lockfiles get `exclude`, everything else stays `full`. Override with
`--mode`.

A bundle contains:

```
< bundle >/
  manifest.json   per file: path, mode, original tokens, sliced tokens, sha256 of the slice, plus totals
  PROMPT.md       all sliced files concatenated with file headers, ready to hand to an agent
  files/<rel>     the sliced files, relative paths preserved
```

`ghostslice check` re-reads the bundle and verifies that every hash and
token total in `manifest.json` matches what is actually on disk.

### Graph: dependency map + prune recommendations (v0.2)

```bash
ghostslice graph ~/my-project          # who imports whom, plus prune candidates
ghostslice scan ~/my-project           # scan output now ends with recommendations
```

GhostSlice builds an import graph (Python via `ast`, TS/JS parser-lite)
and flags code files that are unreachable from your entry points (or,
with no entry points known, imported by nothing). Candidates carry their
token cost so you can see the saving before you act. They are
recommendations to review, never automatic deletions: dynamic imports,
framework wiring, and config-referenced entry files can look dead when
they are not.

### Task-focused context (v0.2)

```bash
# keyword-scored file selection within a sliced-token budget
ghostslice task ~/my-project --task "fix billing payments" --budget 20000 -o /tmp/task-bundle

# git-changed files plus their direct dependencies
ghostslice task ~/my-project --diff -o /tmp/diff-bundle
```

Both export a validated bundle containing only the selection (everything
else is recorded as `exclude` in the manifest).

### Profiles: `.ghostslice.json` (v0.2)

Drop this in a project root and every command picks it up automatically:

```json
{
  "ignore": ["vendor/**", "*.snap"],
  "modes": {"src/**": "signatures", "docs/**": "full"},
  "model": "claude-sonnet",
  "budget_tokens": 50000,
  "entry_points": ["src/main.py"],
  "preset": "claude-code"
}
```

Export presets: `claude-code` (the `.claude_context` bundle), `aider`
(adds `aider-files.txt`, a plain list of the sliced files to pass to
Aider with `--read`), and `generic` (adds a lowercase `prompt.md`).
Nested `.gitignore` files in subdirectories are honoured, scoped to
their subtree.

### Budget gate for CI (v0.2)

```bash
ghostslice check-budget ~/my-project --max-tokens 50000   # or profile budget_tokens
echo $?   # 1 when the selected (sliced) context exceeds the budget
```

### Savings ledger (v0.2)

Every export appends one line to `.ghostslice-history.jsonl` in the
project (scanner-ignored). `ghostslice history ~/my-project` and the
dashboard total the estimated savings across runs.

### Dashboard: visual context tree

```bash
ghostslice serve ~/my-project --port 8765
# open http://127.0.0.1:8765/
```

A single-page local UI (served by the Python process, bound to 127.0.0.1):
files sorted by token cost with a heat bar, click a row to include/exclude
it, a per-file mode selector, live before/after totals, a model selector
with pre-flight dollar cost, a slice preview pane, and an Export button
that writes a `.claude_context` bundle inside the served project.

## Honest labels

- **Token counts are estimates.** Method: a BPE-like split (word and
  punctuation chunks count as 1 token up to 4 characters, then 1 token
  per 4 characters; whitespace is not counted separately). This is near
  the usual "about 4 characters per token" rule for code, but it is not
  any model's exact tokenizer. See `src/ghostslice/tokens.py`.
- **Prices are local and dated, never live.** `prices.json` (repo root
  and `src/ghostslice/prices.json`) carries an `as_of` date (currently
  2026-10-12) and editable per-model input/output rates. Nothing is
  fetched. Verify rates with the provider before relying on a figure.
  Pre-flight cost counts context (input) tokens only.
- **TypeScript/JavaScript slicing is parser-lite.** Python uses the real
  `ast` parser. TS/JS uses line scanning, regexes, and brace matching;
  it handles conventional shapes (functions, arrow functions, classes,
  interfaces, types, enums, test blocks) and can slice exotic syntax
  imperfectly.

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests -q
# or, anywhere:
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Layout

```
src/ghostslice/
  tokens.py     token estimator (documented method)
  scanner.py    .gitignore-aware project scanner (nested .gitignore support)
  slicer.py     Python ast slicer + TS/JS parser-lite slicer (+ Go/Rust/Java/C# lite in v0.3)
  graph.py      import graph + prune recommendations + git changed-files
  profile.py    .ghostslice.json profile loader
  selection.py  task keyword / git-diff context selection
  ledger.py     .ghostslice-history.jsonl savings ledger
  mcp_server.py stdio MCP server (v0.3)
  pricing.py    local prices.json loader + cost estimator
  exporter.py   bundle builder + validator (presets: claude-code/aider/generic)
  server.py     stdlib http.server dashboard API
  dashboard.html  single-page dashboard UI (violet accent #6716f3)
  cli.py        ghostslice command line
prices.json     editable local price table (dated)
```
