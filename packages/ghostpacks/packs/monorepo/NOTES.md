# Monorepo pack - tuning notes

Status: unscored. No GhostBench report backs this pack yet, so its
savings are unmeasured. Run Bench Tier A on a stated reference project
before claiming any score in pack.json.

Built on GhostSlice workspace detection (npm, pnpm, Cargo, go.work,
uv): this pack assumes packages/*/src and apps/*/src layouts and
leaves per-package subtotals to the scanner.

Choices:
- Per-package source at signatures so one package's work does not pay
  for every sibling package in full.
- Build output ignored at any depth: node_modules, dist, build,
  target, .turbo and .next caches in every workspace member.
- Tests stripped, changelogs and docs at headings: history gives
  orientation, not context bulk.
- Budget is a default suggestion (100000) for a multi-package tree,
  not a measured finding. Per-project budgets should override it.
