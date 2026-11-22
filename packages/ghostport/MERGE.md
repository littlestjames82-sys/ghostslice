# GhostPort — merge of improve wave 2026-10-18 (harden + polish + deepen)

Merged tree built from a fresh copy of pristine `~/workspace/ghostport/`
(caches excluded). Lanes applied in order: harden, then polish, then deepen.
Pristine was never edited; nothing was pushed.

Test command (unittest, per README/PLAN — not pytest), run from each tree
root: `python3 -m unittest discover -s tests`

## Final test counts (all verified by running, 2026-10-18)

| Tree | Result |
|---|---|
| pristine (baseline) | Ran 24 tests, OK |
| harden | Ran 44 tests, OK (24 + 20 new in tests/test_harden.py) |
| polish | Ran 24 tests, OK |
| deepen | Ran 40 tests, OK (24 + 16 new in tests/test_scanner_bindings.py) |
| **merged** | **Ran 60 tests, OK (24 + 20 + 16 — the full union)** |

Merged passes everything every lane passed, with zero new failures versus
every lane. Spot checks in merged: demo-project scan still reports exactly
its 3 documented hits (PYUP003/PYUP004/PYUP006, no new false positives);
`ghostport --help` renders the polish help text; `ghostport packs` loads
the deepen-updated pack under the harden validation.

## Files from a single lane (copied verbatim)

From harden only:
- `tests/test_harden.py` (new)

From polish only:
- `README.md`
- `examples/README.md`
- `examples/ghostslice-profile-snippet.json` (key-name fix: now uses the
  loader-accepted `budget_tokens`/`merge`/`pin_first`/`order`)
- `src/ghostport/__init__.py`, `src/ghostport/__main__.py`
- `src/ghostport/planning.py`, `src/ghostport/tokens.py` (docstrings)
- `tests/test_pack_gaps.py` (header docstring correction only)

From deepen only:
- `patterns/python-upgrade.json` and `src/ghostport/packs/python-upgrade.json`
  (PYUP008 alias list completed; the two copies remain byte-identical)
- `tests/test_scanner_bindings.py` (new)

## Files changed by multiple lanes (hand-merged, both lanes survive)

Method: three-way merge (`git merge-file`, pristine as base) per file, then
manual resolution of every conflict and duplicate. No harden fix was dropped.

- `src/ghostport/bundle.py` (harden + polish) — clean 3-way merge: harden's
  wider `signatures_slice` exception set + bundle containment checks
  (project/bundle escape refused with ValueError) plus polish's docstrings.
- `src/ghostport/cli.py` (harden + polish) — clean 3-way merge: harden's
  stderr warning when a `planned` ledger write fails in `cmd_plan`, plus
  polish's per-command docstrings and full argparse help/descriptions.
  Verified both present; argument names/defaults/dispatch unchanged.
- `src/ghostport/graph.py` (harden + polish) — clean 3-way merge: harden's
  parse/read error tolerance in `imports_of`, module-identity self-import
  filtering, and the `mod_by_rel` fix for duplicate module names, plus
  polish's docstrings. Two polish duplicate docstrings collapsed (below).
- `src/ghostport/ledger.py` (harden + polish) — 1 conflict + 1 stacked
  duplicate, hand-resolved (below). All harden logic kept: corrupt-UTF-8 /
  non-object-line tolerant `read_records`, identity enforcement + "ok"
  verdict + contradiction refusal in `validate_verify_report`, forged-
  verified downgrade and unknown-state filtering in `unit_states`.
- `src/ghostport/patterns.py` (harden + polish) — 1 conflict, hand-resolved
  (below). Harden's pack-id slug guard, non-empty-string field checks, and
  per-kind matcher validation kept, plus polish's docstrings.
- `src/ghostport/profile.py` (harden + polish) — clean 3-way merge:
  harden's known-key type checks (ProfileError) plus polish's docstrings.
- `src/ghostport/status.py` (harden + polish) — clean 3-way merge: harden's
  clean ValueError for malformed/non-object port-plan.json and defaulted
  order/token fields, plus polish's docstring.
- `src/ghostport/scanner.py` (harden + polish + deepen) — two-step 3-way
  merge (harden+polish first, 1 conflict hand-resolved; then + deepen,
  clean). Final file carries all three lanes: deepen's extended module
  docstring, `import_bindings()` / `resolve_dotted()` / `_imported_targets()`
  helpers and binding-aware `_matches()` rewrite; harden's `scan_file`
  OSError handling and ValueError/RecursionError/MemoryError parse-error
  reporting; polish's docstrings on `iter_project_files`, `dotted_name`,
  `scan_file`, and `scan_project`.

## Conflicts and how they were resolved

All conflicts were the same shape: polish put a docstring where harden (or
deepen) put logic at the same function head. In every case BOTH were kept —
docstring first, then the logic. No conflict required choosing one lane
over the other, and no harden fix was dropped or weakened.

1. `ledger.py` — `unit_states` docstring: harden rewrote it (latest-state
   line + Hardening paragraph); polish prepended a one-liner and left the
   pristine line as a dead string. Resolved to a single docstring keeping
   polish's summary sentence, the original first line, and harden's full
   Hardening paragraph verbatim.
2. `ledger.py` — `validate_verify_report`: auto-merge stacked polish's new
   docstring on top of harden's extended docstring, leaving the second as a
   dead string expression. Collapsed to one docstring combining polish's
   summary/error contract, the accepted-shapes text, and harden's
   Hardening paragraph verbatim. Logic untouched (harden's version).
3. `patterns.py` — `load_pack` head: harden's slug/traversal guard vs
   polish's docstring. Resolved: polish docstring first, then harden's
   guard, then the original search loop.
4. `scanner.py` — `scan_file` head: harden's try/except around `read_text`
   vs polish's docstring + plain read. Resolved: polish docstring first,
   then harden's guarded read; harden's parse-error handling below kept.

## Duplicate docstrings collapsed (polish-lane quirk, noted not hidden)

The polish lane itself contained five functions with two consecutive
string literals (its new docstring plus the pre-existing one left behind
as a no-op expression): `graph._scc`, `graph.form_units`,
`ledger.validate_verify_report`, `ledger.unit_states`, and
`scanner._matches`. Harmless at runtime, but the merged tree keeps exactly
one docstring per function, worded to preserve both texts:

- `graph._scc`: "Return the strongly connected components of a directed
  graph (Tarjan, iterative)." (merges both originals)
- `graph.form_units`: polish's fuller docstring kept; the dropped line
  ("Form units from scan hits, combine cycles, sequence leaves-first")
  is fully covered by it.
- `ledger.*`: see conflicts 1–2 above.
- `scanner._matches`: single docstring "Return sorted line numbers in
  ``tree`` matched by one pattern matcher." (merges polish's wording
  with the original "sorted").

An AST audit of the merged tree confirms zero remaining double-docstring
functions, and every merged module parses cleanly.

## Anything suspicious

- Nothing functionally suspicious. The only irregularity found was the
  polish lane's duplicate-docstring pattern above, resolved as documented.
- Known lane-noted limits carry over unchanged: harden notes bundle
  containment now refuses symlink-out-of-project files, and any later
  non-report-backed ledger record supersedes a verified one (existing
  latest-state-wins semantics, errs toward under-claiming); deepen notes
  binding resolution is best-effort (shadowing locals still resolve as
  imports; dynamic access not followed) and aliased from-imports can hit
  at both the import line and the use line by design; polish notes
  `pattern_overrides` is accepted by the loader but has no other effect
  in v0.1. None of these were altered by the merge.
- No `IMPROVE.md` files remain in the merged tree (lane files were copied
  individually, and the check was run). Test-run `__pycache__` was cleaned
  from the merged tree after verification.
