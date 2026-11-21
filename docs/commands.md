# Command reference

Part of the [GhostSlice README](../README.md). Every Usage deep dive that is not one of the landing page's flagship three (scan, slice, export).

## Config and data files: `structure` mode (v0.9)

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

## Auto-fit: force a bundle into a token budget (v0.5)

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

## Bundle diff (v0.5)

```bash
ghostslice diff ~/bundle-old ~/bundle-new [--json]
```

Per-file mode changes, original/sliced token deltas, added and removed
files, and totals. Exit 0 for any two valid bundles; if either bundle
fails validation, diff reports which one and exits 1.

## XML and JSON bundles (v0.16)

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

## Secret guard (v0.4)

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

## Redact in place (v0.17)

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

## Context lint (v0.11)

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

## Detection + auto-shrink (v0.12)

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

## Monorepos: per-package subtotals (v0.13)

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

## Duplicates (v0.4)

`scan` and `graph` report duplicate files: exact duplicates (sha256 of
normalized content) and near-duplicates (line-shingle Jaccard >= 0.85,
only for files with at least 8 distinct lines and 200 normalized
characters, to avoid boilerplate noise). A duplicate copy appears in
prune recommendations with its token cost as the potential saving.
The 200-character floor is a profile setting (v1.0.2):
`"duplicates": {"near_min_chars": N}` in `.ghostslice.json` lowers
it to compare smaller files or raises it to skip more boilerplate;
unset, every surface uses the default above.

## Report + explain (v0.4)

```bash
ghostslice report ~/my-project -o report.html   # single self-contained HTML file
ghostslice explain ~/my-project src/util.py     # why included/excluded, mode, tokens, graph, flags
```

The report needs no JavaScript and loads no external assets: scan
totals, top files by tokens with heat bars, sliced estimate and cost,
prune recommendations, duplicates, redacted secret findings, and
savings history, all in one file (violet accent #6716f3).

## Graph: dependency map + prune recommendations (v0.2)

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
Since v1.0.3 the graph command uses the persistent content cache like
scan, lint, and calls (`--no-cache` opts out); its output is identical
cached or not.

## Call graph + dead functions (v0.19)

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

## Task-focused context (v0.2)

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

### Task selection v2: symbols + graph (v0.7)

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

## Symbol-level slicing (v0.18)

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
| php, kotlin, swift | parser-lite spans | full | signature line; declaration types kept whole |
| c, cpp | parser-lite spans (qualified names) | full | signature line; struct/enum kept whole |
| scala | parser-lite spans | full | signature line; trait/enum kept whole |
| ruby | parser-lite spans (keyword/`end`) | full | the `def` line |
| notebook, markdown, config/data, text | **no outline** | — | — |

Declaration types are surface: selecting a *method of* an
interface/trait/protocol ships the whole type, exactly as
signatures mode treats it. Go and Rust generics are handled:
generic functions, methods on generic receivers (attributed to
the base type, e.g. `Stack.Push` for `*Stack[T]`), generic
interfaces, impl blocks with nested generic bounds, and impl
blocks whose brace follows a multi-line `where` clause (v1.0.4),
and Rust type declarations with multi-line `where` clauses,
whose trait methods enumerate like any other trait's (v1.0.5).
Lite limits, stated plainly: nested functions are outlined only
for Python (lite outlines are top-level definitions plus class
members); constructors are not selectable in lite languages —
one exception: Kotlin primary-constructor properties (`val` /
`var` parameters, in data classes and plain classes alike) ARE
symbols of their class as of v1.0.6, because Kotlin makes them
members; a constructor parameter without `val`/`var` is not a
member and stays unlisted. Their spans sit on the class head, so
a slice ships them exactly once, with the head; C#
namespaces do not prefix qualified names; C# records enumerate
their members like classes, expression-bodied methods are
recognised, and Allman-brace declarations (the C# default:
brace on its own line) outline with their true spans in Java
and C# (all v1.0.5); Go grouped
`type ( ... )` declarations are not outlined; a C++ out-of-line definition (`int Store::total() { }`)
is its own symbol, spelled as written, separate from the in-class
declaration it implements.
