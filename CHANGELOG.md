# Changelog

All notable changes to GhostSlice. Versions follow the build waves;
token counts are estimates everywhere (see README).

## [1.0.4] - 2026-10-14
Polish round 4: hardening and depth. The cyclic-symlink sweep
reaches the surfaces the v0.21 fuzz round never covered, the
Go/Rust lite parsers learn generics, and watch re-applies plugin
changes. Audit: `audits/POLISH_104_audit.md`.

### Fixed
- **Workspace detection no longer follows directory symlinks.**
  A declared member reached through a directory symlink — one
  escaping the project root, or aliasing an ancestor of a real
  member — was reported as a package even though the scanner
  never descends into symlinked directories and it could never
  own a file. Detection now accepts only real directories (the
  same rule the walk uses), skips such members with a warning
  naming each, and the manifest fallback no longer reports
  phantom packages through symlinked children. The dashboard,
  CI, watch, and the MCP server were swept with cyclic-symlink
  fixtures and pinned safe: everything terminates, and the
  dashboard still never serves file content from outside the
  project root.
- **Go generics in symbol outlines and signatures mode.**
  Generic functions (`func Map[T any, U any](...)`) were
  invisible to outlines, `slice --symbols`, task-selection name
  extraction, and signatures mode. Methods on multi-parameter
  generic receivers were attributed to a garbage parent
  (`Pair[K, V]`'s methods to `V]`) because the receiver type was
  split on whitespace; they now parent to the base type.
  Generic type declarations (`type Stack[T any] struct`) render
  in signatures mode, and generic interface methods are
  enumerated as symbols.
- **Rust impl headers with nested generics and `where`
  clauses.** An impl whose generic bounds contain an
  associated-type binding (`impl<I: Iterator<Item = u8>>
  Wrapper<I>`) was named `>` and its methods parented to it;
  generic spans are now stripped nesting-aware. An impl whose
  opening brace follows a multi-line `where` clause was not a
  region at all (its methods outlined as parentless free
  functions); the impl's brace is now found, not assumed.

### Added
- **Watch plugin reload.** With the CLI's watch session, plugin
  changes now take effect without a restart: editing the
  profile's `plugins` list or a plugin file's bytes re-runs the
  startup load (same validation and containment) at the next
  poll, and the new set replaces the active one atomically when
  its digest differs — so exports after the swap derive under
  the new set's cache namespace. Swaps are announced on the
  watch stream with the trust warning; a failed load keeps the
  last-good set, reports once per distinct bad content, and
  recovers when fixed. The session summary gains a
  `plugin_reloads` count.

## [1.0.3] - 2026-10-14
Polish round 3: responsiveness and reach. The dashboard stops
charging its first graph request for the call-graph build, the
graph command joins the cache, history learns filters and
percentiles, and watch stops ignoring profile edits. Audit:
`audits/POLISH_103_audit.md`.

### Added
- **History filters and percentiles.** `ghostslice history`
  gains `--top N` (the N runs with the largest savings, largest
  first) and `--since WHEN` (an ISO date, an ISO datetime, or a
  relative form like `7d`). The filters compose; totals, trend,
  and stats then describe exactly the runs shown, the text
  output says so on a `Filter:` line, and the JSON payload
  gains a `filter` block (additive; absent without flags).
  Records with unparseable timestamps are excluded by `--since`
  and counted, never silently kept or dropped. The aggregates
  gain a `percentiles` block (p50/p90 of per-run before / after
  / saved estimated tokens, linear interpolation), printed in
  the `--trend` stats; an empty history reports nulls, not
  invented zeros.
- **Watch profile reload.** `ghostslice watch` now notices
  changes to the profile file (the project's `.ghostslice.json`,
  or whatever file the session's profile was loaded from) and
  applies a valid new profile to subsequent scans and exports
  without a restart — including a profile created mid-watch.
  Detection is by content hash, so a bare `touch` reloads
  nothing. An invalid edit keeps the last-good profile, is
  reported once per distinct bad content, and recovers
  automatically when fixed; deleting the file reverts to the
  built-in defaults. The session summary gains a
  `profile_reloads` count. The profile's `plugins` list is not
  re-applied (process state from startup; changing it still
  needs a restart).

### Changed
- **Dashboard call-graph warm-up.** `serve` starts building the
  `/api/graph` call payload on a background daemon thread at
  startup, so the first graph request usually finds it ready
  (on this repo the lazy build measured ~3.3s; a warm-started
  first request is a memo hit). The payload is byte-identical
  to the lazy one, requests that arrive mid-build receive the
  same final payload, and a build failure is recorded and
  surfaces on the graph request exactly as the lazy failure
  did — never swallowed by the warm-up thread.
- **Graph command uses the cache.** `ghostslice graph` opens
  the persistent content cache under the active plugin digest
  (scan records + the dead-symbol pass's outlines) and gains
  `--no-cache`, matching scan/lint/calls. Output is
  byte-identical cached or not (pinned on fixtures, on this
  repo, and across a plugin edit). The import-graph walk
  itself still reads file text directly, as the call graph's
  ast walk does.

## [1.0.2] - 2026-10-14
Polish round 2: integration, performance, and config. The
persistent cache reaches the two commands that never used it,
the dashboard learns call relationships, and the duplicate
floors become settings. Audit: `audits/POLISH_102_audit.md`.

### Added
- **Call data in the dashboard graph.** `GET /api/graph` now
  carries a `"calls"` payload: Python symbols with their call
  edges (callers/callees from the call graph), computed on the
  first request and kept for the server run. A new Call graph
  panel under the slice preview lists the selected file's
  symbols with who calls each one, what each one calls, and a
  "possibly dead" tag. Edges are capped at 2,000 and dead
  candidates at 200 (true totals and truncation flags are
  reported, and the panel repeats the caveat); non-Python files
  honestly show no call data. Rendering stays textContent-only.
- **Configurable duplicate floors.** Two `.ghostslice.json`
  sections, validated as loudly as the `"lint"` section
  (unknown keys and non-positive or fractional values are load
  errors): `"duplicates": {"near_min_chars": N}` moves the
  near-duplicate size floor (default 200 normalized
  characters) and `"ci": {"duplicates_floor_tokens": N}` moves
  the CI duplicates gate floor (default 500 recoverable
  estimated tokens). Unset means the historical defaults on
  every surface; the init wizard documents both keys and the
  CI check reports the effective floor it used.

### Changed
- **`lint` and `calls` use the content cache.** Their scans,
  the slices lint prices, and the call graph's per-file
  outlines route through `.ghostslice-cache` with the export
  path's discipline (content-hash keys, plugin-digest
  namespacing, corrupt entries read as misses), and both
  commands gain `--no-cache`. Output is byte-identical with
  the cache off, cold, or warm (pinned on fixtures and on this
  repo; on this repo warm lint runs ~27% faster and warm calls
  ~18%). Duplicate detection is not cached (the cache has no
  kind for normalized text). The `scan` command's dead-symbol
  pass now reuses the cache scan already opens. The dashboard,
  MCP, and `ci` keep their no-disk-cache behaviour.

## [1.0.1] - 2026-10-13
Polish release: no new features — the tool run on itself, and
its own findings fixed. Audit: `audits/POLISH_101_audit.md`.

### Fixed
- **One price table.** `prices.json` existed twice (repo root and
  inside the package), byte-identical and both exported (lint
  L004). The repo-root copy is removed: `src/ghostslice/prices.json`
  is the single source of truth (it is the copy shipped as package
  data), the loader's checkout-root candidate is gone, and the
  table is pretty-printed for hand-editing, which also removes
  its giant-lines (L006) shape. A `prices.json` in the current
  directory still overrides for that run, as before. Self-lint on
  this repo: 7 warnings -> 5 (the two price-table warnings are
  fixed; one new L001 appeared because this round's notes pushed
  README.md just over the oversize threshold), the rest
  explained in README "Known warnings on this repo".
- **Call graph: plugin modules and public classes are roots.**
  `calls --dead` flagged 10 false positives on this repo: the
  example Lua plugin's functions (invoked by the plugin loader,
  invisible to import reachability), the `PluginAPI` methods (the
  surface a plugin's `register()` receives), and textio's public
  `read_text_with_encoding`. The analyzer now roots the plugin
  contract's entry points in any module presenting the contract
  (a top-level `register`, or LANGUAGE/EXTENSIONS plus
  `slice_text`) and the direct methods of classes named in a
  module's `__all__`. Only the contract/public surface is rooted:
  a genuinely dead helper inside a plugin file still flags.
  textio also gained an explicit `__all__`. This repo now reports
  0 dead candidates.
- **Dashboard: no innerHTML anywhere.** The pre-existing file
  table and prune recommendations rendered file paths through
  `innerHTML` (the G17 preview/what-if surfaces already used
  textContent). Rows, totals, recommendations, and treemap
  labels are now built with createElement + textContent; a file
  named with HTML metacharacters displays inertly. No visual
  change.

### Checked, no change
- Consistency sweep: all 80 CLI help strings verified (verb
  phrases, no trailing periods — the one capital start is the
  acronym "CI"), README's feature map re-verified against
  `--help` (25 commands, one line each), and probed error
  messages (unknown model, missing project, bad budget, missing
  cache) all exit 2 naming the problem and, where one exists,
  the remedy.

## [1.0.0] - 2026-10-13
The marathon release: GhostSlice 1.0 is the tool the twenty-goal
run set out to build — a zero-dependency context optimizer that
scans, slices, prices, lints, redacts, and bundles project
context for AI agents, with a dashboard, an MCP server, a plugin
system, and a CI gate. New in this release:

### Added
- `ghostslice doctor`: one-screen environment + project health
  (Python floor, version agreement between the package and
  pyproject.toml, estimator stamp, price table, profile, cache,
  ledger, plugins, git hygiene, workspaces) — every warning or
  failure carries a one-line remedy; exit 1 on any fail; never
  writes. Doctor runs even when the price table is broken (the
  one state the rest of the CLI exits early on), because
  reporting that state is its job.
- `ghostslice completions bash|zsh`: completion scripts
  generated from the live argument parser (single source of
  truth); shipped copies in `examples/completions/` are pinned
  byte-equal to fresh output by the test suite.
- README: a stranger-runnable Quickstart, a "What's in 1.0"
  feature map covering every command, and a Troubleshooting
  section fed by doctor's remedies.

### Changed
- `scan` text output (v1.0 layout, Ryan's mockups): the file
  table is now top-N (`--top`, default 15) with a heat bar
  scaled to the largest file and each file's % of total; the
  remaining files collapse into one summary line, and the
  output closes with a summary box (files, total estimated
  tokens, largest file, estimated input cost). The separate
  Pre-flight cost block folded into the box. `scan --json` is
  unchanged.
- `--fit` report is a table (before/after/result plus a
  downgrade-step table); content identical, layout only.
- pyproject.toml version aligned with the package (it had
  drifted at 0.16.0 — the readiness audit's doctor caught it;
  a test and a doctor check now pin the agreement).

### The road here (per-version entries below)
- 0.6-0.9: watch mode, task selection v2, C/C++/Scala slicers,
  config structure slicing.
- 0.10-0.14: estimator calibration, context lint, generated/
  vendored detection, monorepo support, history analytics.
- 0.15-0.19: init wizard, XML/JSON bundles, redact-in-place,
  symbol-level slicing, Python call graph + dead functions.
- 0.20-0.24: content cache + performance, fuzz/encoding
  robustness, dashboard v2 (slice preview + what-if), the
  plugin system, and the CI pack.

## [0.24.0] - 2026-10-13
### Added
- CI pack (G19): `ghostslice ci <project>` runs five named checks
  over the default export selection in one read-only pass:
  budget (vs the profile's `budget_tokens` or `--budget`;
  skipped, not failed, when no budget is configured), lint
  (errors fail; warnings fail only with `--strict`), secrets
  (guard findings FAIL by default; `--allow-secrets` downgrades
  them to a warning for the whole run, including lint's L005
  rule; `--fail-on-secrets` spells the default explicitly), fit
  (whether the auto-fit ladder can reach the budget), and
  duplicates (exact-duplicate groups with 500+ recoverable
  estimated tokens warn). Each check reports pass / warn / fail /
  skipped with a one-line evidence string.
- Exit semantics: 0 = no failed check, 1 = a check failed,
  2 = usage/config errors. `--json` emits one machine payload
  (checks, totals, summary, `exit_code`); `--pr-comment` prints
  a compact Markdown summary for PR comments; `--out FILE` also
  writes the HTML report. A check that errors internally fails
  that check alone; the run itself never tracebacks and writes
  nothing without `--out`.
- GitHub Action sample in `examples/github-action/`: checks out
  the user's repo, installs GhostSlice from its GitHub repo (it
  is not on PyPI), runs `ghostslice ci` with the budget from a
  workflow env var, uploads the JSON + Markdown + HTML artifacts,
  and optionally posts the summary as a PR comment with the
  built-in GITHUB_TOKEN. This repo dogfoods the command in
  `.github/workflows/ghostslice-ci.yml` (budget 180,000 on the
  command line; no repo profile added).

## [0.23.0] - 2026-10-13
### Added
- Plugin system for user slicers (G18): teach GhostSlice a new
  language, or replace a built-in slicer, with a single Python
  file. Two contract styles: module attributes (`LANGUAGE`,
  `EXTENSIONS`, `slice_text(path, text, mode)`, optional
  `outline(path, text)`) or `register(api)` with
  `api.register_slicer(...)`, `api.estimate_tokens`, and
  `api.MODES`. One file may register several languages.
- Loading is explicit only, never ambient: the profile's
  `"plugins"` list (paths relative to the project root and
  required to resolve inside it, symlinks followed) or `--plugin
  PATH` (repeatable) on export/slice/task/watch. No directory
  scanning, no entry points, no environment variable. The CLI
  prints every loaded plugin plus a plain warning that plugins
  are user code run with full privileges. The profile route also
  drives the dashboard and the MCP tools.
- Plugin languages are first-class: the scanner maps their
  extensions, token estimation is the standard estimator, the
  modes pipeline hands them resolved modes (`full`/`exclude`
  stay with the core), outlines join `ghostslice symbols` and
  `export --symbols` (no outline means an honest "no outline"),
  and the fit ladder, task selection, lint, and the dashboard
  what-if all treat them like built-ins.
- Failure discipline: a plugin load failure (syntax error, broken
  contract) fails the command with exit 2 before anything is
  written. A plugin failing on one file falls back to that file's
  full text, records a `plugin_errors` entry in the manifest, and
  prints a CLI warning. Bytes returns are decoded as UTF-8; other
  non-string returns follow the same fallback. Overriding a
  built-in language or claiming its extension is refused without
  `--allow-plugin-override`; duplicate claims on a new language
  resolve last-loaded-wins with a printed note.
- Cache safety: when plugins are loaded, every content-cache key
  is namespaced by a hash of the loaded plugins' file bytes, so
  editing a plugin invalidates its cached slices, outlines, and
  scans automatically. The manifest gains a `plugins` block
  (name, language, extensions, source path, sha256) whenever a
  bundle was built with plugins.
- Example plugin: `examples/plugins/lua_slicer.py`, a parser-lite
  Lua signatures slicer (function/end block matching over a
  string/comment-masked view, long brackets handled) with a basic
  outline, plus `examples/plugins/README.md`. An integration test
  runs the full pipeline (scan, export, symbols, symbol slicing,
  MCP) on a Lua fixture using only the example.
- 49 new tests (679 -> 728) in tests/test_v23_plugins.py.

## [0.22.0] - 2026-10-13
### Added
- Dashboard side-by-side slice preview (G17): clicking a file shows
  the original and its slice in two panes, with original → sliced
  estimated tokens and % saved in the header and a mode switcher
  that re-slices live via the new `GET /api/slice`. Displayed text
  is capped at 200,000 characters per side (flagged `truncated`;
  token counts always describe the full text). The endpoint only
  serves scanned files whose resolved path stays inside the
  project root — `..` segments, absolute paths, backslash paths,
  and symlinks pointing outside are refused; symlinks resolving
  inside are served. `/api/preview` gets the same containment.
- Dashboard what-if panel (`POST /api/whatif`): a global mode
  override, a budget/fit target, and exclude-secrets / redact /
  auto-shrink toggles report would-be totals, the delta against a
  plain default export, the per-file mode-change count, and the
  fitted verdict — computed in memory with the exporter's own
  resolve / fit / slice / redact machinery, writing nothing and
  recording no history. Totals are pinned by tests against a real
  `build_bundle` for every option combination, including profiled
  projects and fit + redact (totals are post-redaction, exactly
  as an export reports).
- The dashboard Export button sends the what-if panel's options,
  so what was previewed is what gets exported; the response gains
  the manifest's fit and redaction summaries when present.
### Fixed
- Dashboard export now honours the project's `.ghostslice.json`
  profile (modes, ignores, entry points, redact / auto-shrink
  defaults), as the CLI export and the dashboard's own scan
  already did; previously it exported without the profile, so a
  profiled project showed one selection and exported another.
- Dashboard export `out` is verified to stay inside the served
  project (a nested path such as `bundles/one` still works);
  `../` escapes are refused with a 400 instead of writing a
  bundle outside the project.

## [0.21.0] - 2026-10-13
### Added
- Shared text decoding (`textio.py`, G16): every surface that turns
  file bytes into text — scanner, slicers, exporter, graph, lint,
  watch, dashboard, MCP — now decodes through one helper. BOMs are
  sniffed (UTF-8 / UTF-16 LE/BE / UTF-32 LE/BE) and decoded with the
  matching codec; counts are computed on the decoded text; bytes
  that are not valid UTF-8 fall back to Latin-1 (lossless) instead
  of U+FFFD mangling. Scanner entries carry `encoding`; bundle
  manifests carry `source_encoding` whenever a file was not plain
  UTF-8. Bundle `files/` are written and re-read as exact bytes.
- Fuzz harness: `tests/fuzz_harness.py` builds a seeded,
  deterministic mutated corpus (truncations, bit flips, NUL and
  invalid-UTF-8 injection, BOM/EOL shuffles, brace unbalancing)
  plus malformed profile/manifest/ledger families;
  `tests/test_v21_fuzz.py` drives every command and library entry
  point over it under a no-traceback invariant.
### Fixed
- UTF-16/UTF-32 files were silently skipped as "binary" (the NUL
  test ran before any decoding); they now scan, slice, and export
  like their UTF-8 twins. A UTF-8 BOM no longer costs a phantom
  token or breaks `ast.parse`. CR-only files report a real line
  count (scanner counts with `splitlines()` semantics).
- Bundles whose slices keep CR/CRLF line endings (full-mode text,
  docs, configs) failed their own `ghostslice check`: bundle files
  are now written as exact bytes and validation reads bytes (text
  mode's universal-newline translation silently rewrote the text
  being hashed). The XML validator now compares against the
  parser-normalized form (XML 1.0 section 2.11: CR/CRLF become LF
  when an XML parser reads `context.xml`).
- Malformed input no longer tracebacks anywhere: profile JSON and
  wrong-typed profile fields are exit 2 naming the field (every
  command, not just lint); `check`/`diff` on missing, malformed,
  or wrong-shaped manifests report errors instead of raising;
  unknown `--model` ids (CLI or profile) are a clean exit 2;
  deeply nested Python/JSON degrades to the fallback/full
  rendering instead of RecursionError; non-object JSON bodies and
  messages in the dashboard/MCP surfaces are rejected, not crashed
  on; filesystem failures at the CLI are clean exit-2 messages.
- A FIFO (or socket/device) in a scanned tree hung the scanner
  forever on open; the scanner now only reads regular files.

## [0.20.0] - 2026-10-13
### Added
- Content cache (G15): a per-project `.ghostslice-cache/` memoizes
  the tool's pure derivations — per-file scan results (token
  estimate, lines, detection evidence), slice results, symbol
  outlines, and symbol-slice renders — keyed by sha256 of every
  input (content hash, relative path, mode or sorted keep-set,
  GhostSlice version, estimator version). Export/slice/task/watch
  and `check-budget` consult it; `scan --timing` and
  `export --timing` print phase breakdowns (scan/resolve/slice/
  render) plus hit/miss/corrupt counters; `ghostslice cache
  stats|clear <project>` inspects and removes it. Bundles are
  byte-identical with the cache off, cold, or warm (whole-tree
  diffs in the test suite), and one changed file in a 2,000-file
  tree misses exactly its own two entries. Entries are written
  atomically (temp + rename; racing exports both succeed),
  corrupt entries count and read as misses, and a 256 MiB cap
  evicts oldest-first. GHOSTSLICE_NO_CACHE=1 or `--no-cache`
  disables it. Local paired measurements (BENCHMARKS.md): warm
  exports ~7-30x faster than cold, warm scans ~3-5x.
- Parallel slicing: `export --workers N` slices on a thread pool
  with results aggregated in manifest order — byte-identical at
  any worker count (test-pinned). It defaults to 1 on purpose:
  measured on the benchmark tree, threads gained ~5% cold at 2
  workers (noise), lost at 4, and made warm runs slower, because
  the hot work is regex/AST under the GIL. The cache is the win.
### Changed
- `.ghostslice-cache` joins the scanner's built-in ignore dirs:
  the cache is never scanned, exported, or watched.
- Nothing else: every command's default output is unchanged, and
  manifest bytes are identical whether the cache is on or off
  (timing travels out-of-band via a build_bundle out-param).

## [0.19.0] - 2026-10-13
### Added
- Python call graph (G14): new module `callgraph.py` and a
  `ghostslice calls <project> [file] [--json] [--dead]` command.
  Per Python file, `ast` call edges between project symbols
  (symbols from the same outline `ghostslice symbols` prints),
  each labelled exact (same file, `self.`/resolved project base,
  import evidence incl. aliases and `module.func()`), heuristic
  (bare name matched across modules without import evidence), or
  attribute (`anything.name(...)` fans out to every project
  method of that name; `self.`/`cls.` calls also fan out to
  subclass overrides). References count as well as calls
  (callbacks, tables, defaults, bases, decorators). Calling a
  class counts as calling its `__init__`. The listing shows
  per-symbol callers/callees for one file and a fan-in ranking
  overall; unresolved/external call sites are counted, not
  hidden.
- Dead-function candidates: callable symbols unreachable from
  the root set (module top levels; profile-declared entry
  points at full trust, heuristic entry files rooting only a
  function named `main`; `[project.scripts]` targets; `__all__`
  exports; test files and `conftest.py`; framework-decorated
  functions; methods of classes extending a non-project base),
  with dunders, unparseable files, and directly self-recursive
  functions exempt. Candidates surface in `calls --dead` and,
  as kind `dead-symbol`, in the `scan`/`graph` prune
  recommendations (the shared recommendations function — and
  lint, which consumes it — is unchanged). Every candidate
  carries the honesty line: recommendations to review, not
  instructions; string-based dispatch (`getattr`) is invisible
  by design and will be flagged. Nothing is auto-excluded.
- Import resolution for the call graph reuses graph.py's
  module mapping, plus a unique-suffix fallback so src-layout
  projects (`src/pkg/...` imported as `pkg...`) resolve.

## [0.18.0] - 2026-10-13
### Added
- Symbol-level slicing (G13): new module `symslice.py` with symbol
  outlines for every sliced language and a new selection surface.
  `ghostslice symbols <project> [file] [--json]` lists each file's
  symbols (qualified name, kind, line span, estimated tokens);
  files in languages without an outline (notebook, markdown,
  config/data, text) are reported as having none, never guessed.
  Python outlines come from `ast` (exact: nested functions,
  methods, classes, module constants, class attributes, and defs
  inside compound statements); the other languages reuse the
  slicer's parser-lite declaration regexes and brace matcher, so
  outline spans are the spans the signatures slicer already trusts.
- `export --symbols SPEC` (and MCP `export_bundle`'s `symbols`
  array): entries are bare names, `Class.method` qualified names
  (suffix-matched: `Store.total` reaches `Shop.Store.total`; C++
  uses `Store::total`), `file.py:name` scoping (globs allowed;
  a colon only scopes when its left side names a scanned file),
  and `*` globs. Matched files ship in the new mode `symbols`:
  requested symbols with bodies, always-context (imports; Python
  docstring head and small constants), enclosing classes as
  shells, and all other symbols collapsed (Python reuses the
  signatures renderers; lite languages collapse to a signature
  line and keep declaration types whole, as signatures mode
  does). Files with no match are excluded, except profile entry
  points, which keep their resolved mode. A bare name matching
  in several files matches in ALL of them and is reported as
  ambiguous in the CLI and the manifest's new top-level `symbols`
  report (requested / matches / ambiguous / per-file
  `symbols_included`); PROMPT.md sections are headed with the
  symbol list. An entry matching nothing raises/exits 2 with
  near-miss suggestions BEFORE anything is written. Composition:
  presets (incl. context.json/xml) and `--redact` apply as usual;
  `--exclude-secrets` still wins over a match (report gains
  `excluded_by_secrets`); `--symbols` + `--fit` is rejected.
- Audit G13 fixes baked in: the Python renderer recurses into
  compound statements at module, class, and function scope, so
  conditionally-defined symbols (`if`/`else`, `try`/`except`,
  `match`, `if TYPE_CHECKING:`) render — kept bodies ship,
  unkept ones signpost — instead of silently vanishing from a
  symbols export (F1); Kotlin/Swift properties and PHP fields
  are outline symbols, matching what signatures mode keeps and
  task selection counts (F2).

## [0.17.0] - 2026-10-13
### Added
- Redact-in-place export (G12): `export --redact` (also `task`,
  `--fit`, `watch --export`, MCP `export_bundle`, and the profile
  option `"redact": true` with a `--no-redact` per-run override).
  The final sliced text of every included file is scanned and each
  flagged secret value is replaced where it sits with
  `[REDACTED:<kind>:<fp>]` — fp is the first 8 hex of the value's
  sha256, so identical secrets map to identical tokens across files
  and runs. Values under 12 characters get a fingerprintless token
  (an 8-hex fingerprint of a short password is a brute-force
  oracle). A private-key finding replaces the whole PEM block.
  New shared API: `secrets_scan.redact_text` (plus REDACTED_KINDS,
  the same kind set --exclude-secrets judges), built on the
  scanner's span-carrying core, with a re-scan gate that fails the
  export loudly if a reportable finding survives.
- The redaction scan judges comment lines as content (Markdown
  headings, block-comment bodies, commented-out config): audit G12
  F1 caught real keys shipping there behind a "redacted" claim.
  Reporting surfaces (`secrets`, lint L005, watch warnings, the
  config backstop) keep the documented comment-skip heuristic;
  redaction is a strict superset of the guard, never weaker.
- Manifest: per-file `redactions`/`redaction_kinds` and a top-level
  `redaction` block (values/files/kinds, plus `left_in_place` for
  any kind the redactor does not handle — surfaced in the CLI
  summary, never silent). Totals and hashes are post-redaction.
  `ghostslice check` re-scans bundles whose manifest claims
  redaction (comment-inclusive) and fails on any surviving
  reportable literal; the result gains `redaction_checked`.
  Ledger records from redacted exports gain a `redactions` count.
- Precedence, explicit in CLI output: with `--exclude-secrets` also
  on, exclusion wins for flagged files and redaction covers the
  rest. With `--fit`, the ladder judges pre-redaction slices and
  the manifest fit block records `redacted_after_tokens` when the
  two totals differ (audit G12 F2).

## [0.16.0] - 2026-10-13
### Added
- Two export presets (G11), both rendered from the same in-memory
  slice results as PROMPT.md — never re-read or re-sliced:
  - `anthropic-xml`: adds `context.xml`, one well-formed XML
    document in Anthropic's `<documents>` shape. Each included file
    is a `<document index mode package original_tokens
    sliced_tokens sha256>` with `<source>` and
    `<document_content>`; every other manifest file is listed
    under `<excluded>` with its mode and reason (mode `exclude`,
    or an empty slice). Content is escaped by ElementTree (no
    CDATA); characters XML 1.0 cannot represent are replaced by
    U+FFFD in context.xml only — `files/` keeps the canonical
    bytes.
  - `json`: adds `context.json`, a single JSON object
    (`project`, `generated_by`, `version`, `model`, `totals`,
    `files` with per-file mode/language/package/tokens/sha256/
    content, `excluded`) for other tools and agents to consume.
- `ghostslice check` validates either artifact when present: XML
  and JSON must parse, per-file content must equal the bundle's
  own sliced bytes (XML compared after the documented U+FFFD
  step), per-file sha256 and JSON totals must match the manifest,
  and the document/file set must mirror the manifest exactly.
  Truncated or tampered artifacts fail with clear messages;
  bundles without an artifact validate exactly as before. The
  result gains an additive `artifacts_checked` list.
- Wrapper cost is reported, not hidden: the manifest gains
  `wrapper_artifacts` per artifact — `bytes`, `estimated_tokens`
  (the artifact as written, escaping included), and
  `overhead_estimated_tokens` (artifact estimate minus the sliced
  total: the markup cost beyond the slices the artifact contains)
  — and the export/task CLI prints both figures. Manifest totals
  still count file slices only.
- The MCP `export_bundle` preset enum (which follows PRESETS)
  exposes both new presets; `build_bundle` accepts an optional
  `model` recorded in context.json.

## [0.15.0] - 2026-10-13
### Added
- `ghostslice init <project>`: generates a tuned `.ghostslice.json`
  from the tool's own analysis, with a printed justification for
  every section. Entry points are ranked candidates (new
  `entries.py`): package.json "bin" / pyproject [project.scripts]
  (+60), package.json "main" (+50), the entry-name heuristic shared
  with the prune engine (+40), a Python `__main__` guard (+35), a
  shebang (+25), and "nothing imports it" (+10, tie-breaker only),
  capped at 5; test files and vendored/generated files are never
  nominated. Vendored directory trees (detect.py path evidence) go
  to `ignore`; all-generated directories (and lone generated files)
  get `modes: "exclude"`; config-heavy directories (≥70% config/data
  files, ≥3 files, ≥500 estimated tokens) get `modes: "structure"`.
- `budget_tokens` defaults to the current default-sliced total
  × 1.25, rounded up to two significant figures, and is omitted
  (with the reason printed) when the sliced total is under 5,000
  tokens. `--budget N` overrides; `--model ID` is the only way a
  model is pinned — init never invents one. No `lint` section is
  written in this version (documented choice); lint findings feed
  the printed top-3 "biggest wins" instead.
- Safety and interaction: an existing profile is refused (exit 2,
  with a summary of its contents) unless `--force`; `--dry-run`
  writes nothing; a written profile is loaded back through the real
  loader before success is reported. On a TTY, each section is
  confirmed with the analysis as the default; non-TTY stdin behaves
  as `--yes` and prints that it did.

## [0.14.0] - 2026-10-13
### Added
- History analytics (`ledger.analytics`): `ghostslice history
  --trend` prints a per-run table (before → after, saved, saved %,
  Δ after-tokens vs the previous run, estimated $ saved per run and
  cumulative at the model's INPUT rate, labelled "prices as of …,
  local snapshot, not live"), aggregates (mean/median saved %, best
  and worst run, first→last context-size change, span; runs/week
  only for spans of a day or more), and width-bounded ASCII
  sparklines of saved and after tokens. `--model ID` picks the
  pricing model (default: profile model or claude-sonnet);
  `--json` returns the full analytics payload — summary keys
  unchanged, plus `runs_detail`, `aggregates`, `charts`,
  `corrupt_lines`, `estimator`, and `model` blocks. The dashboard
  `/api/history` (and the scan payload's `history`) return the same
  payload.
- HTML report: the savings-history section now embeds an inline
  SVG chart (saved-token bars on a shared zero line, after-token
  line on its own labelled scale) plus the total estimated $
  saved, whenever the project has a ledger; with no ledger the
  section is absent.
- Ledger records are stamped with the estimator version that
  produced their totals (`"estimator": "v2"`; `tokens.METHOD_VERSION`).
### Changed
- Estimator honesty: a history that is not uniformly one stamped
  version (any pre-v0.14 unstamped records, or several stamped
  versions) is flagged with an "Estimator mix" warning on the CLI,
  in the JSON payload, and in the HTML report — pre-v0.10 (v1) and
  v0.10–v0.13 (v2) unstamped totals cannot be told apart, so trends
  across them are labelled approximate instead of silently trended.
- Ledger reading counts corrupt lines (bad JSON, non-object JSON,
  non-numeric token fields) and skips them; `summary()` reports
  them as `corrupt_lines`. (The old reader would have crashed on a
  non-object line.)
### Fixed
- Trend $ consistency: per-run/cumulative dollars accumulate raw
  values and round only for display, so the final cumulative always
  equals the aggregate total (audit G09 F1).

## [0.13.0] - 2026-10-13
### Added
- Monorepo / workspace support (`workspaces.py`): package
  boundaries detected once per scan from root-level workspace
  manifests — npm `workspaces` (array or `{packages: [...]}`,
  `!` negations), `pnpm-workspace.yaml` (block list at any
  indentation plus single-line flow lists), Cargo `[workspace]`
  `members`/`exclude` (TOML-lite: quoted strings, comments inside
  arrays; `exclude` cannot remove an explicitly listed member),
  `go.work` `use` directives (single + block form), and
  `[tool.uv.workspace]` members. Declared members that are
  missing on disk are reported (`missing`); members escaping the
  project root are skipped with a warning — both are visible in
  `scan` text and in the `--json` `"workspace"` block.
- Manifest fallback: when nothing is declared, top-level
  directories (or their immediate subdirectories, the
  `packages/<name>` shape) carrying a recognised manifest are
  reported as kind `detected`, visibly distinct from `declared`.
  Nested packages resolve outermost-first; `**` in a member glob
  counts as one path segment (documented simplification).
- Every scanned file gains a `package` field (owning package
  root, `""` for the root package). Per-package subtotals
  (files / original estimated tokens / share, plus sliced
  tokens/share in bundles) appear in `scan` text (when more
  than one package exists), `scan --json` (`"packages"`), the
  export manifest (`"package"` per file, top-level
  `"packages"`), `/api/scan`, and the HTML report.
### Notes
- Additive only: pre-v0.13 bundles still validate (the new
  manifest keys are ignored by the validator), and single-package
  projects see no new output beyond the JSON fields. Selection,
  modes, budgets, graph and lint behaviour are unchanged;
  per-package budgets are out of scope.
- GhostBus verification: totals unchanged (129,555 -> 45,770
  estimated tokens); all 42 files sit in the root package.

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
