# GhostSlice — Publish + Build-Out Report

Completed Oct 12, 2026, on Ryan's words: "Publish GhostSlice to GitHub
like the other Ghost tools" then "build the hell out of it."
Zero-dependency Python stdlib only throughout. No PyPI publish, no
announcements (separate gates).

## Part 1 — v0.1.0 published

- Repo: https://github.com/littlestjames82-sys/ghostslice (public, MIT
  license detected by GitHub, default branch main)
- Topics: ai-agents, claude-code, context-engineering, developer-tools,
  llm, python, token-optimization
- Push route: Git Data API via the studio GitHub skill CLI credentials
  (seed Contents-API README commit, then full tree). Remote tree
  verified blob-for-blob against local `git ls-files`: **26/26 files**,
  commit 5b01f3f.
- Release: https://github.com/littlestjames82-sys/ghostslice/releases/tag/v0.1.0
  (notes carry the real demo: GhostBus 164,988 -> 53,339, 67.7%)

## Wave v0.2.0 — core build-out

Shipped (all tested):
1. **Import/dependency graph** — Python `ast` imports + TS/JS parser-lite
   import/require/dynamic-import resolution to project files. Prune
   recommendations (unreachable from entry points, or no importers when
   no entry points are known; tests/docs/config/lockfiles excluded) in
   `ghostslice scan`, new `ghostslice graph`, dashboard `/api/graph`
   plus a recommendations panel and profile/history in `/api/scan`.
2. **Task-focused context** — `ghostslice task --task "words"`: keyword
   scoring (path hits weigh 5x, content hits capped) with selection by
   *sliced* tokens within a budget, best file always included.
   `--diff`: git-changed files (porcelain + diff HEAD, untracked incl.)
   plus direct dependencies (imports and importers). Both export a
   validated bundle with everything else recorded as `exclude`.
3. **Profiles** — `.ghostslice.json` auto-loaded: ignore globs, per-glob
   modes, model, budget_tokens, entry_points, preset. Mode precedence:
   explicit selections > profile > --mode > built-in defaults.
4. **Nested .gitignore** — per-directory files loaded during the walk,
   rules scoped to their subtree; nested negations override parent
   rules (documented simplification of git semantics).
5. **Budget gate** — `ghostslice check-budget` exits 1 over budget, 2
   with no budget configured. GhostBus check: 53,339 sliced tokens
   passes 60,000, fails 10,000 (verified live).
6. **Repo polish** — GitHub Actions CI (3.10/3.11/3.12), bug/feature
   issue templates, PR template, README badges + v0.2 sections,
   CHANGELOG.md.
- Also: export **presets** (claude-code default; aider = aider-files.txt
  plain file list documented as such; generic = prompt.md) and the
  **savings ledger** (item 9 from the v0.3 list, shipped early):
  exports append to `.ghostslice-history.jsonl`, `ghostslice history`
  and the dashboard total savings per project.
- Tests: **64 passed** (48 in v0.1 + 16 new).
- Push verified blob-for-blob: **36/36 files**, commit 5cd4008.
  Note: the first two push attempts died on dropped connections
  (RemoteDisconnected); per-request retries were added to the push
  script and the third attempt verified clean. Orphaned blobs from the
  failed attempts are unreachable and harmless.
- Release: https://github.com/littlestjames82-sys/ghostslice/releases/tag/v0.2.0
- Demo: GhostBus export unchanged, 164,988 -> 53,339 (67.7%). The graph
  flags 13 review candidates on GhostBus, including config-wired files
  (e.g. the hosted server entry) that look unreachable from code
  imports alone — exactly why recommendations say "review", never
  "delete".

## Wave v0.3.0 — MCP + more languages

Shipped (all tested):
7. **MCP server** — `ghostslice mcp`, stdlib stdio JSON-RPC
   (newline-delimited), tools: scan_project, slice_file, estimate_cost,
   export_bundle. Tested as a pure handler and end-to-end over a real
   stdio subprocess running all four tools.
8. **Go, Rust, Java, C# slicers** (parser-lite, labelled as such):
   signatures + interfaces modes, test stripping (Go Test/Benchmark/
   Example/Fuzz functions, Rust #[test] + #[cfg(test)] mod tests,
   Java @Test methods, C# [Test]/[Fact]/[Theory] methods), golden
   tests per language, including a Rust regex group bug and a C#
   namespace-brace fix found during verification. New languages are
   slicable in export defaults and the CLI.
9. **Savings ledger** — already shipped in v0.2.0 (see above); verified
   live on GhostBus in this wave: one export recorded 164,988 ->
   53,339 / 111,649 saved (demo ledger file removed afterwards).
- Tests: **77 passed** (64 + 13 new).
- Push verified blob-for-blob: **38/38 files**, commit e30df11.
- Release: https://github.com/littlestjames82-sys/ghostslice/releases/tag/v0.3.0

## Patch v0.3.1 — CI caught a real v0.1 bug

The new CI matrix failed on Python 3.10 and 3.11 while 3.12 passed:
`_is_type_alias` in the Python slicer touched `ast.TypeAlias`, which
only exists on 3.12+ — a latent v0.1.0 crash on older Pythons whenever
a module-level assignment was sliced. Fixed with a getattr guard,
verified locally by simulating the missing attribute, pushed (38/38,
commit 862238c), released as v0.3.1, and the CI run for that commit is
**green on all three Python versions**.
Release: https://github.com/littlestjames82-sys/ghostslice/releases/tag/v0.3.1

## Verification summary

- Full suite after each wave: 48 (v0.1) -> 64 (v0.2) -> 77 (v0.3/v0.3.1),
  `PYTHONPATH=src python3 -m pytest tests -q`.
- Dashboard re-curl-verified after each wave: `GET /` 200, `/api/scan`,
  `/api/graph`, `/api/history`, `/api/prices`, `/api/preview`,
  `POST /api/export` all correct.
- GhostBus demo numbers did not change across waves: scan 42 files /
  164,988 estimated tokens; export 53,339 (67.7% saved), $0.4950 ->
  $0.1600 at the local dated Sonnet snapshot.
- Local git: 886d0eb (v0.1.0), fee76cb (v0.2.0), daaad20 (v0.3.0),
  plus the v0.3.1 fix commit. Remote heads differ from local SHAs
  because the Git Data API creates fresh commits with identical trees;
  tree verification is blob-for-blob in every case.

## Honest limitations (unchanged or new)

- Token counts are estimates; prices are a dated local snapshot.
- TS/JS and the four new languages are parser-lite: conventional
  formatting slices well; exotic syntax (braces in template literals,
  multi-line generics, unusual C# layouts) can slice imperfectly.
- Prune recommendations are heuristics: config-wired and dynamically
  imported files can look dead. They are labelled for review.
- Nested .gitignore semantics are a close simplification, not a full
  git implementation (e.g. no per-file re-inclusion under an excluded
  directory edge cases).
- Task keyword selection is literal keyword scoring, not semantic
  search; embeddings remain a possible future wave, deliberately not
  faked here.
- Nothing was published to PyPI and no announcements were made; both
  remain separate Ryan gates.
