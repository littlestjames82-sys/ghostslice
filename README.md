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
# a whole tree (mode applies to all slicable languages, see below)
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
| `headings` | (docs/notebooks) | (docs/notebooks) |

More modes (v0.4): Markdown files support `headings` (headings plus the
first paragraph under each heading; docs still default to `full`, opt in
per-glob via a profile). Jupyter notebooks (`.ipynb`) slice to a text
rendering: `signatures`/`full` keep code-cell source only (outputs and
execution counts are stripped, markdown cells kept as comments) and
`strip-tests` drops test cells. Malformed notebooks never crash the
slicer.

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

### Auto-fit: force a bundle into a token budget (v0.5)

```bash
ghostslice export ~/my-project -o ~/my-project-context --fit 20000
```

With `--fit N`, if the default slicing is over N estimated tokens,
GhostSlice progressively downgrades modes down the ladder
`full -> signatures -> interfaces -> exclude` until the bundle fits.
Downgrades are chosen by lowest value density first: files with no
importers in the import graph go before files with importers, then
largest files first, then path order (fully deterministic; the
manifest records a `fit` report with every downgrade). Two protections:
entry points are never auto-excluded (they can be downgraded to
`interfaces` at most), and files whose mode is set by the project
profile (`.ghostslice.json`) or an explicit selection are never
downgraded. If the bundle still cannot fit, it is written anyway, a
warning is printed, and the command exits 1. `ghostslice task` accepts
`--fit` too (its machine-resolved selection modes are downgradable;
profile modes stay protected). `check-budget` is unchanged: it only
reports, it never downgrades.

### Bundle diff (v0.5)

```bash
ghostslice diff ~/bundle-old ~/bundle-new [--json]
```

Per-file mode changes, original/sliced token deltas, added and removed
files, and totals. Exit 0 for any two valid bundles; if either bundle
fails validation, diff reports which one and exits 1.

### Secret guard (v0.4)

```bash
ghostslice secrets ~/my-project        # exit 1 if findings; values redacted
ghostslice scan ~/my-project           # scan output includes a secrets section
ghostslice export ~/my-project -o bundle --exclude-secrets   # force-exclude flagged files
```

Before you hand a bundle to an agent (or paste it anywhere), GhostSlice
checks the files that would be exported for likely secrets: AWS
AKIA/ASIA keys, GitHub `ghp_`/`gho_` tokens, OpenAI/Anthropic `sk-`
keys, Slack tokens, private-key blocks, passwords embedded in URLs,
sensitive-named assignments (`API_TOKEN=...`, `DATABASE_PASSWORD=...`),
and generic high-entropy assignments. `export` and `task` warn loudly
on stderr and list findings as file:line + pattern type, redacted to
the first 4 characters - the secret value itself is never printed in
full. Placeholders do not flag: `example`, `xxx`, `your-key-here`,
`changeme`, `dummy`, `sample`, `fixture`, `${ENV}` references, and
empty values are all treated as benign. Also available as the
dashboard `/api/secrets` endpoint and the MCP `check_secrets` tool.
This is a heuristic guard, not a guarantee: review findings, and do
not treat a clean scan as proof a tree is secret-free.

### Duplicates (v0.4)

`scan` and `graph` report duplicate files: exact duplicates (sha256 of
normalized content) and near-duplicates (line-shingle Jaccard >= 0.85,
only for files with at least 8 distinct lines and 200 normalized
characters, to avoid boilerplate noise). A duplicate copy appears in
prune recommendations with its token cost as the potential saving.

### Report + explain (v0.4)

```bash
ghostslice report ~/my-project -o report.html   # single self-contained HTML file
ghostslice explain ~/my-project src/util.py     # why included/excluded, mode, tokens, graph, flags
```

The report needs no JavaScript and loads no external assets: scan
totals, top files by tokens with heat bars, sliced estimate and cost,
prune recommendations, duplicates, redacted secret findings, and
savings history, all in one file (violet accent #6716f3).

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
# TF-IDF-scored file selection within a sliced-token budget
ghostslice task ~/my-project --task "fix billing payments" --budget 20000 -o /tmp/task-bundle

# git-changed files plus their direct dependencies
ghostslice task ~/my-project --diff -o /tmp/diff-bundle
```

Scoring is TF-IDF (v0.5): term frequency per file (capped at 20 per
keyword) weighted by inverse document frequency across the project, so
a rare keyword in one file outweighs a common word repeated everywhere;
path hits keep a 5x boost, weighted by the same idf. Content matching
is whole-word. Scores are floats. Both forms export a validated bundle
containing only the selection (everything else is recorded as
`exclude` in the manifest), and both accept `--fit` (see Auto-fit).

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
Aider with `--read`), `generic` (adds a lowercase `prompt.md`),
`cursor` (v0.5: adds `prompt.md` plus a `README.txt` explaining how to
paste/attach the bundle in Cursor; meant to live as a `.cursor-context`
directory), and `copilot` (v0.5: adds a `prompt.md` shaped for GitHub
Copilot Chat, one `## File:` section per file with fenced code blocks).
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

### MCP server (v0.3)

```bash
ghostslice mcp    # stdio JSON-RPC, newline-delimited
```

Tools: `scan_project`, `slice_file`, `estimate_cost`, `export_bundle`,
`check_secrets` (v0.4).
Same zero-dependency stdlib pattern as the Ghost Hands MCP server: any
MCP client that can spawn a stdio process can drive GhostSlice.

### More languages (v0.3, v0.5)

Go, Rust, Java, and C# joined Python and TypeScript/JavaScript in
v0.3, with parser-lite `signatures` and `interfaces` modes and test
stripping (Go `TestXxx` functions, Rust `#[test]` / `mod tests`, Java
`@Test`, C# `[Test]` / `[Fact]`).

v0.5 adds PHP, Ruby, Kotlin, and Swift, same parser-lite label:

| Language | signatures / interfaces keep | strip-tests drops |
|---|---|---|
| PHP | functions, classes, interfaces, traits, enums, properties | `test*` methods, `/** @test */` docblock methods, `#[Test]` methods |
| Ruby | `def` signatures, `class`/`module` blocks, `attr_*`, constants | `def test_*`, `describe`/`context`/`it` blocks |
| Kotlin | `fun`, `class`/`interface`/`object`, `val`/`var` | `@Test` functions, `test*` functions |
| Swift | `func`, `class`/`struct`/`protocol`/`enum`/`extension`, `var`/`let` | `test*` XCTest-style functions, `@Test` functions |

Ruby blocks are tracked by keyword/`end` matching (no braces); the
others reuse the string/comment-aware brace matcher. Parser-lite
honesty applies: conventional formatting slices well, exotic syntax
may not.

### Dashboard: visual context tree

```bash
ghostslice serve ~/my-project --port 8765
# open http://127.0.0.1:8765/
```

A single-page local UI (served by the Python process, bound to 127.0.0.1):
files sorted by token cost with a heat bar, click a row to include/exclude
it, a per-file mode selector, live before/after totals, a model selector
with pre-flight dollar cost, a slice preview pane, and an Export button
that writes a `.claude_context` bundle inside the served project. A
Treemap toggle (v0.5) swaps the list for a squarified treemap: nested
rectangles grouped by top-level directory, sized by estimated tokens
and coloured by the same heat palette; clicking a rectangle toggles
include/exclude just like the list. The list stays the default view.

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
  imperfectly. Since v0.4 the brace matching is string/comment aware:
  braces inside `'...'`, `"..."`, and `` `...` `` template literals
  (including `${...}` interpolation and multi-line templates), `//`
  comments, and `/* ... */` comments do not affect depth, and the same
  awareness applies to the Go/Rust/Java/C# lite slicers (with a
  char-literal heuristic so Rust lifetimes like `'a` do not open a
  phantom string). Remaining known limit: braces inside regex literals
  (e.g. `/}/`) and nested backticks inside `${...}` expressions can
  still confuse the counter.
- **Secret scanning is a heuristic guard, not a guarantee** (see
  Secret guard above): it favours not flagging placeholders over
  catching every possible secret shape.

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
  slicer.py     Python ast slicer + TS/JS parser-lite slicer (+ Go/Rust/Java/C# lite in v0.3, PHP/Ruby/Kotlin/Swift lite in v0.5)
  graph.py      import graph + prune recommendations + git changed-files
  secrets_scan.py  secret guard: provider token shapes, assignments, entropy (v0.4)
  duplicates.py exact (sha256) + near (line-shingle Jaccard) duplicates (v0.4)
  report.py     standalone self-contained HTML report (v0.4)
  fit.py        auto-fit budget downgrades for export/task --fit (v0.5)
  bundlediff.py bundle-vs-bundle diff by manifest (v0.5)
  profile.py    .ghostslice.json profile loader
  selection.py  task TF-IDF keyword / git-diff context selection
  ledger.py     .ghostslice-history.jsonl savings ledger
  mcp_server.py stdio MCP server (v0.3)
  pricing.py    local prices.json loader + cost estimator
  exporter.py   bundle builder + validator (presets: claude-code/aider/generic/cursor/copilot)
  server.py     stdlib http.server dashboard API
  dashboard.html  single-page dashboard UI (violet accent #6716f3)
  cli.py        ghostslice command line
prices.json     editable local price table (dated)
```
