# GhostProxy — merge report (Oct 18, 2026)

Merger: combined harden, polish, and deepen lanes onto a fresh copy of
pristine `~/workspace/ghostproxy/`. Pristine tree was never edited.
No GitHub push.

## Test counts

Command (documented lane command, GhostSlice importable):
`PYTHONPATH=src:$HOME/workspace/ghostslice/src python3 -m pytest -q`

- pristine-check (`~/workspace/.improve-2026-10-18/ghostproxy/pristine-check/`,
  pristine copied to the same depth as merged): **55 passed, 1 xfailed**
  in 52.60s. This matches the baseline stated in all three IMPROVE.md files.
- merged: **97 passed, 1 xfailed** in 78.17s.
  - Arithmetic: 55 baseline + 33 harden (`test_harden.py`) + 9 deepen
    (`test_near_duplicates.py`) + 0 polish (docs/help only) = 97.
- Acceptance: merged failures = none. Pristine-check failures = none
  under this command. Merged failures are therefore a subset of
  pristine-check failures; zero failures appear only in merged.
- Note on environment: all three lanes document that with only
  `PYTHONPATH=src`, 10 parity tests fail because the sibling GhostSlice
  checkout is not beside these copies. That is a pre-existing depth /
  sibling-layout condition, identical for pristine-check and merged,
  not a merge regression. The documented GhostSlice-on-PYTHONPATH
  command above was used for both runs for an apples-to-apples count.

## Files by lane

Single-lane files — copied verbatim from that lane:

- harden only:
  - `src/ghostproxy/config.py`
  - `src/ghostproxy/doctor.py`
  - `src/ghostproxy/ledger.py`
  - `src/ghostproxy/server.py`
  - `tests/test_harden.py` (new, 33 tests)
- polish only:
  - `examples/README.md`
  - `src/ghostproxy/__main__.py`
- deepen only:
  - `src/ghostproxy/slice_adapter.py`
  - `tests/test_near_duplicates.py` (new, 9 tests)

Multi-lane files — hand-merged, both lanes survive (see Conflicts):

- `src/ghostproxy/cli.py` — polish + harden
- `src/ghostproxy/transform.py` — harden + deepen
- `README.md` — polish + deepen

Total vs pristine: 10 modified files + 2 new test files.
No other files changed. No `IMPROVE.md`, `*.orig`, or `*.rej`
files remain in merged (patch backups were removed and verified).

## Conflicts and resolutions

No lane pair changed the same code region in incompatible ways.
All three overlaps were changes in different regions of the same
file, merged by taking one lane as base and applying the other
lane's pristine-relative diff with `patch` (clean hunks, offsets
only, no rejects, no duplicate logic). Each was then verified by
diffing merged against both lane versions to confirm it contains
exactly the other lane's additions.

1. `src/ghostproxy/cli.py` — polish + harden, NO true conflict.
   - Polish: module docstring, `_add_common` / `_config_from` /
     `main` docstrings, help strings for `--host`/`--port`/
     `--upstream`/`report`/`transform` flags, subcommand
     descriptions, main-parser epilog with examples.
   - Harden: a single hunk at the end of `main()` — an added
     `except (OSError, ValueError)` handler returning exit 2 with a
     one-line `ghostproxy: ...` message (after the existing
     `ConfigError` handler, which is a ValueError subclass and
     still takes precedence).
   - Resolution: polish version as base + harden hunk applied
     (succeeded at offset 41 lines). Both survive; no duplication.

2. `src/ghostproxy/transform.py` — harden + deepen, NO true conflict.
   - Harden: `_KNOWN_MODES` constant, non-dict guard in
     `transform_request` (fallback `request-not-an-object`),
     non-dict guard in `_request_text`, and `mode_after`
     computed against `_KNOWN_MODES` instead of `_LADDER`.
   - Deepen: step-3 docstring, `BlockResult.duplicate_of` /
     `similarity` fields + `to_dict()`, normalized-exact and
     near-duplicate dropping in pass 1 (keeper-only, using
     `slice_adapter.duplicate_fingerprint` / `near_similarity` /
     `near_threshold`), and passing the new fields when building
     the transform map in pass 3.
   - Resolution: deepen version as base + all 4 harden hunks
     applied (offsets 4 / 8 / 42 / 44 lines, no rejects). Verified
     pass 3 in merged uses BOTH harden's `_KNOWN_MODES` logic
     AND deepen's `duplicate_of`/`similarity` arguments in the
     same `BlockResult(...)` construction — the closest-adjacent
     hunks — with no duplicate logic.
   - Interaction check: harden's tests do not break on deepen's
     additive transform-map fields, and deepen's tests do not
     break on harden's mode reporting; the combined suite is
     fully green (see counts), proving the semantic interaction
     as well as the textual merge.

3. `README.md` — polish + deepen, NO true conflict.
   - Polish: "Commands at a glance" table + defaults note,
     doctor step fix (`--live-check` → `--check-upstream`),
     Tests command fix to `PYTHONPATH=src:../ghostslice/src`
     with explanatory note.
   - Deepen: transform step 3 expanded with exact thresholds
     (normalization, Jaccard >= 0.85, 200-char / 8-line floors)
     and the new `duplicate_of` map field.
   - Resolution: polish version as base + deepen hunk applied
     (offset 17 lines). Both survive.

## Harden fixes — none dropped

All harden changes are present in merged, verified by diff
against the harden lane (merged differs from harden only by the
polish/deepen additions listed above):
ledger scrub allowlist + `_as_int` coercion, ProxyConfig
validation (upstream URL/port, timeout, max_body_bytes, bool
rejection, profile `log_bodies` drop), server body reading
(bad/negative Content-Length, chunked de-chunking, query-string
routing, `ConfigError` on non-loopback bind), transform
`strip-tests` mode reporting + non-object guard, CLI clean
exit-2 errors, doctor single ledger probe, and all 33 tests
in `tests/test_harden.py` (all passing in merged).

## Anything suspicious

- Nothing suspicious found. No file was changed by all three
  lanes; no identical-file tie needed breaking; no hunk was
  rejected; final merged count is exactly the additive sum of
  the three lanes' stated final counts over the shared baseline.
- Patch `.orig` backups created during the hand-merges were
  deleted; `__pycache__` / `.pytest_cache` from the test runs
  were removed from both merged and pristine-check.

## Fix round (Oct 18, 2026, coordinator verification follow-up)

Coordinator verification found a collection error and a count
discrepancy. All items below were reproduced first, then fixed or
resolved, then re-verified back to back. Two details in the
verification brief itself did not match this tree and are corrected
here: `tests/test_near_duplicates.py` comes from the **deepen**
lane (the polish lane has no such file; merged's copy was and is
byte-identical to deepen's), and the merged count under the
documented method is **97** passed (55 baseline + 33 harden + 9
deepen), not 90.

### Run method (the one documented method)

- Documented method: cwd = inside the tree being measured;
  command: `PYTHONPATH=src:$HOME/workspace/ghostslice/src python3 -m pytest -q`
  (the method already documented in README.md and all three
  IMPROVE.md files).
- Plain method (the coordinator's): cwd = inside the tree;
  command: `python3 -m pytest -q` (no env vars).
- Both methods were run on both trees, back to back, after the
  fix. Verbatim summary lines:

  Documented method:
  - pristine-check: `55 passed, 1 xfailed in 36.95s`
  - merged: `97 passed, 1 xfailed in 40.76s`

  Plain method:
  - pristine-check: `10 failed, 45 passed, 1 xfailed in 38.45s`
  - merged: `97 passed, 1 xfailed in 42.24s`

- Acceptance: merged collects cleanly under both methods, and
  merged failures (none, under either method) are a subset of
  pristine-check failures under the same method (none documented;
  the 10 parity cases plain). Zero failures appear only in merged.

### 1. Collection error — cause and fix

Reproduced pre-fix: plain `python3 -m pytest -q` in merged failed
at collection, `tests/test_near_duplicates.py:34`:
`from ghostproxy import slice_adapter` →
`ModuleNotFoundError: No module named 'ghostproxy'`.

Cause: there is no pytest `pythonpath` setting in pyproject.toml,
and `tests/conftest.py` defined `SRC` but never put it on
`sys.path`. Every other test module copes in one of two ways:
it imports `ghostproxy` only lazily inside test functions (e.g.
`test_harden.py`, by which time a path fix has landed), or it
bootstraps itself — `test_slice_adapter_fallback.py` inserts
`SRC` into `sys.path` before its module-level `ghostproxy`
import. `test_near_duplicates.py` was the only module with a
module-level `ghostproxy` import and no bootstrap, and it is
collected alphabetically before `test_slice_adapter_fallback.py`,
so it could not ride on that module's side effect either. The
documented PYTHONPATH method masked the bug by putting `src` on
the path externally.

Fix (no test weakened, skipped, or deleted; all 9 tests run):
- `tests/test_near_duplicates.py`: added the codebase's own
  established pattern from `test_slice_adapter_fallback.py`
  (import `SRC` from conftest, guarded `sys.path` insert before
  the `ghostproxy` imports, `# noqa: E402`).
- `tests/conftest.py`: added the systemic bootstrap — insert
  `SRC` and `GHOSTSLICE_SRC` (when present) into `sys.path` at
  harness load. This mirrors exactly what `ProxyProcess` already
  does for the proxy subprocess's PYTHONPATH, and makes the
  harness independent of the caller's env and of this copy's
  depth on disk. Standalone check after the fix:
  `python3 -m pytest tests/test_near_duplicates.py -q` →
  `9 passed in 0.86s`.

### 2. Count discrepancy — the truth

Both earlier numbers were correct under different commands; the
discrepancy is the GhostSlice sibling-path condition, not a merge
regression. The 10 plain-method failures are all
`tests/test_slice_adapter_fallback.py::test_fallback_agrees_with_canonical_guard[...]`,
each failing at `from ghostslice.secrets_scan import scan_text`
with `ModuleNotFoundError: No module named 'ghostslice'`:
`ghostproxy.tokens` finds GhostSlice via a sibling-layout path
(`parents[3]/ghostslice/src`) that only resolves when the two
checkouts sit side by side, which these deeper copies do not, so
without GhostSlice's src on PYTHONPATH the import fails. The
`requires_ghostslice` skip guard does not skip them because it
checks the absolute `~/workspace/ghostslice/src` path, which
exists. Under the documented method pristine-check is
`55 passed, 1 xfailed`, confirming the original baseline claim;
under the plain method it is `10 failed, 45 passed, 1 xfailed`,
confirming the coordinator's run. Merged under the plain method
now shows **none** of those 10 failures (the conftest bootstrap
in item 1 puts the real GhostSlice checkout on `sys.path`, so
the parity tests run for real and pass; they are not skipped —
merged plain total is the full 97 passed, 1 xfailed). Merged is
therefore a strict subset of pristine-check under both methods.

### 3. Dead helpers — not present in this tree; audit clean

The brief named a `retry_round` function and a
`RetryStats._classify_round2` from the deepen lane. Neither name
exists anywhere in merged, in any of the three lane copies, or
in pristine (grep over all `.py`/`.md`, zero matches; this
project has no retry code at all), and the original MERGE.md
never mentioned them — that item appears to belong to a
different project's fix brief, so there was nothing to wire in
or remove. A full audit of the actual deepen additions was run
instead: every helper deepen added in `slice_adapter.py`
(`duplicate_fingerprint`, `near_similarity`, `near_threshold`,
`normalize_content`, `line_shingles`, `_gs_duplicates`,
`_local_normalize`, `_local_line_shingles`) is referenced from
`transform.py`, from `duplicate_fingerprint` itself, or from
`tests/test_near_duplicates.py`; a reference scan over all of
merged `src/` found no unreferenced deepen logic and no dead
duplicate logic (the only unreferenced names in `src/` are
`server.py`'s `do_PUT`/`do_PATCH`/`do_DELETE`, which are
`BaseHTTPRequestHandler` dispatch methods invoked by the
framework, and are pristine code).

### 4. Leftovers

Verified: zero `*.orig` and zero `*.rej` files anywhere under
merged (checked before and after this round). `__pycache__` /
`.pytest_cache` from this round's runs were removed from both
merged and pristine-check.

### 5. Harden integrity — re-verified, nothing dropped

Diffed harden lane vs merged for all src files. The four
harden-only src files (`config.py`, `doctor.py`, `ledger.py`,
`server.py`) and `tests/test_harden.py` are byte-identical
between the harden lane and merged. For the two hand-merged
files (`cli.py`, `transform.py`), a line-level check confirmed
every line harden added relative to pristine (7 / 20 lines
respectively; 196 harden-added src lines in total across the
six files) is present in merged. No harden fix is missing.
