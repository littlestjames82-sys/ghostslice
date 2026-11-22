# GhostIndex v0.1 - seam fix report (ecosystem pass seam #8)

Seam: search results were silently capped by the default limits.
Found by the Oct 14, 2026 ecosystem pass (record in
`~/workspace/ghostslice-companions/ECOSYSTEM.md`, Seams #8): on the
34-codebase index, queries with 63 and 409 true matches returned
exactly the capped number of hits, in output that read as a complete
result set. No existing test was edited or weakened; the fix is in
`src/ghostindex/search.py` and `src/ghostindex/cli.py`, plus README
wording and one new test file.

## Before (reproduced)

On a 30-file corpus where every file matches `capterm`, a default
search returned:

- `--json`: 10 hits, top-level keys only `estimator`, `hits`,
  `query`. No total, no cap indication anywhere.
- Human output: `10 hit(s) for 'capterm' (token figures are
  estimates)` - the count of a partial result presented as the
  result.

## Root cause

`search()` in `src/ghostindex/search.py` applied three caps (the
hit `limit`, the result-set `total_tokens` budget dropping
candidates, and the `per_hit_tokens` budget trimming excerpts inside
`_build_hit`) and reported none of them. The CLI printed
`len(hits)` as the headline count, so a capped list was
indistinguishable from a complete one in both output modes.

## Fix

Honesty, not bigger defaults: every limit value is unchanged.

`src/ghostindex/search.py`:

- `search()` now runs an FTS5 `COUNT(*)` over the same MATCH
  expression and root filter as the hit query, so the exact number
  of matching files is always known (docs rows are 1:1 with files).
- It returns a `SearchResult`, a `list` subclass that behaves
  exactly like the hit list it replaces and additionally carries
  `total_matches`, `capped_by` (drawn from `"limit"`,
  `"total_tokens"`, `"per_hit_tokens"`, in that order), the
  effective `limits`, and a `capped` property / `summary_dict()`.
  The hit-selection loop is byte-for-byte the same logic; the only
  additions are bookkeeping (a `budget_skipped` flag) and the
  derivation of `capped_by` from it.
- `Hit` gains `excerpt_truncated`, set inside `_build_hit` wherever
  the per-hit budget actually cuts: windows dropped at the budget,
  lines trimmed from an over-budget window, lines changed by
  within-line capping, and a name-only head stopped early by the
  budget. It is included in `Hit.as_dict()`.

`src/ghostindex/cli.py`:

- `--json` search output gains `total_matches`, `shown`, `capped`,
  `capped_by`, and `limits` alongside the existing keys.
- Human output heads with `N of M matching file(s)` and, when
  capped, a `note:` line naming each limit that bound (with its
  flag and value) and the shown/total counts. A shortened hit is
  marked `excerpt shortened by the per-hit token cap` on its own
  lines.
- `stats` and `doctor` (text and `--json`) now report
  `search_defaults` read from the same `search.py` constants via a
  single helper, so they agree with the `limits` echo in search
  output by construction.

`README.md`: the search-options paragraph and the results-shaping
section now state the contract (totals always, caps named, per-hit
shortening marked, `search_defaults` in stats/doctor).

## After (same 30-file corpus, verified by hand)

- `--json` defaults: `total_matches: 30, shown: 10, capped: true,
  capped_by: ["limit"], limits: {limit: 10, total_tokens: 2000,
  per_hit_tokens: 200}`.
- Human defaults: `10 of 30 matching file(s) for 'capterm'` plus
  `note: results capped by hit limit (--limit 10). Showing 10 of 30
  matching files; raise the limits to see more.`
- `--limit 50 --max-tokens 40`: `capped_by: ["total_tokens"]`,
  shown 2 of 30.
- A single heavily-windowed file: `total_matches: 1, shown: 1,
  capped_by: ["per_hit_tokens"]`, hit carries
  `excerpt_truncated: true`.
- Uncapped runs report `capped: false`, `capped_by: []`, and
  `total_matches == shown`. No-match still exits 1.

## Tests

- New: `tests/test_search_caps.py`, 7 tests, all black-box CLI:
  limit cap reports the true total and reason (JSON, human output,
  and under `--root`), token-budget cap names `total_tokens`,
  per-hit cap flags the excerpt in both modes, an uncapped search
  reports itself complete, and stats/doctor `search_defaults`
  agree with each other and with the search `limits` echo.
- Before: 49 passed. After: **56 passed, 0 failed** (49 existing,
  unmodified, plus the 7 new).
- Ranking and excerpt behaviour for uncapped queries is unchanged:
  the selection loop and excerpt builders were not altered, and the
  existing excerpt/ranking/budget tests pass untouched.

## Gates held

No version bump (still 0.1.0), stdlib only, no push, no PyPI, no
announcements, no spend.
