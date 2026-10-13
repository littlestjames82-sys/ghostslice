# GhostSlice v0.5.0 — Build Report

Date: 2026-10-13. Baseline: v0.4.0 at commit 7893233, 109 tests passing.
Result: **149 tests passing** (109 baseline + 40 new in
tests/test_v05.py; no existing test was changed or weakened — the task
score type change to float is absorbed by the existing assertions,
which only require `> 0`). Zero dependencies added; Python stdlib
only. No PyPI publish, no announcements, no GitHub push (local commit
only, parent verifies first).

## What shipped, per item

1. **Auto-fit budget export** (`src/ghostslice/fit.py`, `--fit N` on
   `export` and `task`)
   - Ladder: full -> signatures -> interfaces -> exclude
     (strip-tests/headings sit at the interfaces rung; their next rung
     is exclude). A rung that would not actually save tokens for a
     file is skipped over (e.g. `interfaces` on JSON returns the full
     text, so the file jumps to the first rung that saves).
   - Order (deterministic): lowest value density = files with no
     importers (import graph) first, then largest current sliced
     size, then path ascending; one effective rung per pick, repeated
     until the total fits or nothing can move.
   - Protections: entry points (profile `entry_points`, else the
     graph name heuristic) are never auto-excluded (interfaces is
     their floor); files moded by the project profile are never
     downgraded; caller `selections` are protected by default
     (`fit_protect_selections=True`). The task CLI passes False
     because its selections are machine-resolved, not user-explicit —
     profile modes stay protected there too.
   - Honest failure: if it cannot fit, the bundle is still written,
     a warning goes to stderr, the manifest `fit` report records
     `fitted: false` with the best achievable total, and the CLI
     exits 1. On success the exit code is 0 (validation permitting).
     `check-budget` is untouched.
   - The manifest gains a `fit` object: target, before/after totals,
     fitted flag, per-transition step counts, and the per-file
     downgrade list.

2. **TF-IDF task selection** (`selection.py`)
   - Score = sum over task keywords of (min(tf, 20) * idf) for
     content plus 5 * path hits * idf for the path, with smoothed
     idf = ln((1 + N) / (1 + df)) + 1 across the project's
     non-lockfile files. Content matching is now whole-word
     tokenisation (was substring counts). Scores are floats
     (rounded to 4 dp); sort order and budget behaviour unchanged.
   - Golden A/B test: 10-file corpus, `alpha` in all 10 files
     (idf 1.0) vs `omega` in one (idf ~2.7). Raw counts rank the
     5-hit common-word file first (5 vs 4); TF-IDF ranks the
     rare-word file first (9.11 vs 5.0). Asserted, plus path-boost
     and the pre-existing billing selection still pass.

3. **PHP, Ruby, Kotlin, Swift slicers** (parser-lite, `slicer.py`)
   - PHP: functions/classes/interfaces/traits/enums/properties;
     strip-tests drops test-prefixed methods, `/** @test */` docblock
     methods, and `#[Test]` methods.
   - Ruby: def/class/module blocks tracked by opener keywords and
     closing `end` (no braces); keeps attr_*/include/constants;
     strip-tests drops `def test_*` and describe/context/it blocks.
   - Kotlin: fun/class/interface/object, val/var; strip-tests drops
     @Test and test-prefixed functions.
   - Swift: func/class/struct/protocol/enum/extension, var/let;
     strip-tests drops test-prefixed XCTest functions and @Test.
   - All reuse the v0.4 string/comment-aware `_brace_end` (char-
     literal heuristic extended to kotlin/swift). Each language has
     golden signatures/interfaces/strip-tests tests plus an
     adversarial case: PHP `"}"`/`'{'` strings + `// }` comment,
     Ruby multi-line hash literal + `"end of the road"` string,
     Kotlin `"}"` + `"${...}"` template, Swift `"}"` + apostrophe
     comment — the following declaration must still slice.
   - Wiring: scanner language map (.php/.rb/.kt/.kts/.swift),
     test-file conventions (`StoreTest.php`, `StoreTests.swift`,
     `*_test.rb`; `latest.php` correctly NOT a test), exporter
     SLICABLE defaults, `slice` CLI language set (now SLICABLE +
     markdown), `explain` default-mode wording, selection
     resolve_mode (now uses SLICABLE). The import graph still only
     parses Python and TS/JS imports, so graph prune recommendations
     remain scoped to those languages (unchanged behaviour).

4. **Bundle diff** (`src/ghostslice/bundlediff.py`, `ghostslice diff`)
   - Validates both bundles first; a bundle that fails validation is
     named and the CLI exits 1. Otherwise: added/removed files,
     per-file mode changes with original and sliced token deltas,
     totals delta, unchanged count; `--json` supported. Exit 0 for
     any two valid bundles.
   - Tests: identical bundles diff empty; a default_mode=full bundle
     shows the mode change and positive sliced delta; added/removed
     both directions; a tampered bundle file makes the CLI exit 1.

5. **Presets `cursor` + `copilot`** (profile PRESETS + exporter)
   - cursor: prompt.md (copy of PROMPT.md) + README.txt explaining
     paste into Cursor chat / @-attach files/ / keep as
     `.cursor-context`. copilot: prompt.md with an instruction
     header and one `## File:` section per sliced file with a
     language-fenced code block. claude-code/aider/generic output is
     byte-identical in behaviour to v0.4. Tests assert the artifacts
     exist, content markers, manifest preset, and `ghostslice check`
     still validates. MCP `export_bundle` preset enum now follows
     PRESETS (tool names/count unchanged).

6. **Dashboard treemap** (`dashboard.html`)
   - List/Treemap toggle in the files card; list remains the default
     and untouched. Treemap is a squarified layout, grouped by
     top-level directory with group labels, leaves sized by
     estimated (original) tokens, filled with the existing heat
     palette colour by share of the largest file, excluded files
     dimmed like the list. Tooltip (title) shows path + tokens +
     mode; the label shows basename + tokens when the rectangle is
     big enough. Click toggles include/exclude through the same
     state as the list checkbox and re-renders both views; resize
     re-layouts. Vanilla JS, inline only, no external assets.
   - Server tests assert `/` 200 containing the treemap container and
     toggle, and that /api/scan and /api/secrets are unchanged; the
     server code itself is untouched (API unchanged by design).

## Demo: GhostBus (~/workspace/ghostbus, read-only)

- Scan: 42 files, **165,052** estimated original tokens (was
  164,988 in v0.4). Export via API (`record_history=False`, bundle
  in /tmp, GhostBus tree untouched): 165,052 -> **53,339** sliced
  estimated tokens, validation OK.
- The +64 original-token delta is fully explained by the parallel
  GhostBus key fix that landed after the v0.4 demo: the two flagged
  dummy-key literals in `deploy/netlify/test-lib.mjs` and
  `scripts/load-bench.mjs` were replaced with longer labelled
  placeholders (`test-admin-key-two-not-a-real-secret`,
  `bench-admin-key-not-a-real-secret`), which tokenise higher.
  Sliced output is byte-equivalent in total (53,339, unchanged)
  because those lines sit in stripped test/bench content. Saved
  total therefore reads 111,713 (was 111,649; same +64).
- The v0.4 secret guard now reports **0 findings** on GhostBus: the
  labelled placeholders do not flag, by design. The guard's own repo
  scan is also clean (`ghostslice secrets .` in ghostslice exits 0).

## Dashboard smoke (fixture project in /tmp)

`ghostslice serve` on a 2-file fixture: `/` 200 (page contains the
treemap markup), `/api/scan` 200, `/api/secrets` 200.

## Tests

- Before: 109 passed. After: **149 passed**
  (`PYTHONPATH=src python3 -m pytest tests -q`).
- New file `tests/test_v05.py`: 40 tests — fit noop / reduce /
  entry-point floor / profile protection / determinism / CLI exit
  codes / task-bundle fit; TF-IDF rare-word ranking, path boost,
  billing regression; per-language golden signatures, interfaces,
  strip-tests, adversarial (16) + language detection, test-file
  conventions, export defaults; bundle diff identical / mode-change
  / added-removed / invalid-exit-1; cursor + copilot presets,
  profile acceptance, MCP enum, CLI preset; dashboard treemap
  markup + API stability.

## Known limitations

- Fit's "value density" is the documented heuristic (importers,
  size, path), not a semantic value judgement; the downgrade list
  in the manifest is the audit trail.
- The new lite slicers assume conventional formatting: one
  declaration per line, opening brace on the declaration line
  (PHP/Kotlin/Swift); Ruby assumes `end` closes at the opener's
  block depth, so endless methods (`def x = 1`), one-line
  `def x; end`, and heredocs can slice imperfectly. PHP heredocs
  and Kotlin raw strings (`"""..."""`) can confuse brace matching
  the same way regex literals already could.
- TF-IDF tokenises on [a-z0-9_]+ words; keywords with punctuation
  or camelCase compounds may need to be given as separate words.
- The treemap sizes leaves by original estimated tokens (stable
  across mode changes); the list remains the place for per-mode
  token detail.

## Files changed

- New: `src/ghostslice/fit.py`, `src/ghostslice/bundlediff.py`,
  `tests/test_v05.py`, `BUILD_V05_REPORT.md` (this file).
- Modified: `src/ghostslice/slicer.py` (PHP/Ruby/Kotlin/Swift lite
  slicers + dispatch, char-literal heuristic extended),
  `src/ghostslice/scanner.py` (language map, .kts, test-file
  conventions), `src/ghostslice/selection.py` (TF-IDF scoring,
  SLICABLE-based resolve_mode), `src/ghostslice/exporter.py`
  (SLICABLE + fit integration + cursor/copilot presets),
  `src/ghostslice/cli.py` (--fit on export/task, diff command,
  float score format, SLICABLE-based language lists),
  `src/ghostslice/profile.py` (PRESETS += cursor, copilot),
  `src/ghostslice/mcp_server.py` (preset enum follows PRESETS),
  `src/ghostslice/dashboard.html` (treemap view + toggle),
  `src/ghostslice/__init__.py` + `pyproject.toml` (version 0.5.0),
  `README.md`, `CHANGELOG.md`.

Not done (separate Ryan gates, untouched): no GitHub push, no PyPI
publish, no announcements.
