# GhostAtlas — merge of harden + polish + deepen lanes

Date: 2026-10-18. Merger worker. Pristine tree `~/workspace/ghostatlas/`
was never edited; merged tree is a fresh copy of pristine with lane
changes applied in order harden, then polish, then deepen.

## Method

- Read all three lane IMPROVE.md files first.
- `diff -rq` of each lane against pristine identified every changed file.
- Files changed by only one lane were copied from that lane.
- Files changed by multiple lanes were combined with `git merge-file`
  (three-way, pristine as base, applied lane-by-lane in the required
  order). Every merge returned rc=0 with no conflict markers, because
  the lanes touched disjoint regions of each shared file. Each merged
  file was then spot-checked by grep to confirm BOTH (or all three)
  lanes' changes are present, and all sources parse.
- No IMPROVE.md was copied into merged (verified: none present).

## Files by lane

### Harden only (copied)
- `src/ghostatlas/config.py` — title/audience_notes collapsed to one line (Markdown injection guard).
- `tests/test_harden.py` — NEW, 11 regression tests.

### Polish only (copied)
- `README.md` — rewritten/expanded documentation.
- `examples/README.md`, `examples/demo.sh`, `examples/diligence.sh` — expanded comments/docs.
- `src/ghostatlas/__main__.py` — module docstring only.

### Deepen only (copied)
- `tests/test_test_coverage.py` — NEW, 15 tests for static test linkage.

### Harden + Polish (hand-verified three-way merge, no conflicts)
- `src/ghostatlas/cli.py` — harden: `--brief`/`--json-out` create parent
  directories. Polish: module docstring, parser help/epilogs, docstrings.
  Disjoint regions (polish at top/parser, harden in `main` write path).
- `src/ghostatlas/engine.py` — harden: gitignore last-match-wins negation,
  `from . import x` resolution + level clamp, JS/TS explicit-extension and
  `.js`->`.ts` resolution, `_looks_generated` marker semantics, line-count
  trailing-newline fix. Polish: docstrings only. Disjoint regions.
- `src/ghostatlas/reading.py` — harden: `dead_zones` normalises None
  reason/tokens. Polish: `reading_minutes` docstring. Disjoint regions.

### Polish + Deepen (hand-verified three-way merge, no conflicts)
- `src/ghostatlas/brief.py` — polish: docstrings for `checked_box_lines`
  and `build_brief`. Deepen: static-test-linkage "Checked:" line, covering-
  shape block in `_test_lines`, one-line linkage summary in diligence lines.
- `src/ghostatlas/render.py` — polish: docstrings for `_svg` and
  `build_html`. Deepen: "Test layout" HTML section (`test_section`) and
  its insertion into the page template.

### Harden + Polish + Deepen (hand-verified three-way merge, no conflicts)
- `src/ghostatlas/data.py` — all three lanes, disjoint regions:
  - Harden: complete hidden-paths purge (packages recomputed, duplicates,
    lint incl. message text, secrets summary recomputed from retained
    findings, call chains, git per-file at the end via the `removed` set),
    go.mod `require ( ... )` block parsing, requirements.txt option/URL
    lines skipped, doubled `ghostatlas:` error prefix dropped.
  - Polish: docstrings only (`_read`, `_git`, `AtlasData` + its methods,
    `build_atlas_data`).
  - Deepen: `test_linkage()` + `CODE_LANGUAGES`/`_stem_of`/
    `_test_target_stem` helpers, `test_coverage` field on `AtlasData`
    (included in `to_dict()`), computed in `build_atlas_data()` after
    per-file enrichment and hidden-path filtering.
  - Ordering verified in the merged file: hidden-path purge runs before
    enrichment, `test_cov = test_linkage(files, graph)` runs after
    enrichment over the filtered set, `test_coverage=test_cov` is passed
    to the `AtlasData` constructor, and harden's git `per_file` filter
    runs after construction using the initialised `removed` set. No
    duplicate logic.

### Unchanged from pristine
Everything else: `PLAN.md`, `IMPLEMENTATION_A.md`, `REPORT_B.md`,
`LICENSE`, `pyproject.toml`, `src/ghostatlas/__init__.py`, all
pre-existing tests and fixtures.

## Conflicts

None. All six multi-lane files merged cleanly (rc=0, no conflict
markers) because lane edits occupied different regions. No harden fix
was dropped; every harden change listed in its IMPROVE.md was verified
present in the merged tree by grep (gitignore negation, generated
markers, relative imports, JS/TS extensions, go.mod blocks, requirements
filtering, CLI mkdirs, error prefix, config single-line guard,
line-count fix, dead-zone None normalisation, hidden-path purge).

## Interaction notes (checked, not just textual)

- Deepen's linkage is computed after harden's expanded hidden-path
  purge, so hidden files cannot leak through the new test-coverage
  surface; deepen's own hidden-path integration test passes in merged.
- Harden's 11 regression tests pass against data that now also carries
  deepen's additive `test_coverage` key; polish's help-text test passes
  with harden's CLI write-path changes in place.

## Test counts (all run 2026-10-18, `PYTHONPATH=src python3 -m pytest tests -q`)

| Tree | Result |
|---|---|
| Pristine (baseline) | 21 passed |
| Harden lane | 32 passed (21 + 11 new) |
| Polish lane | 21 passed (no new tests) |
| Deepen lane | 36 passed (21 + 15 new) |
| **Merged** | **47 passed, 0 failed** (21 + 11 + 15; exceeds best lane) |

Zero new failures versus every lane; merged passes the union of all
lane suites. Test caches (`__pycache__`, `.pytest_cache`) were removed
from the merged tree after the run.

## Anything suspicious

Nothing. No lane changed version, LICENSE, or dependencies; no file
outside the lanes' declared change lists differs from pristine.
