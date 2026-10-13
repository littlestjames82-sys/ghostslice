# GhostSlice — 20-Goal Marathon

Directed by Ryan, Oct 13, 2026: "make 20 long goals and finish each one
and audit after each goal improve it twice then move on to the next goal"

Loop per goal: BUILD -> AUDIT -> IMPROVE (round 1) -> AUDIT -> IMPROVE
(round 2) -> parent verify (own test run + spot checks) -> push to
GitHub (blob-verified) -> GitHub release -> next goal.

Standing constraints, every goal: zero-dependency Python stdlib only;
token counts labelled estimates; prices local/dated; NO PyPI publish;
NO announcements; existing tests never weakened.

Versions: G1-G19 ship as v0.6.0 ... v0.24.0; G20 ships as v1.0.0.
Baseline: v0.5.0, 149 tests passed.

| # | Goal | Version | Status |
|---|------|---------|--------|
| G1 | Watch mode: polling watcher, auto rescan/re-export on change, debounced, ledger-aware | v0.6.0 | done |
| G2 | Task selection v2: symbol-name matching + import-graph boosting on top of TF-IDF | v0.7.0 | done |
| G3 | C, C++, Scala parser-lite slicers (systems-language completion) | v0.8.0 | done |
| G4 | Config slicing: shell/PowerShell + SQL + YAML/TOML structure mode (keys/structure, values optional) | v0.9.0 | done |
| G5 | Token estimator calibration: per-language factors, golden corpora, `calibrate` report | v0.10.0 | done |
| G6 | Context lint: rule engine for context waste (oversize, generated, vendored, minified, giant lines) | v0.11.0 | done |
| G7 | Generated/minified/vendored detection wired into scan, graph, export (opt-in auto-modes) | v0.12.0 | done |
| G8 | Monorepo support: workspace detection (npm/Cargo/go/pyproject), per-package subtotals everywhere | v0.13.0 | done |
| G9 | History analytics: trends, per-model $ saved, ASCII chart, JSON export + savings-history chart embedded in the HTML report (Ryan's mockups, Oct 13) | v0.14.0 | done |
| G10 | `init` wizard: analyze a project and generate a tuned .ghostslice.json (non-interactive --yes mode) | v0.15.0 | done |
| G11 | New bundle formats: Anthropic-style XML bundle + JSON bundle presets | v0.16.0 | done |
| G12 | Redact-in-place export: --redact-secrets replaces secret values with placeholders instead of excluding files | v0.17.0 | done |
| G13 | Symbol-level slicing: keep named symbols + their in-file dependencies (Python ast, TS lite) | v0.18.0 | done |
| G14 | Python call graph: function-level graph, entry-point reachability, dead-function candidates | v0.19.0 | done |
| G15 | Performance: scan caching (.ghostslice-cache), parallel scan, benchmark proof, identical totals | v0.20.0 | done |
| G16 | Fuzz/robustness: malformed-input fuzzing for every slicer + encoding handling (BOM, UTF-16, latin-1) | v0.21.0 | pending |
| G17 | Dashboard v2: side-by-side slice preview (original vs slice, per Ryan's mockups, Oct 13) with diff highlighting + budget slider with live auto-fit preview | v0.22.0 | pending |
| G18 | Plugin system: user slicers from .ghostslice-plugins/*.py, documented API, example plugin | v0.23.0 | pending |
| G19 | CI pack: `ghostslice ci` one-shot (budget + secrets + lint) with PR markdown summary + sample GitHub Action | v0.24.0 | pending |
| G20 | v1.0.0: `doctor` self-check, shell completions, docs restructure, full release-readiness audit + mockup polish (Ryan approved Oct 13): scan CLI top-N with heat bars + % of total + token/cost summary box, export --fit report table in the mockup style | v1.0.0 | pending |

Progress log is appended here as each goal closes, with test counts and
the audit findings that drove the two improvement rounds.

## Progress log

- G1 (v0.6.0) DONE Oct 13, 2026: watch mode shipped — stdlib polling
  watcher, debounce (default max(1s, 2 polls)), compact token deltas,
  --export/--fit/--exclude-secrets via build_bundle, loop-proof
  (bundle dir excluded from detection AND from watch bundle contents),
  --once/--max-events, Ctrl-C summary. Tests 149 -> 173 (24 new).
  Audit rounds (audits/G01_audit.md): round 1 headline fixes — a
  CRITICAL bundle==project-root guard that compared against "."
  instead of "" (caught by its own test after it filled the disk with
  recursive bundles; fixed + regression-pinned), failed exports no
  longer kill the watcher, watch exports no longer ingest the
  previous bundle, NaN CLI args rejected, burst test made
  deterministic on a fake clock, secrets-on-change test added.
  Round 2 headline fixes — watching a nonexistent path now exits 2
  (mid-watch deletion stays soft), revert-before-settle mtime
  semantics pinned by a fake-clock test.
- G2 (v0.7.0) DONE Oct 13, 2026: task selection v2 shipped — symbol
  matching (exact name 15.0, camel/snake part 10.0, per-file cap
  25.0; Python ast + module/class assignment targets, other
  languages via the slicer's signatures output) and one-hop graph
  boosting (25% of the strongest adjacent SELECTED seed, capped
  6.0, max-not-sum so hubs are not dragged in by popularity),
  with the tfidf/symbol/graph breakdown on the CLI and as additive
  manifest fields. Tests 173 -> 196 (23 new). Recovery note: the
  first G2 agent died in a daemon restart mid-goal; its uncommitted
  build was adopted and reviewed file by file, not rebuilt.
  Audit rounds (audits/G02_audit.md): round 1 headline fixes —
  Python constants/class attributes were not symbols at all (now
  collected; function-locals deliberately excluded), and symbol
  extraction ran the slicer on every file even when no keyword
  could match (now gated by a keyword-part substring prefilter
  with a no-false-negative argument). Round 2 headline fix — the
  gate recomputed keyword parts per file (now computed once per
  selection); scope edges of the constants fix (nested classes,
  bare annotations, walrus) reviewed and pinned.
- G3 (v0.8.0) DONE Oct 13, 2026: C, C++, Scala parser-lite slicers
  shipped — C keeps preprocessor lines + struct/union/enum/typedef
  surface (a prototypes-only header barely shrinks in signatures,
  pinned), C++ adds member signatures, namespaces, templates,
  out-of-line definitions and split declarations, Scala adds
  def/val/var + trait/enum full with a Scala 3 indentation fallback
  that keeps more rather than less; the shared brace matcher gained
  gated preprocessor skipping, C++ raw strings, digit separators,
  Scala nested comments / triple-quoted strings / interpolation.
  Tests 196 -> 223 (27 new). Audit rounds (audits/G03_audit.md):
  round 1 headline fix — a CRITICAL head-detection miss: qualified
  (Store::total) and pointer-attached (char *get_name) names
  matched nothing, so out-of-line definitions vanished and their
  bodies leaked (same flaw fixed in the G2 symbol regex); plus
  ctor-init-list continuation, comment-blind declaration scans,
  raw-string delimiter and Scala `=:=` guards. Round 2 headline
  fix — split declarations whose `;` lands on a following line
  (`= 0;`, attributes, trailing returns) are now prototypes running
  to that line; K&R definitions are consequently read as
  prototypes (documented, still unsupported).
- G4 (v0.9.0) DONE Oct 13, 2026: config slicing shipped — a new
  `structure` mode (configslice.py) for YAML/TOML/JSON/SQL/shell/
  PowerShell: key/DDL/function surface kept, values under a
  documented rule (sensitive keys always placeholdered, segment
  matching; numbers/bools/short enum-like strings kept; free text
  and block scalars placeholdered wholesale; secret-scanner
  backstop over every rendering), sequences/JSON arrays collapse
  to an exemplar + count, homogeneous JSON maps >20 entries
  collapse too, SQL INSERT summaries carry counted rows, config
  keys joined the G2 symbol fallback. Config files still default
  to full (GhostBus demo unchanged: 165,052 -> 53,339; only
  scanner language labels moved). Tests 223 -> 276 (53 new).
  Audit rounds (audits/G04_audit.md): round 1 headline fixes —
  two CRITICAL leaks (indentless YAML sequences under sensitive
  keys rendered their exemplar verbatim; one-line shell/PS
  functions kept bodies that could hold assignment-shaped
  secrets), sequences under sensitive keys now collapse
  wholesale, blank-separated lists collapse correctly, TOML
  trailing comments no longer corrupt arrays/strings, dashboard
  mode dropdown gained structure/headings. Round 2 headline
  fixes — PowerShell here-string opener with a trailing comment
  no longer leaks its body into the rendering, and flow-style
  YAML list items render through the flow renderer.
- G5 (v0.10.0) DONE Oct 13, 2026: estimator calibration shipped —
  method v2 multiplies the raw BPE-like split by a per-language-
  family factor (prose 0.85, python 0.86, ts-js 0.75, go 0.73,
  rust 0.89, c-family 0.87, json-data 0.95, minified-js 0.65),
  derived by measuring the raw split's implied chars/token on new
  golden corpora (tests/fixtures/calibration/, one sample per
  family) against published-anchor targets (OpenAI's ~4
  chars/token English rule anchors prose; code/data targets are
  documented denser approximations, tokens.py carries the table).
  New `ghostslice calibrate` report (raw vs calibrated per family;
  agrees with scan totals exactly, verified on GhostBus).
  GhostBus demo shift on the unchanged tree: 165,052 -> 129,555
  original, 53,339 -> 45,770 sliced estimated tokens; manifests
  and all surfaces now name the v2 method from one constant;
  budgets-migration note in README/CHANGELOG. Carried P0 fixed
  first: the config backstop now builds rewritten lines as
  original-indent + body by construction (probe battery could not
  reproduce the reported column-0 loss in the v0.9 build — every
  path already preserved indent — but the guarantee is now
  structural, a real adjacent defect (dropped `- ` marker on
  fallback rewrites) was fixed, and regression tests pin nested
  backstop-only/value-rule/key-rule lines). Tests 276 -> 293
  (17 new). Audit rounds (audits/G05_audit.md): round 1 headline
  fixes — tokens.py docstring family map corrected (notebook ->
  python), one-sample evidence limit stated, per-text minified
  family flip documented and pinned by a bundle-validation test.
  Round 2 headline fix — the docstring's measured v1 implied
  rates are now pinned by a test so corpus edits cannot silently
  invalidate the evidence table.
- G6 (v0.11.0) DONE Oct 13, 2026: context lint shipped — rule
  engine L001-L010 over modes from exporter.resolve_modes
  (extracted from build_bundle and shared with
  estimate_context_tokens, so lint judges exactly the exporter's
  selection; manifest-parity test pins it). Rules reuse graph
  recommendations (L003, duplicate-derived entries owned by
  L004), duplicates (L004), and the secret guard (L005, error
  severity, metadata only). Findings carry token cost, recoverable
  saving, and an action; totals union distinct files / max saving
  per file (no double-count). Exit codes: 1 on errors only,
  --strict promotes warnings, 2 for config/usage errors; profile
  "lint" section tunes severity (incl. off) + thresholds with
  loud validation of ids/severities/option names. Same payload on
  CLI --json, /api/lint, and MCP lint_project. Self-lint on this
  repo: 4 warns, all justified (intentional prices.json package
  duplicate; compact-JSON L006 shapes; the minified calibration
  fixture). GhostBus lint: no errors (its flagged keys were fixed
  earlier today). Tests 293 -> 334 (41 new). Audit rounds
  (audits/G06_audit.md): round 1 headline fix — L004 named the
  group's first file as the keep reference even when excluded;
  now names the first INCLUDED copy. Round 2 headline fixes —
  rule messages are the single source of the token cost (CLI no
  longer appends a duplicate "(est. ...)" suffix; L003/L005/L007
  messages gained their counts) and L006's message names the
  giant-line shape instead of overclaiming "minified". Known
  cost logged for G15: find_duplicates runs twice per lint
  (inside recommendations + for L004).
- G7 (v0.12.0) DONE Oct 13, 2026: detection shipped — new
  detect.py (generated header markers, minified = the estimator's
  own looks_minified verdict, vendored path segments + /*! */
  banners; evidence is metadata only, never content) wired into
  scanner flags (+detect_evidence), scan text/JSON, /api/scan,
  explain, and lint L006/L007 (which now consume detect.py instead
  of private copies). Opt-in auto-shrink (profile "auto_shrink" /
  export --auto-shrink / watch) excludes detected files whose mode
  came from the built-in defaults, recording manifest mode_reason;
  selections, profile modes, CLI --mode, and entry points always
  win; auto resolves before the fit ladder. GhostBus OFF totals
  unchanged (129,555 -> 45,770); ON excludes only one compact
  example JSON (-> 45,612). Tests 334 -> 370 (36 new). Audit
  rounds (audits/G07_audit.md): round 1 headline fix — a HIGH
  false positive: judging looks_minified on the 4KB head alone
  flagged hand-written GhostBus src/tools.mjs (dense TOOLS-array
  head, whole-file verdict False); the minified detector now
  judges the full text the scanner already read, and post-fix
  verdict agreement with the estimator is exact on both real
  trees. Round 1 also added entry-point protection for
  auto-shrink (fit parity). Round 2 reviewed the fixed state
  (caller inventory, protection interplay, manifest surface)
  with no new defects; its fixes were discoverability (profile
  docstring) and the docs set.
- G8 (v0.13.0) DONE Oct 13, 2026: monorepo support shipped — new
  workspaces.py detects package boundaries once per scan from
  root manifests (npm workspaces array/object + "!" negations,
  pnpm-workspace.yaml, Cargo [workspace] members/exclude,
  go.work use directives, uv workspace members), with a manifest
  fallback (top level + one below, the packages/<name> shape)
  labelled "detected" vs "declared"; outermost wins, `**` counts
  as one segment, escaping members are clamped with warnings,
  missing members are reported. Every FileEntry gains `package`;
  per-package subtotals (files / tokens / share, + sliced in
  bundles) land in scan text + --json (with a "workspace"
  evidence block), the export manifest (additive; old bundles
  still validate), /api/scan, and the HTML report. GhostBus
  unchanged: 129,555 -> 45,770, all files in the root package.
  Tests 370 -> 398 (28 new). Audit rounds (audits/G08_audit.md):
  round 1 headline fixes — detection missing/warnings were
  recorded but invisible on every surface (now in scan text +
  JSON), pnpm items at column 0 ended the list early, Cargo
  exclude removed explicitly listed members (now glob-only,
  per Cargo semantics), go.work/pnpm files now count as root
  evidence, `**` behaviour pinned. Round 2 headline fixes —
  a column-0 comment inside the pnpm list no longer ends it,
  and single-line flow-style `packages: [...]` is parsed;
  remaining TOML-lite limits and the all-or-nothing fallback
  reviewed and accepted.
- G9 (v0.14.0) DONE Oct 13, 2026: history analytics shipped —
  `history --trend` (per-run table with Δafter, $ saved per run and
  cumulative at the model's INPUT rate with the dated-snapshot
  label, mean/median saved %, best/worst, first→last context
  change, ASCII sparklines downsampled to 60 buckets), `--json`
  analytics payload (summary keys kept; runs_detail / aggregates /
  charts / corrupt_lines / estimator / model added), same payload
  on /api/history and the scan payload, and the HTML report embeds
  an inline-SVG savings chart (saved bars on a shared zero line,
  after-token line on its own labelled scale), the section absent
  when no ledger exists. Ledger records are now stamped
  `"estimator": "v2"` (tokens.METHOD_VERSION); any history that is
  not uniformly one stamped version gets an "Estimator mix"
  warning (pre-v0.14 unstamped records cannot be split v1 vs v2)
  on CLI, JSON, and report. Corrupt/non-object/non-numeric ledger
  lines are counted and skipped (the old reader crashed on a
  non-object line). Tests 398 -> 427 (29 new). Audit rounds
  (audits/G09_audit.md): round 1 headline fixes — cumulative $
  summed display-rounded per-run values and disagreed with the
  token-total $ (0.7620 vs 0.7619 on this repo's own ledger; now
  raw accumulation, equal by construction, pinned), runs/week
  extrapolated from sub-day spans was noise (now gated to spans
  >= 1 day; sub-day spans print as hours), after-change line
  formatting, and a tautological no-model test tightened.
  Round 2 verified the $ invariant on the real ledger and pinned
  best/worst tie -> earliest run and empty-ledger CLI --json;
  _input_cost docstring corrected.
- G10 (v0.15.0) DONE Oct 13, 2026: `ghostslice init` shipped —
  new entries.py ranks entry-point candidates by documented
  signals (npm bin / pyproject [project.scripts] +60, npm main
  +50, the prune engine's name heuristic +40, a Python __main__
  guard +35, a shebang +25, no-importers +10 as tie-breaker only;
  cap 5; test files and vendored/generated files are hard-excluded
  as candidates) and init_wizard.py turns the tool's own analysis
  into a profile with a printed justification per section:
  vendored trees (detect.py path evidence) -> ignore, all-generated
  dirs/files -> modes exclude, config-heavy dirs (>=70% config,
  >=3 files, >=500 est. tokens) -> modes structure, budget =
  default-sliced total x1.25 rounded up to 2 s.f. (omitted, with
  the number, under 5,000 sliced tokens), model only from --model,
  and NO lint section (documented: findings feed the top-3 wins
  instead). Safety: existing profile refused (exit 2 + contents
  summary) without --force, --dry-run writes nothing (fs-snapshot
  pinned), the written file round-trips through load_profile inside
  run_init, and a round-trip export test proves the modes/ignore
  take effect. TTY users confirm per section (defaults = the
  analysis; injected-input tested); non-TTY behaves as --yes and
  prints that it did. GhostBus dry-run: its three package.json bin
  commands top the ranking (135/95/95), budget 58,000 proposed on
  the 45,770 sliced basis, nothing written. Tests 427 -> 462
  (35 new). Audit rounds (audits/G10_audit.md): round 1 headline
  fixes — the __main__ guard moved from a whole-text regex to a
  module-level ast check (comments/strings/nested guards no longer
  nominate; regex fallback for unparseable files), config dirs
  under generated dirs no longer earn a fighting structure glob,
  an explicit --budget locks the interactive budget prompt, and
  every suggested mode glob is verified through Profile.mode_for
  before writing (fnmatch-metachar file names are dropped loudly).
  Round 2 headline fix — a .ghostslice.json that is a directory,
  or any unwritable target, is a clean exit 2 instead of a
  write_text traceback.
- G11 (v0.16.0) DONE Oct 13, 2026: XML + JSON bundle formats
  shipped — `anthropic-xml` preset writes context.xml (Anthropic
  <documents> shape: per-file <document> with source + escaped
  document_content and mode/token/sha256 attributes in manifest
  order, plus an <excluded> section with reasons for excluded and
  empty-slice files) and `json` preset writes context.json
  (project/generated_by/model/totals + per-file content), both
  rendered from build_bundle's single in-memory slicing pass so
  they cannot diverge from PROMPT.md/files. Escaping is
  ElementTree-only (no CDATA); XML-illegal characters become
  U+FFFD in context.xml only, files/ keeps canonical bytes.
  `ghostslice check` validates either artifact when present
  (parse, content vs the bundle's own slices, sha256 + totals vs
  manifest, exact file-set mirror; additive artifacts_checked),
  and wrapper overhead is measured on the artifact as written and
  reported in manifest wrapper_artifacts + the CLI — totals still
  count slices only. Tests 462 -> 488 (26 new). Audit rounds
  (audits/G11_audit.md): round 1 headline fix — the new validator
  crashed with AttributeError on a valid-JSON-but-wrong-shaped
  context.json; shape guards (_json_records) now make it report
  clean errors, never raise, with regression tests. Round 2 was a
  probe battery (wrong-typed values, duplicate documents, stray
  artifacts in plain bundles — presence validation confirmed
  deliberate) with no new defects; its fixes were the documented
  choices and the PRESETS/profile/CLI/README consistency guard.
- G12 (v0.17.0) DONE Oct 13, 2026: redact-in-place export shipped —
  `export --redact` (task/--fit/watch/MCP inherit; profile
  `"redact": true` + `--no-redact` override) replaces flagged
  values in the final slice text with `[REDACTED:<kind>:<fp>]`,
  fp = sha256[:8] for values >= 12 chars only (a short value's
  fingerprint would be a brute-force oracle; short values get the
  fingerprintless form). PEM findings replace the whole block.
  Same kind set --exclude-secrets judges (REDACTED_KINDS = every
  scanner kind; the scanner's gates are the severity filter);
  precedence when both are on: exclusion wins, redaction covers
  the rest, CLI prints it, unhandled kinds would surface as
  left_in_place, never silent. Manifest totals/hashes are
  post-redaction; per-file redactions/kinds + a top-level
  redaction block; `check` re-scans claimed bundles and fails on
  a surviving literal; ledger records gain "redactions".
  Tests 488 -> 525 (37 new). Audit rounds (audits/G12_audit.md):
  round 1 headline fix — a CRITICAL: comment-line secrets shipped
  (the guard's reporting scan skips full-line comments; a
  Markdown heading is `#`-prefixed content) — redaction and the
  validator now scan with comments=True (one core, documented
  knob; reporting surfaces unchanged), plus the fit block
  records redacted_after_tokens so --fit + --redact print one
  explained pair of totals. Round 2 headline fix — the goal's
  own test file tripped `ghostslice secrets .` with contiguous
  fake literals in its source; fixtures now assemble literals
  from parts (runtime values unchanged), guard exits 0.
- G13 (v0.18.0) DONE Oct 13, 2026: symbol-level slicing shipped —
  new module symslice.py outlines for all 14 outlined languages
  (Python via ast incl. nested/conditional defs, constants, class
  attributes; the rest reuse the slicer's parser-lite regexes and
  brace matcher), `ghostslice symbols` listing (name/kind/lines/
  estimated tokens, honest "no symbol outline" for notebook/
  markdown/config/text), and `export --symbols` (+ MCP symbols
  array): bare names, qualified names with suffix matching
  (Store.total reaches Shop.Store.total; C++ Store::total),
  file.py:name scoping (a colon scopes only when its left side
  names a scanned file), and globs. Matched files ship mode
  "symbols": requested bodies + always-context + class shells +
  collapsed signatures; unmatched files excluded except profile
  entry points (mode kept); cross-file ambiguity includes ALL
  matches and is printed/reported; an unmatched entry is a hard
  exit 2 with near-miss suggestions before anything is written;
  --exclude-secrets still wins (excluded_by_secrets), --redact
  and presets compose, --fit is rejected in combination.
  Manifest gains the top-level symbols report + per-file
  symbols_included; PROMPT.md sections headed with the list.
  Tests 525 -> 555 (30 new). Audit rounds (audits/G13_audit.md):
  round 1 headline fix — conditionally-defined Python symbols
  (if/else, try/except, match, TYPE_CHECKING) were outlined and
  matched but silently dropped by the renderer; all three Python
  renderers now recurse into compound statements (kept bodies
  ship, unkept signpost). Round 2 headline fix — Kotlin/Swift
  properties and PHP fields were missing from outlines though
  signatures mode keeps them and task selection counts them;
  they are outline symbols now (verbatim data context).
- G14 (v0.19.0) DONE Oct 13, 2026: Python call graph shipped —
  new callgraph.py (AST edges between symslice symbols, labelled
  exact / heuristic / attribute; references count as calls do;
  class instantiation edges to __init__) behind `ghostslice
  calls [file] [--json] [--dead]`, with dead-function candidates
  merged as kind "dead-symbol" into the scan/graph prune
  recommendations at the CLI surface only (the shared
  recommendations function and lint are unchanged). Roots:
  module top levels, profile entry points (full trust) vs
  heuristic entry files (only a function named main),
  [project.scripts], __all__, test files + conftest, framework
  decorators, and methods of classes extending non-project
  bases; dunders, unparseable files, and direct self-recursion
  exempt; getattr-style dispatch flagged by design under the
  honesty line. Self-repo dogfood: 44 candidates at build, 0
  after the audit fixes — the 44 read as 38 downstream of the
  missing __init__ edge, the http.server Handler family, and
  three test-only-called public helpers (one, a private helper
  unused in src since G2, a true positive whose unit test is
  its caller). Tests 555 -> 590 (35 new). Audit rounds
  (audits/G14_audit.md): round 1 headline fixes — instantiation
  never reached __init__ (whole subtrees flagged), framework
  protocol subclasses flagged, heuristic entry files rooted
  everything in them (app.py!), src-layout absolute imports
  unresolved, and the unresolved counter drowned in stdlib
  method calls. Round 2 headline fix — template-method
  overrides flagged because self. calls resolved exact-only;
  self./cls. calls now fan out to subclass overrides.
- G15 (v0.20.0) DONE Oct 13, 2026: performance shipped — new
  cache.py: a per-project .ghostslice-cache memoizes scan
  derivations, slice results, symbol outlines, and symbol-slice
  renders, keyed by sha256 of every input (content, path, mode /
  keep-set, tool version, estimator version); atomic stores,
  corrupt-reads-as-miss, 256 MiB oldest-first cap, `cache
  stats|clear`, GHOSTSLICE_NO_CACHE / --no-cache, and --timing
  phase breakdowns on scan/export. Bundles are byte-identical
  cache off/cold/warm at any worker count (whole-tree diffs,
  hash-seed and racing-writer probes in audits/G15_audit.md);
  one changed file in the 2,000-file tree misses exactly its own
  2 entries. Parallel slicing (--workers) shipped but defaults
  to 1: measured no faster under the GIL (2 workers ~+5% cold =
  noise, 4 lost, warm runs slower threaded) — the cache is the
  win: paired local medians, synthetic export 4.38s -> 0.65s
  warm, repo export 2.61s -> 0.085s, scans ~3-5x (BENCHMARKS.md,
  labelled local + sandbox-noisy). Tests 590 -> 614 (24 new).
  Audit rounds: round 1 — in-flight store temp files matched the
  *.json eviction/stats walks (renamed to .part + stale-temp
  sweep) and the export CLI's warning pre-scan bypassed the
  cache (now shares it); the poison probe pinned the trust model
  in README (cache is trusted derived data; secrets/redaction
  always run on final text). Round 2 — no defects (hash-seed
  determinism, bundle-diff zero-change, precise incrementality
  all probed); improvements were ms-precision timing output and
  the checked-in BENCHMARKS.md. Round 2's verification tail
  caught a real one in round 1's own fix (F6): the stale-temp
  sweep walked the cache tree per store, making cold fills
  quadratic (fill 14.8s CPU under load -> 3.1s after throttling
  the sweep to every 512 stores); the suite's speedup test now
  times process CPU (paired ~5x) instead of the sandbox's
  weather-vane wall clock, and the big-tree tests were made
  disk-lean after /tmp filled to 100% during one loaded run.
