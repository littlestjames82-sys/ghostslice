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
| G5 | Token estimator calibration: per-language factors, golden corpora, `calibrate` report | v0.10.0 | pending |
| G6 | Context lint: rule engine for context waste (oversize, generated, vendored, minified, giant lines) | v0.11.0 | pending |
| G7 | Generated/minified/vendored detection wired into scan, graph, export (opt-in auto-modes) | v0.12.0 | pending |
| G8 | Monorepo support: workspace detection (npm/Cargo/go/pyproject), per-package subtotals everywhere | v0.13.0 | pending |
| G9 | History analytics: trends, per-model $ saved, ASCII chart, JSON export + savings-history chart embedded in the HTML report (Ryan's mockups, Oct 13) | v0.14.0 | pending |
| G10 | `init` wizard: analyze a project and generate a tuned .ghostslice.json (non-interactive --yes mode) | v0.15.0 | pending |
| G11 | New bundle formats: Anthropic-style XML bundle + JSON bundle presets | v0.16.0 | pending |
| G12 | Redact-in-place export: --redact-secrets replaces secret values with placeholders instead of excluding files | v0.17.0 | pending |
| G13 | Symbol-level slicing: keep named symbols + their in-file dependencies (Python ast, TS lite) | v0.18.0 | pending |
| G14 | Python call graph: function-level graph, entry-point reachability, dead-function candidates | v0.19.0 | pending |
| G15 | Performance: scan caching (.ghostslice-cache), parallel scan, benchmark proof, identical totals | v0.20.0 | pending |
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
