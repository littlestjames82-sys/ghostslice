# GhostScope — merge report (2026-10-18)

- Tool: ghostscope
- Merged tree: `~/workspace/.improve-2026-10-18/ghostscope/merged/` (fresh copy of pristine `~/workspace/ghostscope/`, caches excluded; pristine never edited)
- Lane order applied: harden, then polish, then deepen
- Method: `diff -rq` per lane vs pristine, then file-by-file. Single-lane files copied outright; multi-lane files merged by applying the later lane's pristine-based patch onto the earlier lane's version, with hand-merging where patches collided (see Conflicts). A line-presence audit afterwards confirmed every line added by any lane (vs pristine) is present in merged, with no duplicate logic.

## Test counts

Command (per lane docs): `PYTHONPATH=src:. python3 -m pytest tests -q`

- Merged: **74 passed, 1 skipped** (69.69s)
- Pristine-check (`~/workspace/.improve-2026-10-18/ghostscope/pristine-check/`, pristine copied to the same depth): **38 passed, 1 skipped** (40.23s)
- Arithmetic check: 38 baseline + 22 harden tests + 14 deepen tests = 74. Polish added no tests.
- The 1 skip in both is the pre-existing optional `ghostslice`-on-PATH cross-check.
- Acceptance rule: merged failures (0) are a subset of pristine-check failures (0). Zero failures appear only in merged.

## Files by lane

### Harden only (copied)
- `src/ghostscope/scanner.py` — shared `_decode`, single-read scan
- `tests/test_harden.py` — NEW, 22 regression tests

### Polish only (copied)
- `examples/README.md`
- `examples/run_demo.sh`
- `src/ghostscope/__main__.py` — module docstring
- `src/ghostscope/profile.py` — `load_scope_profile` docstring

### Deepen only (copied)
- `src/ghostscope/graphbuild.py` — shared `outline_cover()` helper, `covering_tests()` delegates to it
- `tests/test_lost_coverage.py` — NEW, 14 tests

### Multiple lanes (hand/patch merged, both/all changes survive)
- `src/ghostscope/cli.py` — harden + polish. Harden: `OSError` (was `FileNotFoundError`) in `pack`/live-`explain` handlers returning exit 2, and non-object `scope.json` rejection in `explain --pack`. Polish: help text, metavars, subcommand descriptions, docstrings. Different regions; polish patch applied with line offsets (+3/+7).
- `src/ghostscope/diffparse.py` — harden + polish. Harden: hunk-state tracking (`--- `/`+++ ` inside an incomplete hunk treated as content), header-less `diff -u` parsing, `_check_safe_path` raising `ValueError` on absolute/`..` paths. Polish: `parse_diff` docstring (applied at offset +15, after harden's inserted block).
- `src/ghostscope/gitinput.py` — harden + polish. Harden: `errors="replace"` on all git subprocess calls, `_safe_rel` guard in `head_content`/`base_content`. Polish: `ScopeInputError` and `load_change_input` docstrings. One polish hunk applied with fuzz 1 (context shifted by harden's `_safe_rel` insertion directly below the class); result verified by reading the file — class docstring replaced `pass`, `_safe_rel` intact, no duplication.
- `src/ghostscope/validate.py` — harden + polish. Harden: missing-file-with-claimed-content error, empty-content sha256 check no longer skipped, non-object manifest / non-list `files` / path-less entries return clean `ok: False`, unsafe manifest paths rejected. Polish: `validate_pack` docstring (offset +7).
- `src/ghostscope/mcp_server.py` — harden + polish + deepen (see Conflict 1). Harden: non-object JSON message gets `-32600`, unparseable input gets `-32700` instead of silence. Polish: docstrings for `tool_scope_pack`, `tool_scope_explain`, `handle_message`, `serve`. Deepen: `lost_covering_tests` added to the capped `scope_pack` changed-file summary.
- `README.md` — polish + deepen. Polish: stale status/install wording fixed, corrected `explain` example, `check`/`--json`/exit-code guidance, pack-mode table, `ghostscope mcp` tool arguments, Tests note. Deepen: lost-coverage paragraph in the Risk section (applied at offset +26 after polish's expansion).
- `src/ghostscope/pack.py` — polish + deepen. Polish: docstrings for `analyse`, `build_pack`, `render_review`, `explain_from_scope`. Deepen: `_lost_covering_tests()` / `_apply_lost_coverage()`, lost-cover notes with generic-note dedup, `lost_covering_tests` in scope totals/labels, REVIEW.md lost-cover lines and limits bullet (deepen hunks applied at offsets +4 to +12).

## Conflicts

1. **`src/ghostscope/mcp_server.py` — `handle_message` head (harden vs polish, same region).** Harden inserts an `isinstance(msg, dict)` guard as the first statement of `handle_message`; polish inserts a docstring at exactly the same spot. The polish patch hunk failed (and, because the patch was applied via a dry-run gate, none of polish's four mcp hunks were applied in that pass). Resolved by hand: polish docstring placed first (so it remains the function's docstring), immediately followed by harden's guard unchanged, then the original body. The other three polish docstrings (`tool_scope_pack`, `tool_scope_explain`, `serve`) were also inserted by hand verbatim from the polish lane. Deepen's one-line `lost_covering_tests` addition is in a different region and applied cleanly. Verified: `diff` of merged vs each of the three lane versions of this file shows exactly the other lanes' additions and nothing else — no harden fix dropped, no duplicate logic.
2. All other multi-lane files: no same-region conflicts. Later-lane patches applied with line offsets only (and the one fuzz-1 case in `gitinput.py` noted above, verified by eye).

## Anything suspicious

- None. No harden fix was dropped (line-presence audit: all lane-added lines present in merged for all 15 changed files; `python3 -m py_compile src/ghostscope/*.py` passes).
- No `IMPROVE.md`, `.orig`, or `.rej` files remain in merged; `__pycache__`/`.pytest_cache` from the test run were removed.
- Pristine tree `~/workspace/ghostscope/` was never edited; nothing was pushed to GitHub.
