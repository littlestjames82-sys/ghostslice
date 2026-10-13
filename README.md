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
| `structure` | (config/data files, below) | (config/data files, below) |

More modes (v0.4): Markdown files support `headings` (headings plus the
first paragraph under each heading; docs still default to `full`, opt in
per-glob via a profile). Jupyter notebooks (`.ipynb`) slice to a text
rendering: `signatures`/`full` keep code-cell source only (outputs and
execution counts are stripped, markdown cells kept as comments) and
`strip-tests` drops test cells. Malformed notebooks never crash the
slicer.

### Config and data files: `structure` mode (v0.9)

YAML, TOML, JSON, SQL, shell and PowerShell files get a real slicing
story. `structure` keeps a file's shape — key paths, table headers,
DDL, function definitions — and replaces values under the rule below.
`signatures` means the same surface for these languages; `interfaces`
is the values-free variant (SQL: CREATE statements only). Config files
still default to `full` in exports — opt in per-glob via a profile
(`"modes": {"*.yaml": "structure"}`) or with `--mode structure`.

- **YAML**: mapping keys and nesting kept; sequences collapse to one
  rendered exemplar item plus a `… (+N more)` line; flow collections
  render recursively; anchors kept, aliases pass through. Comments
  are kept only in the leading header block or directly above a
  mapping key at the same indent (section headers); trailing
  comments are dropped.
- **TOML**: table headers and dotted keys kept, order preserved;
  multi-line strings and multi-line arrays collapse to one-line
  placeholders; inline tables collapse to `{…}`.
- **JSON**: real parse; key order preserved; arrays render one
  exemplar element plus a `… (N more items)` marker; homogeneous
  maps with more than 20 entries collapse to one exemplar entry.
  Invalid JSON returns the source unchanged.
- **SQL**: CREATE statements are kept in full (they are the schema);
  INSERT collapses to a summary comment with a counted row total
  (INSERT ... SELECT is labelled not countable); other statements
  collapse to a one-line summary. Comments standing between
  statements are preserved.
- **Shell / PowerShell**: function definitions collapse to their
  header line; top-level variable assignments are kept under the
  value rule; the leading comment block is kept. Shell heredoc
  bodies are never parsed as code; PowerShell here-strings are
  placeholdered.

**The value rule** (security is senior to convenience):

1. A value under a sensitive-looking key is ALWAYS replaced by a
   placeholder (`"…"`), whatever its type — a PIN under `password:`
   is a number and still goes. Sensitive = any name segment (split
   on non-alphanumerics and camelCase) in {password, passwd, pass,
   pwd, secret, token, key, auth, credential(s), private, session,
   cookie, bearer, jwt, apikey}, or the name containing "secret",
   "password", "passwd" or "credential" anywhere. So `db_pass`,
   `apiToken`, `client-secret` are sensitive; `monkey`, `tokenizer`
   are not.
2. Numbers, booleans and nulls under other keys are kept.
3. A string under another key is kept only when it is clearly
   enum-like: ≤ 24 chars, a single token of `[A-Za-z0-9._/+:-]`, or
   an env/placeholder reference (`${...}`, `$VAR`); random-looking
   strings (12+ chars mixing upper, lower and digits) are
   placeholdered anyway. Long strings and free text always become
   `"…"` (JSON: `"…(len N)"`).
4. Block scalars, multi-line strings and other free-text constructs
   are placeholdered wholesale.

Every rendering also passes through the v0.4 secret scanner as a
backstop: any output line it still flags has its value replaced.
Structure mode is tested to never leak a planted secret in any of
the six formats.

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

### XML and JSON bundles (v0.16)

Two presets add a single-file rendering of the whole bundle, built
from the same in-memory slice results as `PROMPT.md` (never re-read
or re-sliced), for consumers that do not want the `files/` tree:

```bash
ghostslice export ~/my-project -o bundle --preset anthropic-xml
ghostslice export ~/my-project -o bundle --preset json
```

**`anthropic-xml` → `context.xml`** — one well-formed XML document in
Anthropic's document shape:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<documents>
  <document index="1" mode="signatures" package=""
            original_tokens="120" sliced_tokens="45" sha256="...">
    <source>src/app.py</source>
    <document_content>...sliced text, XML-escaped...</document_content>
  </document>
  <excluded>
    <file path="package-lock.json" mode="exclude" reason="excluded (mode: exclude)"/>
  </excluded>
</documents>
```

Documents appear in manifest order (`index` is 1-based). `package` is
the v0.13 workspace package of the file ("" for the root package).
Every manifest file is either a `<document>` or listed under
`<excluded>` — excluded files (mode `exclude`) and files whose slice
came out empty (e.g. a test file under `strip-tests`), each with its
reason. Content is escaped with Python's ElementTree (never
hand-rolled, never CDATA), so code full of `]]>`, `<`, `>` and `&`
round-trips exactly. The one lossy step: characters XML 1.0 cannot
represent (most C0 controls, lone surrogates) are replaced by U+FFFD
in `context.xml` only — `files/` and `context.json` keep the
canonical bytes.

**`json` → `context.json`** — one JSON object for other tools and
agents:

```json
{
  "tool": "ghostslice", "version": "...", "preset": "json",
  "generated_by": "ghostslice ...", "generated_at": "...",
  "project": "my-project", "root": "/abs/path", "model": "claude-sonnet",
  "token_method": "...",
  "totals": {"original_tokens": 0, "sliced_tokens": 0, "saved_tokens": 0},
  "files": [{"path": "...", "mode": "...", "language": "...",
             "package": "", "original_tokens": 0, "sliced_tokens": 0,
             "sha256": "...", "content": "...sliced text..."}],
  "excluded": [{"path": "...", "mode": "exclude", "reason": "..."}]
}
```

`model` is the export's model id, or `null` when the export was not
made through the CLI. `files` carries exactly the included set (same
files and contents as `PROMPT.md`), in manifest order.

**Wrapper overhead, stated honestly:** the artifact contains the
slices, so pasting it costs its own total, of which only the markup
beyond the slices is overhead. The manifest totals do not count
either figure — totals stay about the file slices, unchanged. The
manifest records the wrapper under `wrapper_artifacts` per
artifact: `bytes`, `estimated_tokens` (the artifact as written,
escaping included), and `overhead_estimated_tokens` (the artifact
estimate minus the sliced total, itself an estimate, clamped at
0). The export/task CLI prints both numbers.

**Validation:** `ghostslice check` validates either artifact when
present — the XML must parse, the JSON must parse, per-file content
must equal the bundle's own sliced bytes (XML compared after the
documented U+FFFD step), per-file and total hashes/totals must match
the manifest. Truncated or tampered artifacts fail with a clear
message. Bundles without an artifact validate exactly as before.

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

### Redact in place (v0.17)

```bash
ghostslice export ~/my-project -o bundle --redact   # keep the files, replace the values
```

`--exclude-secrets` drops a flagged file entirely. `--redact` is the
other remedy: the final sliced text of every included file is scanned
and each flagged value is replaced where it sits with a typed
placeholder, so the file still ships:

```
API_KEY = "[REDACTED:aws-access-key:74355467]"
DB = "postgres://u:[REDACTED:password-in-url:7a078322]@h/db"
password = "[REDACTED:sensitive-assignment]"
```

- The suffix is a fingerprint - the first 8 hex of the value's
  sha256 - so the same secret maps to the same token in every file
  and run, and cross-references stay visible without the value. It
  is only added for values of 12+ characters: an 8-hex fingerprint
  of a short password would be a brute-force oracle, so short values
  get the fingerprintless form.
- A private-key finding replaces the whole PEM block (BEGIN through
  END, or the trailing base64 body when a slice cuts the END line).
- Redaction judges the same kinds the guard reports, in one stricter
  context: comment lines count as content (a Markdown heading is
  `#`-prefixed content, and a real key in a comment must not ship),
  while the reporting commands keep skipping comment lines as
  documentation. Placeholder-shaped examples in comments stay
  untouched, and the placeholder itself never trips the scanner.
- The scan runs on the sliced text, never on pre-slice findings
  (slicing can split or merge lines), so manifest line references
  are slice-relative. Manifest `sliced_tokens`/sha256 describe the
  redacted text - totals are post-redaction - each affected entry
  gains `redactions`/`redaction_kinds`, and the manifest gains a
  `redaction` summary block. `ghostslice check` re-scans any bundle
  whose manifest claims redaction and fails if a reportable literal
  remains. After redaction the text is re-scanned before anything
  is written; a leftover reportable finding fails the export loudly
  instead of shipping.
- With `--exclude-secrets` also on, exclusion wins: flagged files
  are dropped whole and redaction covers the remaining files (the
  CLI prints this). A finding of a kind the redactor does not handle
  would be counted as `left_in_place` in the summary, never shipped
  silently. Set it per project with `"redact": true` in
  `.ghostslice.json`; `--no-redact` overrides the profile for one
  run. `task`, `--fit`, `watch --export`, and the MCP `export_bundle`
  tool accept the same switch. With `--fit`, the ladder judges
  pre-redaction slices; the manifest's fit block then also records
  `redacted_after_tokens`.
- Boundaries, honestly: a secret split across two lines (string
  concatenation) is not one flagged value - the guard has the same
  limit - and the standalone `slice` command and dashboard export do
  not apply redaction.

### Context lint (v0.11)

```bash
ghostslice lint ~/my-project            # exit 1 only on error-severity findings
ghostslice lint ~/my-project --strict   # warnings fail too
ghostslice lint ~/my-project --json     # same payload as /api/lint and MCP lint_project
```

Lint judges the selection an export *would* produce — file modes are
resolved by the exporter's own `resolve_modes`, never a second copy —
and flags context waste before you spend tokens on it. Each finding
has a stable rule id, a severity, the estimated token cost, what
acting on it recovers, and a concrete action:

| Rule | Flags |
|---|---|
| L001 | a file over 20,000 estimated tokens still at full mode |
| L002 | slicable code at full mode whose signatures slice saves >= 60% and >= 2,000 tokens |
| L003 | graph prune candidates (unreachable / no importers) still included |
| L004 | exact / near-duplicate files with more than one copy included |
| L005 | likely secrets in a file slated for inclusion (error severity; metadata only, never values) |
| L006 | giant lines (avg or p95 line length over 400 chars — the minified/compact shape; detection only) |
| L007 | generated-code header markers (`@generated`, "do not edit", ...) at full mode |
| L008 | test files included at full mode |
| L009 | a lockfile not excluded (possible via a profile mode override) |
| L010 | 20+ tiny files (< 10 tokens each) adding manifest noise (info) |

Totals never double-count: flagged tokens union distinct files, and
potential savings take the best saving per file. Tune rules in the
profile's `"lint"` section — per-rule severity (`off`/`info`/`warn`/
`error`) and numeric options (e.g. `"L001": {"threshold_tokens":
5000}`); unknown rule ids, severities, or option names are a loud
error at load, never a silent ignore. Exit codes: 0 clean (or
warnings only), 1 on errors (or warnings with `--strict`), 2 on
config/usage errors. Also on the dashboard as `/api/lint` and as the
MCP `lint_project` tool.

### Detection + auto-shrink (v0.12)

Every scan flags files that look **generated**, **minified**, or
**vendored**, with the evidence attached (`ghostslice scan` shows
`[generated]` / `[minified]` / `[vendored]`; `--json` and the
dashboard's `/api/scan` carry `is_generated` / `is_minified` /
`is_vendored` plus a `detect_evidence` map; `ghostslice explain`
prints them too). Detection lives in one module, `detect.py`, and
is deliberately conservative — a hit needs textual or path
evidence:

- **generated**: a canonical header marker (`@generated`,
  `generated by`, `do not edit`, thrift's `autogenerated by`, ...)
  in the first 15 lines. Evidence is the marker itself.
- **minified**: the token estimator's own line-shape verdict
  (`tokens.looks_minified`, the same judgement that picks the
  minified-js calibration family), judged on the full text.
  Evidence is line statistics, never content.
- **vendored**: an exact `vendor/` / `third_party/` / `extern/`
  path segment, or a `/*! Library vX.Y */` license banner.
  Lookalike directories (`vendors/`, `myvendor/`) never hit.

Prose is out of scope: a README saying "generated by the build"
flags nothing (markdown and notebooks skip the content detectors).

Opt in to acting on the flags with **auto-shrink**:

```bash
ghostslice export ~/my-project -o ~/ctx --auto-shrink
# or, in .ghostslice.json:  "auto_shrink": true
```

Detected files whose mode would come from the built-in defaults
resolve to `exclude`, and the manifest records why per file
(`"mode_reason": "auto: generated (generated by)"`). Explicit
choices always win: task selections, profile `modes`, a CLI
`--mode`, and profile `entry_points` are never auto-excluded.
With `--fit`, auto-shrink applies first and the fit ladder works
on what remains. Default is off — a plain export is byte-identical
to v0.11. Lint rules L006/L007 read the same detectors, so lint,
scan, and export never disagree about what these shapes are.

### Monorepos: per-package subtotals (v0.13)

Scanning a monorepo reports per-package subtotals (files, estimated
tokens, share of the total) in `scan` (text + `--json`), the export
manifest (`"package"` per file plus a top-level `"packages"`
summary with sliced shares), `/api/scan`, and the HTML report.

Package boundaries come from the workspace manifests at the
project root — evidence first, in this order: npm `workspaces`
(array or `{packages: [...]}`, `!` negations honoured),
`pnpm-workspace.yaml`, Cargo `[workspace]` `members`/`exclude`
(exclude cannot remove an explicitly listed member), `go.work`
`use` directives, and `[tool.uv.workspace]` members in
`pyproject.toml`. Members named by such a manifest are kind
**declared**. If no manifest declares members, directories
carrying their own manifest (top level, or one level below, like
`packages/<name>`) are reported as kind **detected** — weaker
evidence, labelled as such. Files outside every package belong to
the root package (labelled `(root)`).

Rules worth knowing: globs match one path segment (`**` counts as
one segment — a documented simplification); glob-matched members
must contain the ecosystem's manifest; declared members missing
on disk and members that would escape the project root (skipped,
with a warning) are listed in `scan` output and in the `--json`
`"workspace"` block. Nested workspaces resolve outermost-first.
Visibility only: selection, modes, and budgets are unchanged —
there are no per-package budgets.

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
they are not. Since v0.19 the scan/graph recommendation lists also
include dead *symbols* (kind `dead-symbol`) from the call graph below.

### Call graph + dead functions (v0.19)

```bash
ghostslice calls ~/my-project                    # most-called symbols (fan-in)
ghostslice calls ~/my-project src/auth.py        # callers/callees per symbol in one file
ghostslice calls ~/my-project --dead             # dead-function candidates
ghostslice calls ~/my-project --json             # full payload: symbols, edges, dead, counts
```

For Python files, GhostSlice builds a symbol-level call graph with the
real `ast`. Every resolved edge is labelled: **exact** (same file,
`self.` or a resolved project base class, or import evidence — aliases
and `module.func()` included), **heuristic** (a bare name matched in
another module with no import evidence), or **attribute**
(`anything.name(...)` fans out to every project method of that name —
deliberately conservative, and `self.`/`cls.` calls also fan out to
subclass overrides, since that is where dispatch can land). References
count as well as calls: a function passed as a callback, stored in a
table, or named in a default is alive. Calling a class counts as
calling its `__init__`.

Dead candidates are callable symbols no root reaches: roots are module
top levels, profile-declared entry points (heuristic entry files root
only a function named `main`), `[project.scripts]` targets, `__all__`
exports, test files and `conftest.py`, framework-decorated functions
(route handlers, pytest fixtures), and methods of classes extending a
non-project base (an `http.server` handler's `do_GET` is invoked by
the base class, not by your code). Dunders are never candidates, files
that do not parse are never judged, and a directly self-recursive
function is alive by rule. Nothing is ever auto-excluded.

The honesty line travels with every candidate — *recommendations to
review, not instructions: dynamic dispatch, getattr, string
registries, and framework callbacks can hide real use*. String-based
dispatch (`getattr(x, "name")`) is invisible by design and such a
function *will* be flagged; that is the known limit, stated rather
than hidden. Import resolution follows the import graph's
root-relative model, plus a unique-suffix fallback for src layouts.

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

#### Task selection v2: symbols + graph (v0.7)

Two more signals layer on top of TF-IDF for `--task`:

- **Symbol matching.** A keyword that names a symbol *defined* in a
  file earns a bonus, because a definition is stronger evidence than
  a body mention (and the body counter never sees it: `render_invoice`
  tokenises as one word, not as "invoice"). An exact symbol-name match
  earns 15.0; a keyword equal to one camelCase/snake_case part of a
  symbol (or whose parts all appear in the symbol) earns 10.0. Each
  keyword scores once per file at its best tier, and the symbol
  component is capped at 25.0 per file. Symbols come from the file
  itself: Python via `ast` (functions, classes, methods, and
  module/class-level assignment targets — constants count as
  definitions; function-local variables do not), other slicable
  languages via the slicer's own signatures output (no second parser).
- **Graph boosting.** After the budget has picked the seed files, a
  file one import hop from a seed (it imports a seed, or a seed
  imports it) earns 25% of the strongest adjacent seed's score,
  capped at 6.0. It is a max, not a sum: a hub imported by everything
  earns no more than a file imported by one seed, so popularity alone
  never drags a file in. Boosts flow only from files actually
  selected, boosted files are taken with whatever budget remains,
  they never displace a seed, and a boost never exceeds the budget
  (the single-best-file guarantee belongs to the seed stage only).

The CLI prints each chosen file's score with its components
(`tfidf / symbol / graph`), and bundle manifests from `task` carry
matching `score` and `score_components` fields per selected file
(additive; other bundles are unchanged).

### Symbol-level slicing (v0.18)

Files are not always the right unit. `ghostslice symbols` lists what
a project defines, and `export --symbols` ships exactly the named
symbols — with their bodies — plus the context needed to read them:

```bash
# what can I ask for? (name, kind, line span, estimated tokens)
ghostslice symbols ~/my-project
ghostslice symbols ~/my-project src/auth.py [--json]

# ship login's body, not the whole auth module
ghostslice export ~/my-project -o /tmp/bundle --symbols "Auth.login, db.connect"
```

A spec is a comma list of entries. Each entry is one of:

- a **bare name** (`login`) — matches that symbol anywhere;
- a **qualified name** (`Auth.login`, C++ `Store::total`) — matches
  the full name or any qualified name *ending* in it (`Store.total`
  reaches `Shop.Store.total`);
- a **file-scoped name** (`db.py:login`, globs allowed:
  `src/*.py:login`) — the part before the `:` must name or glob a
  scanned file, so `Store::total` is never mistaken for scoping;
- a **glob** (`*.render*`, `hash_*`) — fnmatch against qualified and
  bare names.

Semantics, all of them deliberate:

- A file with a requested symbol ships in mode `symbols`: the
  requested symbols **with bodies**, the file's always-context
  (imports; for Python also the module docstring's first line and
  small module constants, mirroring signatures mode), enclosing
  classes as shells, and every other symbol collapsed to its
  signature so the file stays navigable.
- A bare name that matches in several files matches in **all** of
  them. The CLI and the manifest say so (`ambiguous`) — ambiguity is
  reported, never silently resolved to one file.
- An entry that matches **nothing** is a hard error (exit 2) with
  near-miss suggestions, raised before anything is written: a typo
  must not silently export less context.
- Files with no requested symbol are excluded — except profile
  **entry points**, which keep their resolved mode and stay
  included (an entry point is an explicit whole-file signal).
  `--exclude-secrets` still wins over a match (the report gains
  `excluded_by_secrets`); `--redact` composes as usual. `--symbols`
  cannot combine with `--fit` (the ladder downgrades whole files;
  symbol selection narrows within files).
- The manifest gains a top-level `symbols` report (requested,
  per-entry matches, ambiguities, per-file lists) and each
  symbols-mode entry gains `symbols_included`. PROMPT.md sections
  are headed `(mode: symbols: Auth.login, ...)`. MCP
  `export_bundle` takes the same selection as a `symbols` array.

Per-language support. "Body" = a selected symbol ships its full
body; "Collapse" = what a non-selected symbol becomes.

| Language | Outline source | Body | Collapse |
|---|---|---|---|
| python | `ast` (exact: nested defs, methods, constants, class attributes, conditional defs) | full | signatures rules (the signatures renderers themselves) |
| typescript, javascript | parser-lite spans | full | signature line; interfaces/types/enums kept whole |
| go | parser-lite spans | full | signature line; struct/interface kept whole |
| rust | parser-lite spans (impl blocks) | full | signature line; struct/enum/trait/union kept whole |
| java, csharp | parser-lite spans | full | signature line; interface/enum/record kept whole |
| php, kotlin, swift | parser-lite spans | full | signature line; interface/trait/protocol kept whole |
| c, cpp | parser-lite spans (qualified names) | full | signature line; struct/enum kept whole |
| scala | parser-lite spans | full | signature line; trait/enum kept whole |
| ruby | parser-lite spans (keyword/`end`) | full | the `def` line |
| notebook, markdown, config/data, text | **no outline** | — | — |

Declaration types are surface: selecting a *method of* an
interface/trait/protocol ships the whole type, exactly as
signatures mode treats it. Lite limits, stated plainly: nested
functions are outlined only for Python (lite outlines are
top-level definitions plus class members); constructors are not
selectable in lite languages; C# namespaces do not prefix
qualified names; Go grouped `type ( ... )` declarations are not
outlined; a C++ out-of-line definition (`int Store::total() { }`)
is its own symbol, spelled as written, separate from the in-class
declaration it implements.

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
directory), `copilot` (v0.5: adds a `prompt.md` shaped for GitHub
Copilot Chat, one `## File:` section per file with fenced code blocks),
`anthropic-xml` (v0.16: adds `context.xml`, an Anthropic-style XML
document of the slices), and `json` (v0.16: adds `context.json`, a
machine-consumable JSON object of the slices). See
"XML and JSON bundles" below for both schemas.
Nested `.gitignore` files in subdirectories are honoured, scoped to
their subtree. An optional `"lint"` section tunes the context linter
per rule (see Context lint above), `"auto_shrink": true` makes
exports exclude detected generated/vendored/minified files (see
Detection + auto-shrink above), and `"redact": true` makes exports
replace flagged secret values in place (see Redact in place above).

### Init: generate a tuned profile (v0.15)

```bash
ghostslice init ~/my-project                 # interactive on a TTY, --yes otherwise
ghostslice init ~/my-project --dry-run       # print the profile + evidence, write nothing
ghostslice init ~/my-project --budget 80000 --model claude-sonnet
```

`init` analyses the project with the tool's own engines (scan, the
import graph, detect.py flags, the context linter) and writes a
`.ghostslice.json` where every section carries a printed
justification:

- **entry_points**: the top candidates (cap 5), ranked by signal —
  a package.json `"bin"` entry or a pyproject `[project.scripts]`
  entry (+60), package.json `"main"` (+50), the entry-name heuristic
  shared with the prune engine (+40), a Python
  `if __name__ == "__main__"` guard (+35), a shebang (+25), and
  "nothing imports it" (+10, tie-breaker only). Test files and
  vendored/generated files are never nominated: a false entry point
  is worse than a missing one, because exports protect entry points
  from auto-shrink and fit downgrades.
- **ignore**: directory trees whose files are all flagged vendored
  by path. **modes**: directories whose files are all flagged
  generated get `"exclude"`; config-heavy directories (≥70%
  config/data files, ≥3 files, ≥500 estimated tokens) get
  `"structure"`. Docs and tests are deliberately not pinned — the
  built-in defaults already handle them.
- **budget_tokens**: your `--budget`, or the current default-sliced
  total × 1.25 rounded up to two significant figures, so
  `check-budget` catches growth. Projects slicing under 5,000 tokens
  get no budget (it would be noise) — the omission is printed, with
  the number. **model** is written only from `--model`; init never
  invents one. No `"lint"` section is written in this version: lint
  stays at its defaults rather than freezing today's findings into
  config.

Safety: an existing `.ghostslice.json` is refused (exit 2, with a
summary of what's in it) unless `--force` is given; `--dry-run`
writes nothing at all; the written file is loaded back through the
real profile loader before init reports success. On a TTY you are
asked per section (entry points, file rules, budget) with the
analysis as the default; piped stdin behaves as `--yes` and says so.
The output ends with the top 3 "biggest wins" from the analysis and
the linter — guidance only; init changes nothing but the profile.

### Budget gate for CI (v0.2)

```bash
ghostslice check-budget ~/my-project --max-tokens 50000   # or profile budget_tokens
echo $?   # 1 when the selected (sliced) context exceeds the budget
```

### Savings ledger (v0.2)

Every export appends one line to `.ghostslice-history.jsonl` in the
project (scanner-ignored). `ghostslice history ~/my-project` and the
dashboard total the estimated savings across runs.

### History analytics (v0.14)

```bash
ghostslice history ~/my-project                 # plain totals (unchanged)
ghostslice history ~/my-project --trend         # per-run table + charts
ghostslice history ~/my-project --trend --model claude-opus
ghostslice history ~/my-project --json          # full analytics payload
```

`--trend` prints each run oldest first (before → after, saved,
saved %, the change in after-tokens versus the previous run, and
estimated $ saved per run and cumulative), then aggregates: mean /
median saved %, best and worst runs, the first→last change in
context size, the span (weekly run rate only when the history spans
at least a day), and ASCII sparklines of saved and after tokens
across runs. Dollar figures use the model's **input** rate from the
local prices snapshot (context is input tokens) and are labelled
with its date: "prices as of …, local snapshot, not live".

The JSON payload keeps the summary keys (`runs`,
`total_before_tokens`, `total_after_tokens`, `total_saved_tokens`,
`records`) and adds `runs_detail` (per-run saved %, deltas,
cumulative tokens and $), `aggregates`, `charts` (the sparklines),
`corrupt_lines`, an `estimator` block, and a `model` block when
priced. The dashboard's `/api/history` returns the same payload.
The HTML report embeds a savings-history chart (inline SVG bars for
saved tokens, a line for after tokens) whenever the project has a
ledger, and omits the section when it has none.

**Estimator versions, honestly:** records written from v0.14 on are
stamped with the estimator version that produced their totals
(`"estimator": "v2"`, the calibrated method). Older records carry
no stamp, and pre-v0.10 (v1) totals cannot be told apart from
v0.10–v0.13 (v2) totals — so any history that is not uniformly one
stamped version is flagged with an "Estimator mix" warning instead
of being trended as if its totals were directly comparable.
Corrupt ledger lines (bad JSON, non-object, non-numeric token
fields) are skipped and counted, never fatal.

### Calibration report (v0.10)

```bash
ghostslice calibrate ~/my-project [--json]
```

Per language family present: file count, characters, the raw
(uncalibrated) estimate, the calibrated estimate every other command
uses, the implied characters-per-token, and the factor and target
behind it. This is the transparency surface for the estimator: if a
total looks surprising, `calibrate` shows exactly which family and
factor produced it. See the token bullet under Honest labels for the
evidence basis and the v0.9 -> v0.10 totals-shift note.

### Watch mode (v0.6)

```bash
ghostslice watch ~/my-project                                  # report changes + estimated-token deltas
ghostslice watch ~/my-project --export                         # also rewrite .claude_context on every settled change
ghostslice watch ~/my-project -o /tmp/ctx --interval 2 --fit 20000 --exclude-secrets
ghostslice watch ~/my-project --once                           # snapshot, poll once, report, exit (scripting)
```

Polling watcher (stdlib only, no watchdog dependency). It snapshots
the scanned files every `--interval` seconds (default 1) and reports
a compact delta (files added/removed/changed, estimated tokens
before -> after) once the tree has stayed quiet for the debounce
window (default: the larger of 1s and 2 poll cycles; `--debounce 0`
settles on the first differing poll), so editor/build bursts coalesce
into one event. With `--export` (or `-o`, which implies it) the
bundle is written at startup and after every settled change, exactly
like `ghostslice export`: profile, `--preset`, `--mode`, `--fit`, and
`--exclude-secrets` all apply, each settled export appends at most
one ledger record (one per settled export in normal operation), and
an unfittable or invalid bundle is reported without stopping the
watcher. Watch-written bundles also exclude the bundle directory
itself from their contents when it lives inside the project.

The watcher is loop-proof: the bundle directory (when inside the
project) is excluded from its own change detection and the ledger is
scanner-ignored, so its own writes never trigger events. The bundle
output may not be the project root itself (rejected with exit 2).
With a custom bundle name inside the project, plain scans can still
see a previous bundle's files; prefer the default `.claude_context`
name (scanner-ignored) or a path outside the project. The profile is
loaded once at startup; edit `.ghostslice.json` and restart the watch
to apply it. `--max-events N` exits after N settled events. Ctrl-C
exits 0 with a session summary (duration, polls, events, exports).

### Performance: the content cache (v0.20)

Repeat runs are fast because GhostSlice memoizes its own pure
derivations on disk, in `<project>/.ghostslice-cache/`:

```bash
ghostslice export ~/my-project -o /tmp/ctx --timing   # phase breakdown + cache counters
ghostslice scan ~/my-project --timing                 # scan phase vs analysis, cache counters
ghostslice cache stats ~/my-project                   # entries, bytes, age by kind
ghostslice cache clear ~/my-project                   # delete it (derived data; rebuilds on demand)
ghostslice export ~/my-project -o /tmp/ctx --no-cache # bypass the cache for one run
GHOSTSLICE_NO_CACHE=1 ghostslice export ...           # or disable it entirely
```

What is cached: per-file scan derivations (token estimate, line
count, detection evidence), slice results (text + token counts),
symbol outlines, and symbol-slice renders. Every entry is keyed
by the sha256 of *all* its inputs — the file's content hash, its
relative path, the slice mode (or sorted symbol keep-set), the
GhostSlice version, and the token-estimator version — so a hit is
the same result the code would have computed, and bundles are
byte-identical with the cache off, cold, or warm (the test suite
diffs whole bundle trees to prove it). A changed file misses
exactly its own entries; a GhostSlice or estimator upgrade moves
the version dimensions and simply misses. Entries are written
atomically (temp file + rename), a corrupt entry counts and reads
as a miss, and a 256 MiB cap evicts oldest-first.

Measured warmups (local, this dev sandbox, medians; see
BENCHMARKS.md for method and caveats): a 2,000-file tree exports
in ~0.65s warm vs ~4.4s cold; this repo exports in ~0.09s warm vs
~2.6s cold. Parallel slicing (`--workers N`) is available and
deterministic, but measured *no faster* for this workload (the
work is regex/AST under the GIL), so it defaults to 1 — the cache
is the win, not thread count.

Trust model, plainly: the cache is trusted derived data, like
ccache's store. Nothing in it is trusted for a security decision
(secret scanning and redaction always run on the final text,
cached or not), but a hand-forged entry would change output —
`cache clear` or GHOSTSLICE_NO_CACHE if that ever matters. The
cache directory is scanner-ignored (never scanned, exported, or
watched); add `.ghostslice-cache/` to your `.gitignore` — it is
regenerable. Estimator changes must bump the estimator version
stamp (`tokens.METHOD_VERSION`) so old entries miss, which is
the same discipline the savings ledger already uses.

### MCP server (v0.3)

```bash
ghostslice mcp    # stdio JSON-RPC, newline-delimited
```

Tools: `scan_project`, `slice_file`, `estimate_cost`, `export_bundle`,
`check_secrets` (v0.4), `lint_project` (v0.11).
Same zero-dependency stdlib pattern as the Ghost Hands MCP server: any
MCP client that can spawn a stdio process can drive GhostSlice.

### More languages (v0.3, v0.5, v0.8)

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

v0.8 adds C, C++, and Scala, same parser-lite label:

| Language | signatures / interfaces keep | strip-tests drops |
|---|---|---|
| C | `#include` and other preprocessor lines, function signatures/prototypes, struct/union/enum blocks, typedefs | `test_*` / `testXxx` functions |
| C++ | the C surface plus classes (member signatures), namespaces, templates, enum class | gtest `TEST`/`TEST_F`/`TEST_P` blocks, `test_*` functions |
| Scala | `def` signatures, `val`/`var`, class/object declarations, trait/enum in full | `@Test` defs, `test_*` defs, `test("...") { }` blocks |

C details: interfaces mode keeps the type surface (struct/union/
enum/typedef, preprocessor) and drops free functions; a `.h` header
of prototypes barely shrinks in signatures mode, which is correct —
it is already all surface. `.h` is treated as C by convention (C++
headers use `.hpp`/`.hh`); a C++ class in a `.h` file slices by the
C rules and loses its class context. The brace matcher now also
skips preprocessor lines (macro braces cannot corrupt it), consumes
C++ raw strings whole, and treats `1'000'000` digit separators and
`'{'` char literals correctly. C++ out-of-line definitions
(`int Store::total() const`) and constructor initializer lists are
supported. Scala details: block comments nest, triple-quoted
strings and `s"..."` interpolation are honoured, and Scala 3
significant-indentation bodies are handled by an indentation
fallback that degrades to keeping more (an indented trait is kept
in full), never less. Known lite limits for the three: K&R
parameter declarations (read as a prototype), one-line class
bodies, `extern "C"` wrappers, C++ concepts/requires clauses,
Scala `given` instances and extension methods.

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

- **Token counts are estimates.** Method (v2, since v0.10): a BPE-like
  split (word and punctuation chunks count as 1 token up to 4
  characters, then 1 token per 4 characters; whitespace is not counted
  separately), multiplied by a per-language-family calibration factor.
  The raw split over-counts versus published tokenizer behaviour (it
  charges full price for substrings real BPE merges), so each family's
  factor brings the estimator's implied characters-per-token on the
  golden corpora in `tests/fixtures/calibration/` onto a published
  anchor: ~4 chars/token for English prose (OpenAI's published rule
  of thumb), with code/data families set denser as documented
  approximations in `src/ghostslice/tokens.py`. It is still not any
  model's exact tokenizer. Run `ghostslice calibrate <project>` to see
  raw vs calibrated totals per family on your own tree.
  **Migration note:** v0.10 totals are lower than v0.9 totals for
  calibrated families (the GhostBus demo moved 165,052 -> 129,555
  original and 53,339 -> 45,770 sliced estimated tokens). Old bundles
  remain valid and name the old method in their manifest; budgets set
  with `check-budget` or a profile under v0.9 compare against
  calibrated totals from v0.10 on, so re-check them once.
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
  exporter.py   bundle builder + validator (presets: claude-code/aider/generic/cursor/copilot/anthropic-xml/json)
  watch.py      polling watch mode: debounced rescan + auto re-export (v0.6)
  server.py     stdlib http.server dashboard API
  dashboard.html  single-page dashboard UI (violet accent #6716f3)
  cli.py        ghostslice command line
prices.json     editable local price table (dated)
```
