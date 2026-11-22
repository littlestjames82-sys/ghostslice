# GhostPacks — merge of harden + polish + deepen lanes (2026-10-18)

Merged tree built from a fresh copy of pristine `~/workspace/ghostpacks/`
(pristine never edited). Lanes applied in order: harden, polish, deepen.
No IMPROVE.md in this tree; no GitHub push.

## Test counts (PYTHONPATH=src python3 -m pytest tests -q, run in each tree)

- Pristine (run in a temp copy to keep the real tree untouched):
  23 tests, 22 passed, 1 failed.
- Harden lane: 41 tests, 40 passed, 1 failed.
- Polish lane: 23 tests, 22 passed, 1 failed.
- Deepen lane: 38 tests, 37 passed, 1 failed.
- **Merged: 56 tests, 55 passed, 1 failed.**

The single failure in every tree, including merged, is the documented
pre-existing failure
`tests/test_merge_remove_roundtrip.py::test_merge_remove_roundtrip_restores_export_totals`
(GhostSlice-side counting of the project's own `.ghostslice.json`;
identical assertion in all trees). Zero new failures versus any lane;
merged passes the union of all lane tests (23 + 18 harden + 15 deepen).
All three starter packs and the demo pack still lint OK in merged.

## Files by lane

Taken wholesale (changed by one lane only):

- Harden: `tests/test_hardening.py` (new).
- Polish: `src/ghostpacks/cli.py`, `src/ghostpacks/doctor.py`,
  `src/ghostpacks/__main__.py`, `examples/README.md`.
- Deepen: `tests/test_bench_report_verification.py` (new).

Hand-merged (changed by more than one lane):

- `src/ghostpacks/authoring.py` — harden code fix (init-pack output
  path that is an existing file raises a clean GhostPacksError) plus
  polish docstrings for `_slug` and `create_pack_from_project`.
  Different regions; both survive verbatim.
- `src/ghostpacks/manager.py` — harden version (lockfile non-object
  entry validation, `_ask` EOF-safe prompts, `_validated_backup_path`
  guard in `remove`) plus polish docstrings for
  `load_project_profile`, `load_lockfile`, `plan_merge`,
  `profile_diff`. Different regions; both survive verbatim.
- `README.md` — polish version as base (Quick start, Status refresh,
  `list`/`doctor`/flags/library-order/exit-code docs, field notes,
  "If something fails") with deepen's three bench cross-check
  passages folded in (Honest scores hard rule, `bench` paragraph,
  `lint` description). The passages sit in spots polish did not
  rewrite, so the combined text keeps both.
- `src/ghostpacks/pack.py` — three-way merge, see conflicts below.

## Conflicts and resolutions (all in pack.py)

1. **Bench report verification: harden `_bench_report_problem` vs
   deepen `_bench_report_errors`.** Same region, different rules:
   - Harden: claimed score must be finite and >= 0 (string/bool/dict/
     negative rejected); report must resolve inside the pack and be a
     readable JSON object; the report's own score, *if present*, must
     match the claim.
   - Deepen: report's `score` field is *required*, must equal the
     claim; report must name `reference_project` (or a non-empty
     `reference_projects` list); `savings_percent`, when present,
     must be 0-100.
   Resolution: one unified `_bench_report_errors(manifest, root)`
   implementing the strict union of both lanes (every check from
   both). The only behavioral choice: where harden made the report
   score optional-if-present and deepen requires it, the stricter
   deepen rule wins. No harden check was dropped: inside-pack
   resolution, readable-JSON-object, invalid report score, and the
   >= 0 claimed-score rule all survive. Harden's helper was removed
   (superseded, not silently dropped); `score_status` and
   `_manifest_errors` both use the unified function (deepen's
   wiring). The shipped conftest honest report already carries
   score + reference_project, so the stricter union passes both
   lanes' guard tests. Module docstring took deepen's expanded
   honest-scores bullet; polish docstrings for `Pack`, its
   properties, `_read_json`, and `_manifest_errors` were applied on
   top; harden's real-calendar-date validation, non-object `bench`
   error, and data-only lint sweep (dotfiles, symlinks, non-regular
   files) are intact.
2. **Symlink message wording.** Harden's lint sweep rejects any
   symlink and lint returns before manifest checks, which would have
   swallowed deepen's bench message containing "outside" that
   deepen's symlink test pins. Resolution: the sweep message now
   reads "...packs are self-contained data only and a symlink can
   point outside the pack" — a factual statement of the sweep's own
   rationale, so both lanes' pinned outputs survive.
3. **Invalid-score message wording.** Deepen's non-numeric test pins
   the substring "finite number"; a first merged wording ("a finite
   non-negative number") broke that substring and failed the test.
   Reworded to "must be a finite number and non-negative", which
   keeps harden's >= 0 semantics and deepen's pinned text. Caught by
   the full merged run (intermediate result: 54 passed, 2 failed),
   fixed, re-ran green.

## Anything suspicious

- Nothing dropped: every harden fix is present and pinned by its
  tests in merged (hidden-file sweep, symlink/fifo rejection, bench
  outside/garbage/mismatch, date validation, tampered-backup remove,
  non-object lockfile, EOF prompt, init-pack file path).
- Deliberate strictness increase versus the harden lane alone: a
  scored pack whose Bench report lacks a `score` field or a
  reference project now fails lint (deepen's rule). This is the
  lanes' intended combined behavior, and no in-tree pack is scored.
- Pristine tree was not modified; test runs for pristine were done
  in a temp copy.
