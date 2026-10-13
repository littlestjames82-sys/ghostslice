# Changelog

All notable changes to GhostSlice. Versions follow the build waves;
token counts are estimates everywhere (see README).

## [0.12.0] - 2026-10-13
### Added
- Detection module (`detect.py`): generated / minified / vendored
  detectors returning (hit, evidence) — evidence is metadata only
  (a canonical marker, a path segment, line statistics, a library
  banner name), never file content. Generated = canonical header
  markers in the first 15 lines; minified = the token estimator's
  own `looks_minified` verdict, judged on the full text (audit
  G07 F1: head-only judging flipped the verdict on hand-written
  code with a dense opening block); vendored = an exact `vendor/`
  / `third_party/` / `extern/` path segment or a `/*! ... */`
  library banner. Markdown and notebooks are out of scope for the
  content detectors; lookalike directories never hit.
- Scanner flags: every `FileEntry` gains `is_generated`,
  `is_minified`, `is_vendored`, and `detect_evidence`, surfaced in
  `scan` text (`[generated]` etc.), `scan --json`, `/api/scan`,
  and `ghostslice explain`.
- Auto-shrink (opt-in, default off): profile `"auto_shrink": true`
  or `export --auto-shrink` (also on `watch --export`) excludes
  detected files whose mode would come from the built-in defaults;
  the manifest records `"mode_reason": "auto: <kind> (<evidence>)"`
  per affected file. Explicit selections, profile modes, a CLI
  `--mode`, and profile entry points always win. With `--fit`,
  auto-shrink resolves first and the ladder works on the rest.
### Changed
- Lint L006/L007 consume `detect.py` (shared `line_stats` and the
  generated-marker list) instead of private copies. L007's header
  window is now 15 lines and markdown/notebook files no longer
  fire it (prose scope); all v0.11 fixture outcomes are unchanged.
- GhostBus verification: export totals with auto-shrink off are
  unchanged (129,555 -> 45,770 estimated tokens); with it on, one
  compact example JSON is excluded (129,555 -> 45,612). No
  hand-written file is flagged on either GhostBus or this repo.

## [0.11.0] - 2026-10-13
### Added
- Context lint (`ghostslice lint`, new module `lint.py`): a rule
  engine that flags context waste in the selection an export would
  produce. Ten rules with stable ids — L001 oversize file at full
  mode (>20,000 estimated tokens), L002 full-mode slicable code
  (signatures save >= 60% and >= 2,000), L003 graph prune
  candidates still included, L004 duplicate copies both included,
  L005 secrets slated for inclusion (error severity, metadata
  only), L006 giant lines (avg/p95 over 400 chars, detection
  only), L007 generated-code header markers at full, L008 test
  files at full, L009 lockfiles not excluded, L010 tiny-file
  manifest noise (info). Every finding carries the estimated
  token cost, the recoverable saving, and a concrete action;
  totals union distinct files and take the best saving per file,
  so overlapping rules never double-count.
- Lint surfaces: CLI text + `--json`, dashboard `/api/lint`, and
  the MCP `lint_project` tool all return the same payload.
  Exit codes: 1 only on error-severity findings by default;
  `--strict` promotes warnings to failure; 2 on config/usage
  errors.
- Profile `"lint"` section: per-rule severity override
  (off/info/warn/error) and numeric threshold options. Unknown
  rule ids, severities, and option names are a loud load error.
### Changed
- Exporter mode resolution extracted into `exporter.resolve_modes`
  and shared by `build_bundle`, `estimate_context_tokens`, and
  the linter, so lint can never drift from what an export would
  do (pinned by a manifest-parity test). No behaviour change for
  valid profiles; an unknown profile mode now raises the same
  ValueError in `estimate_context_tokens` that bundles always did.

## [0.10.0] - 2026-10-13
### Added
- Estimator calibration (method v2): the BPE-like raw split is now
  multiplied by a per-language-family factor (tokens.py carries the
  table with its evidence basis). Factors were derived by measuring
  the raw split's implied characters-per-token on new golden corpora
  (tests/fixtures/calibration/, one sample per family: Python,
  TypeScript, Go, Rust, C, Markdown prose, JSON data, minified JS)
  and scaling each family onto a published-anchor target rate
  (OpenAI's published ~4 chars/token for English text anchors prose;
  code/data targets are documented approximations set denser than
  the anchor). New `ghostslice calibrate <project>` report shows
  raw vs calibrated totals, implied chars/token, factor and target
  per family, in text and --json.
- Carried parent finding P0 (from G4): the config slicer's scanner
  backstop now builds rewritten lines as original-indent + body by
  construction (and keeps a leading `- ` sequence marker), pinned
  by regression tests asserting nested backstop-only, value-rule
  and key-rule placeholder lines keep their indentation.
### Changed
- Token totals shift DOWN versus v0.9 for calibrated families
  (all factors are <= 1; the raw split over-counted). GhostBus
  demo: 165,052 -> 129,555 original, 53,339 -> 45,770 sliced
  estimated tokens on the unchanged tree. Manifests now record
  the method as "estimates (BPE-like split v2, per-language
  calibrated, not exact tokenizer counts)"; scan JSON, dashboard
  and MCP report the same string from one source. Old bundles
  remain valid. `check-budget` and profile budgets compare
  against calibrated totals from this version on: re-check any
  budget tuned under v0.9.

## [0.9.0] - 2026-10-13
### Added
- `structure` mode for config/data files (new module
  `configslice.py`): YAML, TOML and JSON render their key shape
  with values under a documented value rule; SQL keeps CREATE
  statements in full and collapses INSERT/other statements to
  summary comments (INSERT row counts counted, INSERT ... SELECT
  labelled not countable); shell and PowerShell `signatures`
  collapse function definitions and keep top-level assignments
  under the same rule. `interfaces` is the values-free variant
  (SQL: CREATE only). Config files still default to `full`;
  structure is opt-in via profile or `--mode`.
- The value rule: a value under a sensitive-looking key (segment
  match: password/passwd/pass/pwd/secret/token/key/auth/
  credential/private/session/cookie/bearer/jwt/apikey, plus
  substring rules) is ALWAYS placeholdered, numbers included.
  Numbers/booleans/nulls and short enum-like strings are kept
  under other keys; long/free-text values and block scalars are
  placeholdered wholesale. Every rendering is re-checked by the
  secret scanner as a backstop (flagged output lines lose their
  value portion).
- YAML sequences collapse to one exemplar plus a count (a
  sequence under a sensitive key collapses wholesale); JSON
  arrays likewise, and homogeneous JSON maps over 20 entries
  collapse to one exemplar entry.
- Scanner language names for the new types (yaml, toml, sql,
  shell, powershell — previously generic "text"; file set and
  token counts unchanged), the `slice` CLI applies modes to them,
  fit's rung table knows `structure`, the dashboard mode dropdown
  offers `structure`/`headings`, and YAML/TOML/JSON top-level
  keys now serve as task-selection symbols.
### Notes
- Audit: audits/G04_audit.md (two improve rounds). Round 1 fixed
  two CRITICAL leaks (indentless YAML sequences under sensitive
  keys rendered verbatim; one-line shell/PowerShell functions
  kept bodies that could hold assignment-shaped secrets) plus a
  sensitive-parent sequence rule, blank-line list collapsing,
  and TOML trailing-comment corruption. Round 2 fixed a
  PowerShell here-string variant and flow-style YAML list items.
- GhostBus demo unchanged: 165,052 -> 53,339 estimated tokens.

## [0.8.0] - 2026-10-13
### Added
- C, C++, and Scala parser-lite slicers (signatures, interfaces,
  strip-tests), wired through the scanner language map and
  test-file detection, export defaults, the `slice` CLI, and the
  task-selection symbol fallback (symbols are read from the
  slicers' own signatures output, as for the other lite languages).
  - C: preprocessor lines are surface in both reducing modes;
    struct/union/enum blocks and typedefs are kept as declaration
    surface; function definitions collapse to their signature,
    prototypes are kept as-is (a header of prototypes barely
    shrinks in signatures mode — pinned by a test). strip-tests
    drops `test_*`/`testXxx` functions.
  - C++: classes reduced to member signatures, namespaces
    recursed, single-line template heads (standalone or inline),
    enum class blocks, typedef/using kept; out-of-line definitions
    (`int Store::total() const`), constructor initializer lists,
    and split declarations (`= 0;` / attributes / trailing returns
    on following lines) supported. strip-tests also drops gtest
    `TEST`/`TEST_F`/`TEST_P` blocks. `.h` is C by convention;
    C++ headers are `.hpp`/`.hh`.
  - Scala: def/val/var signatures, class/object reduced to member
    signatures, trait/enum kept in full; Scala 3 significant-
    indentation bodies handled by an indentation fallback that
    keeps more rather than less (an indented trait is kept whole).
    strip-tests drops `@Test` defs, `test_*` defs, and
    `test("...") { }` blocks.
- The shared brace matcher gained language-gated awareness:
  C/C++ preprocessor lines and their backslash continuations are
  never brace-counted, C++ raw strings `R"delim(...)delim"` are
  consumed whole, `'` digit separators (1'000'000) do not open
  char literals, Scala block comments nest, and Scala
  triple-quoted strings and `s"..."` interpolation are honoured.
### Notes
- Audit: audits/G03_audit.md (two improve rounds). The round-1
  headline was a CRITICAL head-detection miss: qualified
  (`Store::total`) and pointer-attached (`char *get_name`)
  function names matched nothing, so out-of-line definitions
  vanished and their bodies leaked; also fixed comment-blind
  declaration scans and split declarations. Known lite limits
  (documented in README): K&R parameter declarations are read as
  prototypes, one-line class bodies lose their members,
  `extern "C"` wrappers, C++ concepts/requires, Scala `given`
  instances and extension methods.

## [0.7.0] - 2026-10-13
### Added
- Task selection v2 for `ghostslice task --task`: symbol-name
  matching and one-hop import-graph boosting layered on the v0.5
  TF-IDF score. A keyword equal to a whole symbol name defined in a
  file earns 15.0; a keyword equal to one camelCase/snake_case part
  of a symbol earns 10.0; the per-file symbol component is capped
  at 25.0. Symbols: Python via `ast` (defs/classes/methods plus
  module- and class-level assignment targets; the slicer's fallback
  def lines for unparseable files), other slicable languages via
  the slicer's own signatures output.
- Graph boosting: a file one import hop from a selected seed earns
  25% of the strongest adjacent seed's base score, capped at 6.0 —
  a max, not a sum, so a popular hub is not dragged in by its
  importer count. Boosted files use only the budget that remains
  and never displace a seed or exceed the budget.
- Score breakdown exposed: the `task` CLI prints per-file
  tfidf/symbol/graph components, and task bundle manifests carry
  additive `score` and `score_components` fields on selected
  files. `select_for_task` keeps its legacy return shape.
### Notes
- Symbol extraction is gated: when no keyword part appears in a
  file's text, its symbol component is provably 0 and extraction
  is skipped (no behaviour change, faster scans).
- Audit: audits/G02_audit.md (build adopted from a recovered
  session; two improvement rounds: constants as symbols + the
  extraction gate, then gate-parts precomputation).

## [0.6.0] - 2026-10-13
### Added
- Watch mode: `ghostslice watch <project>` — stdlib polling watcher
  (no new dependencies). Snapshots scanned files (mtime/size/estimated
  tokens) every `--interval` seconds (default 1) and, after a debounce
  quiet window (default the larger of 1s and 2 poll cycles;
  `--debounce 0` settles immediately), prints a compact delta:
  added/removed/changed files and estimated-token totals before ->
  after. Editor/build bursts coalesce into one settled event.
- `--export` / `-o <bundle>` (implies export): bundle written at
  startup and after every settled change via the same build_bundle
  path as `export` (profile, `--preset`, `--mode`, `--fit`,
  `--exclude-secrets` honoured; exactly one savings-ledger record per
  settled export; an unfittable/invalid bundle is reported and the
  watcher keeps running).
- Loop-proofing: the bundle directory inside the project is excluded
  from the watcher's own change detection, and the ledger file is
  scanner-ignored, so watch writes never trigger events. The bundle
  output directory may not be the project root itself (exit 2).
- Scripting exits: `--once` (one snapshot-compare poll, then exit)
  and `--max-events N`. Ctrl-C exits 0 with a session summary
  (duration, polls, change events, exports written). Watching a path
  that does not exist exits 2; a project deleted mid-watch is
  reported per-poll and the session keeps its last snapshot.

## [0.5.0] - 2026-10-13
### Added
- Auto-fit budget export: `ghostslice export --fit N` (and `task
  --fit N`) progressively downgrades modes down the ladder
  full -> signatures -> interfaces -> exclude until the bundle fits N
  estimated tokens. Downgrade order is deterministic (lowest value
  density: no-importer files first, then largest, then path). Entry
  points are never auto-excluded; profile-moded and explicitly
  selected files are never downgraded. The manifest records a `fit`
  report. If the bundle cannot fit, it is still written, a warning is
  printed, and the exit code is 1. `check-budget` semantics unchanged.
- PHP, Ruby, Kotlin, and Swift slicers (parser-lite): `signatures`
  and `interfaces` modes plus test stripping (PHP `test*` /
  `/** @test */` / `#[Test]` methods, Ruby `def test_*` and
  describe/it blocks, Kotlin `@Test` / `test*` functions, Swift
  `test*` XCTest functions and `@Test`). Wired into the scanner
  language map, export defaults, the `slice` CLI, and test-file
  detection (`StoreTest.php`, `StoreTests.swift`, `*_test.rb`, ...;
  `latest.php` is not a test file).
- Bundle diff: `ghostslice diff <bundleA> <bundleB> [--json]` —
  per-file mode changes, original/sliced token deltas, added/removed
  files, totals. Exit 0 for any two valid bundles; exit 1 when either
  bundle fails validation, naming which.
- Export presets `cursor` (prompt.md + README.txt explaining
  paste/attach usage in Cursor) and `copilot` (prompt.md shaped for
  Copilot Chat with `## File:` sections and fenced code blocks).
  Existing presets unchanged; MCP `export_bundle` preset enum follows
  the profile PRESETS list.
- Dashboard treemap view: a List/Treemap toggle (list stays default).
  Squarified treemap grouped by top-level directory, rectangles sized
  by estimated tokens, coloured with the existing heat palette, click
  toggles include/exclude, tooltip shows path + tokens. Vanilla JS,
  no external assets; the dashboard API is unchanged.
### Changed
- Task keyword selection is now TF-IDF (stdlib): term frequency
  (capped at 20 per keyword per file) weighted by smoothed inverse
  document frequency across the project's files; path hits keep their
  5x boost weighted by the same idf. Content matching is whole-word
  tokenisation (previously substring counts). Scores returned by
  `select_for_task` and printed by the CLI are now floats.

## [0.4.0] - 2026-10-13
### Added
- Secret guard: `secrets_scan` module flags likely secrets in files that
  would be exported (provider token shapes: AWS AKIA/ASIA, GitHub
  ghp_/gho_/…, OpenAI/Anthropic sk-, Slack xox*, private-key blocks,
  context-gated AWS secret keys, passwords in URLs, sensitive-named
  assignments, generic high-entropy assignments). Findings carry path,
  line, and pattern type only, redacted to the first 4 characters.
  Placeholder values (example, xxx, your-key-here, changeme, dummy,
  sample, fixture, env references, empty) do not flag. Surfaces:
  `ghostslice secrets <path>` (exit 1 on findings), a secrets section
  in `scan`, loud warnings from `export`/`task`, `export
  --exclude-secrets`, dashboard `/api/secrets`, and MCP `check_secrets`.
- Notebook (`.ipynb`) slicing: code cells only (outputs and execution
  counts stripped by construction), markdown cells kept as comments;
  strip-tests drops test cells; malformed notebooks never crash.
  Markdown `headings` mode: headings plus the first paragraph under
  each (docs still default to `full`; use per-glob/profile to opt in).
- Duplicate detection: exact duplicates by sha256 of normalized
  content, near-duplicates by line-shingle Jaccard >= 0.85 (files with
  >= 8 distinct lines and >= 200 normalized chars only). Surfaced in
  `scan`, `graph` prune recommendations, dashboard `/api/graph`, and
  the HTML report.
- Standalone HTML report: `ghostslice report <project> -o report.html`
  (single self-contained file, inline CSS, violet #6716f3, no JS or
  external assets; filenames/content HTML-escaped, secrets redacted).
- `ghostslice explain <project> <file>`: inclusion/exclusion reason,
  mode and why (explicit/profile/default/gitignore), original vs sliced
  estimated tokens, imports/importers, duplicate and secret flags.
### Changed
- Parser-lite brace matching is now string/comment aware for TS/JS and
  the Go/Rust/Java/C# lite slicers: braces inside '...', "...", `...`
  template literals (including ${...} interpolation and multi-line
  templates), // line comments, and /* ... */ block comments no longer
  affect depth. Rust lifetimes are handled with a char-literal
  heuristic. Remaining documented limit: braces inside regex literals
  (e.g. /}/) and nested backticks inside ${...} can still confuse it.
- MCP tool list grows from 4 to 5 (`check_secrets` added).

## [0.3.1] - 2026-10-12
### Fixed
- Python 3.10/3.11 crash in the Python slicer: `_is_type_alias` touched
  `ast.TypeAlias`, which only exists on 3.12+. CI (added in 0.2.0) caught
  it on the 3.10/3.11 matrix jobs while 3.12 passed. Guarded with getattr
  and verified by simulating the missing attribute.

## [0.3.0] - 2026-10-12
### Added
- MCP server (`ghostslice mcp`): stdlib stdio JSON-RPC with tools
  scan_project, slice_file, estimate_cost, export_bundle, tested
  end-to-end over a real stdio subprocess.
- Go, Rust, Java, and C# slicers (parser-lite): signatures and
  interfaces modes plus test stripping, with golden tests per language.
- Export defaults and CLI slicing now treat the new languages as
  slicable.
### Notes
- The savings ledger and its dashboard summary shipped in 0.2.0
  (earlier than this wave's plan); they are unchanged here.

## [0.2.0] - 2026-10-12
### Added
- Import/dependency graph (Python `ast`, TS/JS parser-lite) with prune
  recommendations in `ghostslice scan`, `ghostslice graph`, and the
  dashboard (`/api/graph`).
- Task-focused context: `ghostslice task --task "words"` (keyword-scored
  selection within a token budget) and `--diff` (git-changed files plus
  direct dependencies), exported as a bundle.
- Project profiles: `.ghostslice.json` (ignores, per-glob modes, model,
  budget_tokens, entry_points, preset), loaded automatically.
- Export presets: `claude-code` (default), `aider` (aider-files.txt file
  list), `generic` (prompt.md).
- Nested `.gitignore` support (per-directory files, subtree-scoped,
  nested negations can override parent rules).
- `ghostslice check-budget` CI gate (exit 1 when over budget).
- Savings ledger: exports append to `.ghostslice-history.jsonl`;
  `ghostslice history` and the dashboard summarise total savings.
- GitHub Actions CI (Python 3.10/3.11/3.12), issue + PR templates.

## [0.1.0] - 2026-10-12
### Added
- Scanner (.gitignore-aware), token estimator, Python `ast` + TS/JS
  parser-lite slicer (full/signatures/interfaces/strip-tests/exclude),
  pre-flight cost estimator with local dated prices.json, local web
  dashboard, `.claude_context` export bundle with manifest + `check`.
