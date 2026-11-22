# MERGE.md - ghostbench, improve lanes merged (2026-10-18)

Merged tree built fresh from the pristine tree
(`~/workspace/ghostbench/`, never edited), lanes applied in order
harden -> polish -> deepen. Method: single-lane files copied verbatim;
multi-lane files combined with a three-way merge
(`git merge-file`, base = pristine), then hand-verified. No lane's
IMPROVE.md was copied in. LICENSE byte-identical, version stays 0.1.0.

## Test counts (PYTHONPATH=src python3 -m pytest -q)

- merged: **68 passed, 1 skipped, 1 failed** (70 collected)
- pristine-check (pristine copied to the same depth,
  `../pristine-check/`): **27 passed, 1 skipped, 1 failed**
- The 1 failure in both is identical and environmental:
  `test_ghostbus_corpus_points_at_the_real_tree_and_copies_nothing` -
  the GhostBus corpus relative path `../../../../ghostbus` resolves to
  `~/workspace/.improve-2026-10-18/ghostbus`, which does not exist.
  Merged failures are a subset of (equal to) pristine-check failures:
  zero failures appear only in merged.
- Count arithmetic checks out: in-copy baseline 29 collected
  (27 pass / 1 skip / 1 fail) + 32 harden tests + 9 deepen tests = 70.

## Files by lane

### Harden only (copied verbatim)
- `tests/test_hardening.py` (new, 32 tests)

### Polish only (copied verbatim)
- `src/ghostbench/__main__.py`, `src/ghostbench/demo.py`,
  `src/ghostbench/tokens.py` (docstrings)
- `examples/README.md`, `examples/corpora/adversarial/README.md`

### Deepen only (copied verbatim)
- `tests/test_symbol_scoring.py` (new, 9 tests)

### Harden + polish (clean three-way merges, no conflicts)
- `src/ghostbench/cli.py` - verified: merged-vs-harden diff is only
  polish help/description/docstring text; merged-vs-polish diff is only
  harden logic (no-task refusal before writing, compare input wrapping,
  `add` corpus validation, `main` ValueError/OSError -> exit 2).
- `src/ghostbench/corpus.py`, `src/ghostbench/prices.py`,
  `src/ghostbench/runner.py` (at this stage), `src/ghostbench/scoring.py`
  (at this stage), `src/ghostbench/tierb.py` - verified by AST
  comparison with docstrings stripped: merged logic == harden logic
  exactly for corpus/prices/runner/scoring/tierb.
- `src/ghostbench/report.py` - merged-vs-harden diff is polish
  docstrings plus polish's one code change (redundant `f` prefix
  removed in `render_compare_md`, output byte-identical); harden's
  `compare_reports` shape validation present.

### Polish + deepen (clean three-way merge)
- `README.md` - polish rewrite (Contents, Quickstart, Exit codes,
  Troubleshooting) with deepen's symbol-scoring documentation
  (Scoring section, `symbols_score` and new totals keys in Report
  format) merged in; both verified present.

### Harden + polish + deepen (three-way merges)
- `src/ghostbench/scoring.py` - clean merge: harden validation
  (`_valid_token_count`, patch-parser and gap fixes), polish
  docstrings, and deepen's `symbol_leaf` / `_symbol_present` /
  `patch_added_text` / `score_expected_symbols` all present.
- `src/ghostbench/report.py` - clean merge: harden compare validation,
  polish docstrings + f-prefix fix, deepen's symbol-coverage totals
  line and per-task Symbols column all present.
- `src/ghostbench/runner.py` - ONE conflict, resolved by hand
  (see below).

## Conflicts and resolutions

1. **`src/ghostbench/runner.py` scoring import (the only conflict).**
   Harden's import adds `_valid_token_count`; deepen's adds
   `score_expected_symbols`; both edited the same import statement
   differently. Resolved by combining both names into the single
   import (plus the existing names), no duplicate logic:
   `normalise_verify_report, parse_patch, saving_pct,
   score_expected_symbols, score_files_touched,
   _valid_token_count`. Both symbols are used in the merged file
   (harden's `_variant_from_spec` validation and deepen's per-task
   `symbols_score` computation), and the full suite passes.
   No harden fix was dropped anywhere in this merge.

## Suspicious / notes

- Nothing suspicious. All other multi-lane files merged cleanly with
  zero conflict markers, which matches the lanes' own reports
  (polish = docstrings/help only; deepen = additive scoring in
  separate regions).
- Deepen's totals aggregation in `run_corpus` reads
  `r["symbols_score"]` on rows produced by the merged `run_task`,
  which always sets it - verified by the passing deepen CLI
  integration tests (mini 100% coverage, slice-gap failure,
  provided-bundle not gated, adversarial outcomes unchanged) and the
  passing harden suite in the same run.
- `pristine-check/` is left next to this tree for the parent's
  comparison; it is an unmodified copy of the pristine tree.
