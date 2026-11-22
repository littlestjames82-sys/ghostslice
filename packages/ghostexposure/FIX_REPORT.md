# GhostExposure Fix Report - bundles now pass `ghostslice check`

Date: Oct 14, 2026
Task: parent-directed fix. Parent cross-check found an Exposure bundle did
not pass GhostSlice's checker, although PLAN.md / README claim the bundle
is a normal Slice bundle that validates with it.
Gates held: stdlib only, evidence-only copy rules unchanged, no network,
no push/publish/spend, no tests edited (nothing under `tests/**` touched).

## Defect reproduced (before the fix)

Export: `examples/mini_project` with `surfaces/starter.json`, then from
`~/workspace/ghostslice`:

    PYTHONPATH=src python3 -m ghostslice check <bundle>

Result before the fix:

    {
      "ok": false,
      "errors": [
        "manifest: 'total_original_tokens' is missing or not an integer",
        "auth/login.py: sliced_tokens None != recomputed 73",
        "total_sliced_tokens None != recomputed 73"
      ],
      "files_checked": 1,
      "total_sliced_tokens": 73,
      "total_original_tokens": 0,
      "artifacts_checked": [],
      "redaction_checked": false
    }

Root causes, all in the Exposure manifest writer:

1. Schema mismatch. The manifest used Exposure-only names
   (`original_estimated_tokens`, `exported_estimated_tokens`, and a
   `totals` dict with `exported_estimated_tokens`) and had none of the
   GhostSlice bundle fields GhostSlice's `validate_bundle`
   (`ghostslice/src/ghostslice/exporter.py`) requires: per-file
   `original_tokens` / `sliced_tokens` and top-level integer
   `total_original_tokens` / `total_sliced_tokens` /
   `total_saved_tokens`.
2. Estimator mismatch. Exposure estimated tokens as
   `ceil(len(text)/4)` (its `inventory.estimate_tokens`), while
   GhostSlice's checker recomputes `sliced_tokens` from the bundle
   files with GhostSlice's calibrated estimator
   (`ghostslice.tokens.estimate_tokens` with the per-file language
   from `ghostslice.scanner.language_for`). Even with the field names
   fixed, the numbers would not have matched (Exposure said 67 for
   `auth/login.py`, GhostSlice recomputes 73).
3. Binary mode. Binary payloads were recorded with mode
   `full-binary`, which is not a GhostSlice mode, with token figures
   that cannot validate for non-UTF-8 bytes under GhostSlice's
   text-based recomputation.

## Fix (all under `src/ghostexposure/`)

Reference used: GhostSlice `exporter.py` (manifest written by
`build_bundle` and checked by `validate_bundle`) and GhostPort
`src/ghostport/bundle.py` + `src/ghostport/tokens.py`, whose bundles
pass `ghostslice check`.

- New `src/ghostexposure/tokens.py`, following the GhostPort pattern:
  prefers GhostSlice's `estimate_tokens` + `METHOD` and
  `scanner.language_for` when a GhostSlice install/checkout is
  reachable (direct import, else the sibling checkout
  `~/workspace/ghostslice/src`, also derived relative to this file),
  and falls back to a documented `ceil(len(text)/4)` estimate with
  its own method string when GhostSlice is not reachable. The
  manifest records which method produced its figures in
  `token_method`.
- `src/ghostexposure/inventory.py`: `estimate_tokens(text, path=None)`
  now delegates to `tokens.estimate_tokens`, so inventory/partition
  figures use the same estimator and per-file language as the
  manifest.
- `src/ghostexposure/partition.py`: the partition record now calls
  `estimate_tokens(text, path)` so its `estimated_tokens` matches the
  manifest `original_tokens` for the same file.
- `src/ghostexposure/exporter.py`: the manifest writer now emits the
  GhostSlice bundle schema alongside the Exposure fields:
  - per file: `original_tokens`, `sliced_tokens` (GhostSlice
    estimator, per-file language), plus `language` and `package`,
    while keeping `decision`, `reasons`,
    `original_estimated_tokens`, and `exported_estimated_tokens` so
    existing Exposure readers keep working (the `*_estimated_*`
    values now hold the same GhostSlice-estimator figures);
  - top level: `generated_at`, `root`, `token_method`,
    `total_original_tokens`, `total_sliced_tokens`,
    `total_saved_tokens` (all integers, totals are the sums of the
    per-file fields), while keeping the legacy `totals` dict
    (`files_in_bundle`, `exported_estimated_tokens`, now also
    `original_tokens` / `sliced_tokens`) that `EXPOSURE.md`
    rendering uses;
  - binary payloads: still carried verbatim under `files/` with the
    raw-bytes sha256 Exposure's own verifier checks, but recorded
    with mode `exclude` and `sliced_tokens` 0 (the record GhostSlice
    uses for non-sliced files, and the one its checker skips),
    flagged `"binary": true, "carried_verbatim": true` in the
    manifest entry so the mode is not misread.
- No changes to Exposure's own `verify_bundle` logic, its
  evidence-only statements, or any test.

## Verification (after the fix)

Full Exposure suite, from `~/workspace/ghostexposure`:

    python3 -m pytest tests -q
    .........................                                                [100%]
    25 passed in 1.74s

(25 passed, same as the pre-fix baseline stated in the task.)

Fresh export (same reproduction case as the defect):

    PYTHONPATH=src python3 -m ghostexposure export examples/mini_project --surface surfaces/starter.json -o /tmp/ghostexposure-fresh/bundle
    PYTHONPATH=src python3 -m ghostexposure verify /tmp/ghostexposure-fresh/bundle   # exit 0

    Bundle on disk matches its manifest and partition.

GhostSlice check on that fresh export, from `~/workspace/ghostslice`
(exit 0), verbatim:

    {
      "ok": true,
      "errors": [],
      "files_checked": 1,
      "total_sliced_tokens": 73,
      "total_original_tokens": 73,
      "artifacts_checked": [],
      "redaction_checked": false
    }

Additional spot checks, each passing BOTH Exposure verify (exit 0)
and `ghostslice check` (`"ok": true`, exit 0):

- `tests/fixtures/basic_project` with the fixture starter pack:
  4 files checked, total_sliced_tokens 261, total_original_tokens 261.
- `tests/fixtures/planted_key_project` (redaction path): 2 files
  checked, total_sliced_tokens 144, total_original_tokens 148,
  redaction still recorded and the fake literal still absent from
  the exported copy.
- A synthetic project with a distance-1 context caller (Python,
  `signatures` mode): 2 files checked, total_sliced_tokens 114,
  total_original_tokens 130.
- A synthetic project with a binary surface file (`auth/token.bin`,
  non-UTF-8 bytes): both verifiers pass; GhostSlice checks the
  1 text file, the binary is carried verbatim as described above.

## Files changed

- `src/ghostexposure/tokens.py` (new)
- `src/ghostexposure/inventory.py` (estimator delegates, path-aware)
- `src/ghostexposure/partition.py` (passes the file path to the estimator)
- `src/ghostexposure/exporter.py` (GhostSlice-schema manifest writer,
  binary record, totals)
- `FIX_REPORT.md` (this file)

No files under `tests/**` were edited. No network, push, publish, or
spend.
