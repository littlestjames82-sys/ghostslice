# GhostReview — Merge of harden + polish + deepen (Oct 18, 2026)

Merger: three improvement lanes merged onto a fresh copy of the
pristine tree (`~/workspace/ghostreview/`, never edited), in the
order harden, then polish, then deepen. No file was pushed anywhere.

## Test counts (all `PYTHONPATH=src python3 -m pytest tests -q`)

| Tree | Result |
|---|---|
| Pristine baseline (per all three IMPROVE.md files) | 77 passed |
| harden lane (re-run by merger) | 93 passed (77 + 16 new in `tests/test_harden.py`) |
| polish lane (re-run by merger) | 77 passed (no new tests, doc/help only) |
| deepen lane (re-run by merger) | 88 passed (77 + 11 new in `tests/test_deepen_scope.py`) |
| **merged (final, re-run by merger)** | **104 passed, 0 failed** |

104 = 77 baseline + 16 harden + 11 deepen. Merged passes at least
what the best lane passed (harden, 93), with zero new failures
versus every lane: every pre-existing test, every harden test, and
every deepen test is present and passing in merged. The lane counts
above were both recorded in the lanes' IMPROVE.md files and
independently re-run by the merger; they agree exactly.

## Files by source lane

Single-lane files (copied verbatim from that lane; verified
byte-identical to the lane version after the merge):

- `examples/README.md` — polish only
- `src/ghostreview/__main__.py` — polish only (new module docstring)
- `src/ghostreview/dependents.py` — polish only (docstrings)
- `src/ghostreview/symbols.py` — polish only (docstrings)
- `tests/test_harden.py` — harden only (new file, 16 tests)
- `tests/test_deepen_scope.py` — deepen only (new file, 11 tests)

Multi-lane files (three-way merged, base = pristine; the merged
diff against pristine is the union of the lane diffs in every case):

- `src/ghostreview/cli.py` — harden + polish
- `src/ghostreview/diffparse.py` — harden + polish (one conflict, below)
- `src/ghostreview/inputs.py` — harden + polish + deepen (three-way, below)
- `src/ghostreview/mcp_server.py` — harden + polish
- `src/ghostreview/risks.py` — harden + polish
- `README.md` — polish + deepen
- `src/ghostreview/core.py` — polish + deepen
- `src/ghostreview/reports.py` — polish + deepen

No other files differ from pristine. No `IMPROVE.md` was carried
into merged (checked: none present before this MERGE.md was written).

## Conflicts and how they were resolved

Only one textual conflict occurred in the entire merge. All other
multi-lane files merged cleanly by three-way merge because the lanes
touched different regions; each such file was still diff-checked
against pristine afterwards to confirm both lanes' changes survive
with no duplicate logic.

1. **`src/ghostreview/diffparse.py` — `_clean_path` (harden vs polish).**
   Both lanes changed the head of the function: polish added a
   docstring and kept `raw = raw.strip()`; harden replaced that line
   with `raw = raw.strip().split("\t")[0].strip()` plus an explanatory
   comment, so a traditional `diff -u` header `/dev/null\t<timestamp>`
   is still recognised as `/dev/null` (and it removed the now-redundant
   second tab-split after the `/dev/null` check).
   Resolution (hand-merge, both changes survive): polish docstring
   first, then harden's comment and tab-split-first line; the redundant
   second split is not reintroduced. The rest of both lanes' diffparse
   changes coexist: polish docstrings for `Hunk`, `FileChange`, and
   `parse_diff`; harden's `saw_old_null`/`saw_new_null` fields,
   `_maybe_quoted_path` for rename/copy paths, `% 256` guard in
   `_c_unquote`, header-less `/dev/null` added/deleted normalisation.

2. **`src/ghostreview/inputs.py` — three-way, no textual conflict,
   highest semantic risk (called out explicitly).** Harden and deepen
   both rewrote parts of `load_scope_pack`: harden added the
   non-object top-level guard and replaced the risk-reasons loop with
   a list-validated version (a non-list value is ignored, dict/list
   reasons are skipped, instead of inventing one reason per character
   or key); deepen added `_scope_str_list` / `_scope_reading_order`,
   per-file changed-symbols / covering-tests / direct-callers
   extraction inside the same entry loop, and pack totals in the
   return dict. The three-way merge interleaved them correctly, and
   the merger verified the merged function line by line: harden's
   validated `raw_reasons` loop runs first, deepen's per-file
   extraction follows inside the same `if epath:` block, and both
   lanes' return fields are present. Harden's `load_verify_report`
   fixes (non-object guard, non-dict `post`/`tests`, list-only gap
   counts via `_count`) and polish's `diff_from_file` docstring also
   survive intact.

All other overlaps were disjoint-region and verified as unions:

- `cli.py`: polish help/docstring/epilog text + harden's
  `write_reports` `OSError` → clean stderr message + exit 2.
- `mcp_server.py`: polish docstrings + expanded `review_diff`
  description + harden's non-object JSON-RPC line → `-32600`
  invalid-request response, server keeps serving.
- `risks.py`: polish docstrings (`is_test_path`, `is_config_path`,
  `verdict_for`) + harden's secret-path tightening (below) and
  case-insensitive secret-extension check.
- `core.py`: polish `build_review`/`_summary` docstrings + deepen's
  `reconcile_scope()` / `_name_list()`, its call in `build_review`
  (also on the could-not-review path via the shared `base` flow),
  and the reconciliation sentence in `_summary`.
- `reports.py`: polish `write_reports`/`render_markdown` docstrings
  + deepen's Scope-section rendering (pack size, reconciliation
  line, reading order, per-file Scope detail).
- `README.md`: polish Quickstart fix, "Choosing a diff source"
  table, CI preview examples, MCP argument clarification, and
  Troubleshooting section + deepen's Reports paragraph documenting
  full Scope citation and reconciliation.

No harden-lane fix was dropped. The complete harden set is present
in merged: wrong-shape Verify/Scope readers (`inputs.py`),
`diffparse.py` `/dev/null` / quoting / octal fixes, `risks.py`
secret-path fixes (below), `mcp_server.py` non-object survival,
and `cli.py` unwritable-output exit 2 — each pinned by its test in
`tests/test_harden.py`, all 16 passing in merged.

## Deliberate behaviour change — SURVIVED (verified)

Whole-token secret-name matching in `src/ghostreview/risks.py`
(harden lane, deliberate):

- `_SECRET_PATH_RE` now requires `secret`/`secrets` and
  `credential`/`credentials` to be a whole name token (end of path
  or followed by `/`, `.`, `_`, or `-`):
  `.*secrets?(?=$|[/._-])` / `.*credentials?(?=$|[/._-])`, instead of
  the old `.*secret.*` / `.*credentials.*` substring match.
- The secret-extension check is also case-insensitive in merged
  (`Path(path).suffix.lower() in _SECRET_EXTS`).

Verified in the merged tree three ways:

1. Code: the tightened regex and the harden comment ("secretary.py
   is not secret-shaped and must not draw a high flag") are present
   verbatim in merged `risks.py`.
2. Tests: `tests/test_harden.py::test_secretary_is_not_a_secret_path`
   and its companions pass in merged — `secretary.py` draws no
   `SECRET-PATH` flag, while `secret_key.py` and
   `config/credentials.json` still do.
3. Direct probe by the merger against merged `risks.py`:
   `secretary.py` not flagged, `secretstuff.py` not flagged,
   `secret_key.py` flagged, `app_secret.py` flagged,
   `credentials.json` flagged, `cert.PEM` flagged, `cert.Key`
   flagged (case-insensitive extension). All as intended.

## Anything suspicious

- Nothing suspicious found. No conflict markers remain anywhere in
  merged (grep-checked), no duplicate logic was introduced by any
  merge, no lane file is missing from the union, and no extra file
  differs from pristine beyond the union listed above.
- One expected cosmetic note: `core.py` in deepen (and therefore in
  merged) places `reconcile_scope` before the module's `HONESTY`
  constant with a single blank line after the imports; this is the
  deepen lane's own formatting, preserved as-is, not a merge artefact.
- Test-run caches (`__pycache__`, `.pytest_cache`) created while
  verifying were removed from merged afterwards; merged is a clean
  source tree plus this MERGE.md.
