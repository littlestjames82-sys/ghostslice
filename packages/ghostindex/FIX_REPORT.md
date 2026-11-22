# GhostIndex v0.1 - D1 fix report (parent-directed)

Defect: REPORT_B.md D1 - a single very long line defeated the per-hit
excerpt cap (200 est. tokens). No tests were edited or weakened; the
fix is entirely in `src/ghostindex/search.py`.

## Root cause (confirmed)

`_build_hit` trimmed over-budget windows line-by-line only. For a
one-line window it appended that whole line and stopped, so no
within-line truncation ever happened and the cap was unenforceable
for long lines (minified bundles, generated one-liners).

## Fix

Three helpers added in `src/ghostindex/search.py`, wired into both
excerpt paths in `_build_hit` (match windows and the name-only head):

- `_anchor_for(line, query)` - earliest (position, length) where a
  query term matches a line, mirroring `_term_predicates` semantics:
  plain terms as substrings of the lowered line, trailing-* terms as
  the first word they prefix.
- `_truncate_line(text, query, budget, language)` - when a line alone
  exceeds the budget, keeps the largest slice around the anchor whose
  estimated tokens fit (binary search, markers included in the
  estimate). The full matched term is always inside the slice. Each
  cut end is marked visibly with `...` (module constant
  `TRUNCATION_MARKER`), so the excerpt never pretends to be the whole
  line; kept text on both sides of a marker is verbatim. If even the
  bare term plus markers exceeds a tiny budget, that minimal anchored
  slice is returned as a floor (same spirit as the line trim keeping
  at least the match line). A line with no anchor is cut from the
  start.
- `_cap_lines(wlines, budget, query, language)` - enforces the budget
  across a window's lines: lines are kept whole while they fit; a
  line that does not fit is truncated within the line, except a
  context line ahead of a not-yet-kept match line, which is skipped
  so the remaining budget is spent on the match itself.

`_build_hit` now applies `_cap_lines` whenever a window (or the
name-only head) is still over `per_hit_tokens` after the existing
line-granular trim, and recomputes the estimate from the final window
text, so `excerpt_tokens_est` always describes the excerpt actually
returned. The global `--max-tokens` behaviour is untouched (it maps
to the total budget in `search()`, as before).

## Manual repro (fixture `tests/fixtures/project_alpha`, term
`needlelongline`, index in /tmp, `search --json`)

Before fix:
- 1 window, 10,073 chars, `excerpt_tokens_est` 2168,
  `file_tokens_est` 2168 (the "excerpt" was the whole file).

After fix:
- 1 window, 916 chars, `excerpt_tokens_est` 200 (exactly the per-hit
  cap), `file_tokens_est` 2168.
- The term `needlelongline` is present and anchored (x-padding kept
  before it, y-padding after), both cut ends marked `...`, and no
  2,000-char padding run appears anywhere in the output.

Direct unit spot checks of `_truncate_line` (budget 200): centre
match 913 chars with markers both ends; prefix query `needle*`
anchors identically; term at line start keeps the term at the start
with a trailing marker only; term at line end symmetric; a no-anchor
line is cut from the start; a budget of 1 token still returns the
anchored term as a floor (22 chars).

## Suite

`python3 -m pytest tests -q` from `~/workspace/ghostindex/`:

- Before: 44 passed, 1 failed
  (`tests/test_excerpts.py::test_excerpt_from_a_very_long_line_is_bounded`).
- After: **45 passed, 0 failed** - confirmed on two consecutive full
  runs (10.9s, 12.0s).

Files changed: `src/ghostindex/search.py` only, plus this report.
Gates held: stdlib only, local only, no network, no push/publish,
no spend.

Note for the parent: README.md's honest-limits section still states
the D1 long-line limit as a known defect. That wording is now stale
(the cap holds; the honest limit that remains is that a truncated
line shows only the neighbourhood around the first match). README is
outside this fix's ownership, so it was not edited here.
