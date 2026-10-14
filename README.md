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

## Quickstart

From the root of this checkout, no install step (the export also
starts the savings ledger, `.ghostslice-history.jsonl`, in the
scanned project):

```bash
PYTHONPATH=src python3 -m ghostslice scan .
PYTHONPATH=src python3 -m ghostslice doctor .
PYTHONPATH=src python3 -m ghostslice export . -o /tmp/ghostslice-context --fit 60000
PYTHONPATH=src python3 -m ghostslice check /tmp/ghostslice-context
PYTHONPATH=src python3 -m ghostslice history . --trend
```

Installed instead? Drop the `PYTHONPATH=src python3 -m` prefix and
run the same commands as `ghostslice ...` against any project.

## What's in 1.0

Every command, one line each (details in the deep dives under
[Documentation](#documentation);
`ghostslice <command> --help` is the full reference):

| Command | What it does |
|---|---|
| `ghostslice scan` | Rank a project's files by estimated token cost (top-N table, heat bars, % of total, summary box) |
| `ghostslice graph` | Import graph between project files, plus prune recommendations |
| `ghostslice slice` | Slice one file or a whole tree to a mode (signatures, interfaces, ...) |
| `ghostslice export` | Write an agent context bundle (.claude_context: PROMPT.md, files/, manifest) |
| `ghostslice task` | Task-focused bundle: keyword- or git-diff-selected files only |
| `ghostslice symbols` | List a project's symbols for symbol-level slicing |
| `ghostslice calls` | Python call graph: who calls what, most-called symbols, dead-function candidates |
| `ghostslice diff` | Diff two bundles by manifest: mode changes, token deltas, added/removed files |
| `ghostslice secrets` | Scan a project for likely secrets (values always redacted in output) |
| `ghostslice report` | Write a standalone HTML report for a project |
| `ghostslice explain` | Explain why one file is included/excluded and how it is sliced |
| `ghostslice watch` | Watch a project; rescan on change, optionally re-export the bundle |
| `ghostslice init` | Analyze a project and generate a tuned .ghostslice.json profile |
| `ghostslice lint` | Lint the default export selection for context waste (rules L001-L010) |
| `ghostslice check-budget` | CI gate: exit non-zero if the selected context exceeds a token budget |
| `ghostslice ci` | CI pack: budget + lint + secrets + fit + duplicates in one read-only run |
| `ghostslice check` | Validate a bundle against its manifest |
| `ghostslice history` | Savings-ledger summary and trend analytics for a project |
| `ghostslice calibrate` | Per-language-family token calibration report (raw vs calibrated estimates) |
| `ghostslice cache` | Inspect or clear the per-project content cache (.ghostslice-cache) |
| `ghostslice doctor` | One-screen health check: versions, prices, profile, cache, ledger, plugins, git, workspaces |
| `ghostslice completions` | Print a bash/zsh completion script generated from the live argument parser |
| `ghostslice mcp` | Run the stdio MCP server (JSON-RPC) for agent clients |
| `ghostslice serve` | Serve the local dashboard (scan, slice preview, what-if panel) |
| `ghostslice prices` | Show the local, dated model price table |

## Usage

### Scan: rank files by estimated token cost

```bash
ghostslice scan ~/my-project
ghostslice scan ~/my-project --model claude-sonnet
ghostslice scan ~/my-project --json
```

The text table (v1.0) shows the top 15 files by estimated tokens
(`--top N` to change it) with a heat bar scaled to the largest
file and each file's share of the total; the remaining files
collapse into one summary line, and the output closes with a
summary box (file count, total estimated tokens, largest file,
and the estimated input cost when a model is known). `--json`
output is unchanged.

The scanner respects `.gitignore`, skips built-in junk (`node_modules`,
`.git`, `dist`, build/cache dirs, binary files), and flags test files and
lockfiles separately.

### Slice: keep only the surface

```bash
# one file
ghostslice slice src/app.py --mode signatures -o /tmp/sliced
# a whole tree (mode applies to all slicable languages, see docs/languages.md)
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
| `structure` | (config/data files; docs/commands.md) | (config/data files; docs/commands.md) |

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

Bundle shapes (presets): `claude-code` (the `.claude_context`
bundle above), `aider`, `generic`, `cursor`, `copilot`,
`anthropic-xml`, and `json` — see
[Profiles and CI](docs/profiles.md) for what each one adds.
The remaining deep dives (structure mode for config files,
auto-fit, bundle formats, the secret guard and redaction,
context lint, duplicates, the call graph, task and symbol
selection) live in the [command reference](docs/commands.md).

## Documentation

The landing page is the whole story at a glance; the deep
reference lives under `docs/`:

- [Command reference](docs/commands.md) — every Usage deep dive
  beyond scan, slice, and export: structure mode, auto-fit,
  bundle formats, secret guard, redaction, context lint,
  detection, monorepos, duplicates, reports, the import and
  call graphs, task-focused context, and symbol-level slicing.
- [Profiles and CI](docs/profiles.md) — `.ghostslice.json`,
  the init wizard, the budget gate, and the CI pack.
- [History and calibration](docs/history.md) — the savings
  ledger, history analytics, and the calibration report.
- [Operations](docs/operations.md) — watch mode, the content
  cache, doctor and shell completions, and the MCP server.
- [Dashboard](docs/dashboard.md) — the visual context tree,
  slice preview, what-if panel, and call graph panel.
- [Languages](docs/languages.md) — the parser-lite language
  set (Go, Rust, Java, C#, PHP, Ruby, Kotlin, Swift, C, C++,
  Scala) and its stated limits.
- [Plugins](docs/plugins.md) — teach GhostSlice a new
  language, or replace a built-in slicer, with a plugin file.
- [Reference](docs/reference.md) — the honest labels
  (estimates, prices, parser-lite limits) and the encoding,
  malformed-input, and limits contract.

## Troubleshooting

Run `ghostslice doctor <project>` first: it checks most of the
failure modes below and prints the remedy next to each finding.

- **A command exits 2 with "invalid profile"** — `.ghostslice.json`
  has a field of the wrong shape; the message names the field.
  Fix it, or regenerate the profile with `ghostslice init --force`.
- **"unknown model id"** — the id (from `--model` or the profile)
  is not in the local price table. `ghostslice prices` lists the
  known ids; add yours to `prices.json` if you need another.
- **"cannot load the price table"** — `prices.json` is missing or
  not valid JSON. `ghostslice doctor` still runs in this state
  and reports the exact file; restore or fix it there.
- **A named plugin fails to load and every command refuses** —
  that is deliberate (a half-loaded plugin set never runs). The
  error names the plugin and the reason; fix the file, or remove
  it from the profile's `plugins` list.
- **Bundles or caches show up in `git status`** — add
  `.claude_context/` and `.ghostslice-cache/` to `.gitignore`
  (doctor's git check flags exactly this).
- **History warns about an "estimator mix"** — the ledger holds
  records from before estimator stamping (or from two estimator
  versions). Nothing is broken; totals across versions are not
  directly comparable, and new records are stamped.
- **Numbers look off for one file** — check its encoding:
  UTF-16/UTF-32 files are decoded via their BOM and non-UTF-8
  bytes fall back to Latin-1 (see "Encodings, malformed input,
  and limits"); the manifest records `source_encoding` for
  anything that was not UTF-8.

### Known warnings on this repo

`ghostslice lint .` on the GhostSlice repo itself reports zero
errors and four warnings, each true and each explained:

- **L003, `examples/plugins/lua_slicer.py`** — flagged as a prune
  candidate because no project code imports it. It is the example
  plugin: it is *loaded* by the plugin system, not imported, and
  reachability cannot see the loader. It stays.
- **L007, `examples/completions/ghostslice.bash` / `.zsh`** —
  generated files included at full mode. They are the generated
  completion scripts, shipped as the copyable examples of the
  `completions` command; their whole content is the example.
- **L006, `tests/fixtures/calibration/minified.sample`** — giant
  lines. That is the fixture's job: it is the calibration corpus's
  minified-shape sample, and the warning correctly describes it.

Until v1.0.1 the lint also flagged a duplicated `prices.json`
(repo root + package copy, L004) and its giant lines; the root
copy was removed and the single remaining table pretty-printed,
so those warnings are fixed, not explained. Until v1.0.5 the
list also carried an L001 for this README itself: at 20,198
estimated tokens it was the product's whole manual in one file.
The manual now lives in this landing page plus the deep
reference under `docs/` (see Documentation above), each file
comfortably under the threshold — fixed, not explained, in
the same way.

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests -q   # the full suite
```

(`python -m unittest discover -s tests` also runs and passes,
but it only collects the unittest-style tests; the
pytest-fixture files need pytest.)

## Layout

```
src/ghostslice/
  tokens.py     token estimator (documented method)
  scanner.py    .gitignore-aware project scanner (nested .gitignore support)
  slicer.py     Python ast slicer + TS/JS parser-lite slicer (+ Go/Rust/Java/C# lite in v0.3, PHP/Ruby/Kotlin/Swift lite in v0.5, C/C++/Scala lite in v0.8)
  configslice.py  structure mode for YAML/TOML/JSON/SQL/shell/PowerShell (v0.9): value rule + scanner backstop
  graph.py      import graph + prune recommendations + git changed-files
  callgraph.py  python call graph + dead-function candidates (v0.19)
  secrets_scan.py  secret guard: provider token shapes, assignments, entropy (v0.4)
  duplicates.py exact (sha256) + near (line-shingle Jaccard) duplicates (v0.4)
  detect.py     generated/minified/vendored detection: header markers, estimator line shape, vendor paths/banners (v0.12)
  workspaces.py monorepo detection (npm/pnpm/Cargo/go.work/uv + manifest fallback) and per-package subtotals (v0.13)
  lint.py       context lint rule engine L001-L010 over exporter.resolve_modes (v0.11)
  report.py     standalone self-contained HTML report (v0.4)
  fit.py        auto-fit budget downgrades for export/task --fit (v0.5)
  bundlediff.py bundle-vs-bundle diff by manifest (v0.5)
  profile.py    .ghostslice.json profile loader
  selection.py  task TF-IDF + symbol + graph keyword / git-diff context selection
  entries.py    entry-point candidate signals for init (manifest bin/main/scripts, names, shebangs, __main__ guards) (v0.15)
  init_wizard.py  `ghostslice init`: profile generation with printed evidence per section (v0.15)
  ledger.py     .ghostslice-history.jsonl savings ledger
  mcp_server.py stdio MCP server (v0.3)
  pricing.py    local prices.json loader + cost estimator
  prices.json   the price table itself: local, dated, hand-editable (the only copy; pre-v1.0.1 a duplicate also sat at the repo root)
  exporter.py   bundle builder + validator (presets: claude-code/aider/generic/cursor/copilot/anthropic-xml/json)
  watch.py      polling watch mode: debounced rescan + auto re-export (v0.6)
  plugins.py    user slicer plugins: contract, opt-in loading, containment, failure discipline (v0.23)
  doctor.py     `ghostslice doctor`: environment + project health checks with remedies (v1.0)
  completions.py  bash/zsh completion scripts generated from the live parser (v1.0)
  server.py     stdlib http.server dashboard API
  dashboard.html  single-page dashboard UI (violet accent #6716f3)
  cli.py        ghostslice command line
docs/         the deep reference: commands.md (Usage deep dives), profiles.md (profiles, init, CI gates), history.md (ledger, history analytics, calibration), operations.md (watch, cache, doctor, MCP), dashboard.md, languages.md, plugins.md, reference.md (honest labels, encodings, limits)
examples/plugins/  example user plugins: a parser-lite Lua slicer with outline (v0.23)
examples/completions/  generated bash/zsh completion scripts (regenerate with `ghostslice completions`)
```
