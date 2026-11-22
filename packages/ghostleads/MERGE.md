# GhostLeads - Merge Report (Oct 18, 2026 improvement run)

Merger output: pristine tree plus harden, then polish, then deepen,
hand-merged file by file. Nothing was pushed. Pristine tree was never
edited.

## Test counts

Test command (all runs): `python3 -m pytest -q`

- Baseline: 40 passed (pristine copy at the same depth,
  `~/workspace/.improve-2026-10-18/ghostleads/pristine-check/`,
  40 passed, 0 failed)
- Harden lane: 55 passed (40 + 15 new in `tests/test_harden.py`,
  per its IMPROVE.md)
- Polish lane: 40 passed (no new tests, per its IMPROVE.md)
- Deepen lane: 53 passed (40 + 13 new in
  `tests/test_deepen_fuzzy_dedupe.py`, per its IMPROVE.md)
- Merged: 68 passed, 0 failed

68 = 40 baseline + 15 harden + 13 deepen, exactly as expected.
Polish added no tests. Merged failure set is empty, so it is a
subset of the baseline failure set (also empty). No deviations.

## Files changed by only one lane (copied outright)

- Harden: `tests/test_harden.py` (new)
- Polish: `examples/WALKTHROUGH.md`, `src/ghostleads/__init__.py`,
  `src/ghostleads/__main__.py`, `src/ghostleads/packs.py`,
  `src/ghostleads/scoring.py`
- Deepen: `tests/test_deepen_fuzzy_dedupe.py` (new)

## Multi-lane files and how each conflict was resolved

- `src/ghostleads/cli.py` (harden + polish): three-way merge was
  clean. Harden's try/except around `save_store` in `score` and
  `write_packs` in `pack` (clean `error: ...`, exit 2) survives
  verbatim alongside polish's expanded help text, epilogs, and
  docstrings.
- `README.md` (polish + deepen): three-way merge was clean. Polish's
  full rewrite (at-a-glance, quick start, examples, exit codes,
  troubleshooting) survives, and deepen's near-spelling dedupe
  paragraph is present verbatim in the Duplicates section.
- `src/ghostleads/models.py` (harden + polish + deepen): two
  conflicts from polish, one from deepen.
  - `phone_digits`: harden's extension-stripping implementation kept
    verbatim; polish's docstring kept and extended by one clause to
    mention the extension stripping (see merger-authored code below).
  - `normalise_name`: harden's `_fold_ascii(...)` implementation kept
    verbatim; polish's docstring kept, extended to mention accent
    folding, and its closing "not fuzzy" sentence clarified to say
    this function itself is not fuzzy while near-spelling matching
    lives in `fuzzy_name_match` / `store.same_lead` (it would
    otherwise have contradicted the merged deepen behaviour).
  - Deepen insertion: harden's `normalise_town` function and deepen's
    `edit_distance` / `fuzzy_name_match` functions were competing for
    the same insertion region; both are kept verbatim, harden's
    `normalise_town` first, then deepen's two functions.
- `src/ghostleads/store.py` (harden + polish + deepen): polish merged
  cleanly (docstrings on `load_store` / `save_store` over harden's
  validation code). Deepen produced two conflicts:
  - Import line: union of both lanes:
    `from .models import Lead, fuzzy_name_match, normalise_name, normalise_town, phone_digits`.
  - `same_lead` town lines: harden's `normalise_town(a.town or "")` /
    `normalise_town(b.town or "")` kept (deepen's plain lower/split
    lines dropped, as they are a strictly weaker form of the same
    normalisation), and deepen's fuzzy corroboration branch
    (`if not exact: ...`) inserted verbatim immediately after those
    lines, so it compares towns through `normalise_town`. Deepen's
    `_field_agrees` / `_attribute_agrees` helpers and its expanded
    `same_lead` docstring merged cleanly and survive verbatim.

## Merger-authored code

Almost none. No new logic was written. The only merger-authored text
is in `models.py` docstrings, marked here clearly:

- `phone_digits` docstring: polish's text plus the clause
  "a trailing extension (``ext. 12`` / ``x12``) is stripped," so the
  docstring describes harden's implementation accurately.
- `normalise_name` docstring: polish's text plus "folds accented
  letters to ASCII" and a rewritten closing sentence (quoted in the
  resolution notes above) so the docstring stays true after deepen.

All executable code in merged files is verbatim from one of the three
lanes (union/intersection choices only, as documented above).

## Flags

- None blocking. No conflict required dropping any lane's fix or
  behaviour; every harden fix survives.
- Offline / drafts-only check: merged source contains no network
  code (grep for urllib/requests/socket/http in `src/` finds
  nothing); no lane added a send or contact capability. The fuzzy
  dedupe in deepen only merges records the user already supplied.
- `STUDIO_CONTACT = "(423) 408-2150"` in `packs.py` is untouched, as
  designed (documented studio public contact only, per repo README/
  PLAN). It is not a leak and was not redacted.
- No version bumps anywhere (`pyproject.toml` and `__init__.py` both
  still 0.1.0); stdlib only; LICENSE untouched.
- All lane IMPROVE.md files were excluded; MERGE.md is the only new
  file at the merged root.

## Verdict

CLEAN
