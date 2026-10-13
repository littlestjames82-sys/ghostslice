# Changelog

All notable changes to GhostSlice. Versions follow the build waves;
token counts are estimates everywhere (see README).

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
