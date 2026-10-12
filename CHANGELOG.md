# Changelog

All notable changes to GhostSlice. Versions follow the build waves;
token counts are estimates everywhere (see README).

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
