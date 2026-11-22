# GhostExposure — merge of harden + polish + deepen lanes

- Tool: ghostexposure
- Merged tree: `~/workspace/.improve-2026-10-18/ghostexposure/merged/` (fresh copy of pristine `~/workspace/ghostexposure/`, caches excluded; pristine never edited, nothing pushed)
- Lane order applied: harden, then polish, then deepen (3-way merge per file, base = pristine)

## Test counts (all verified by running `python3 -m pytest -q` in each tree)

| Tree | Result |
|---|---|
| pristine (baseline, per lane IMPROVE.md files) | 34 passed |
| harden | 60 passed (34 + 26 new in `tests/test_harden.py`) |
| polish | 34 passed (docs/help only, no new tests) |
| deepen | 48 passed (34 + 14 new in `tests/test_match_evidence.py`) |
| **merged** | **74 passed, 0 failed** (34 baseline + 26 harden + 14 deepen) |

Merged passes everything every lane passed, with zero new failures versus any lane.

## File provenance

Single-lane files (copied from that lane):

- harden only: `tests/test_harden.py` (new)
- deepen only: `tests/test_match_evidence.py` (new)
- polish only: `examples/README.md`, `src/ghostexposure/__init__.py`, `src/ghostexposure/__main__.py`, `src/ghostexposure/tokens.py`
- harden only (code): none besides the test file; every harden code file was also touched by another lane (see below)

Multi-lane files (hand/3-way merged, both lanes' changes survive):

- `src/ghostexposure/secrets.py` — harden (CRLF offset fix, contained-finding drop, PEM truncation guard, span-merging `redact_text`) + polish (expanded `find_literals`/`redact_text` docstrings). One textual conflict, see below.
- `src/ghostexposure/surface.py` — harden (full `load_pack` validation, named `SurfaceError` for every malformed pack) + polish (module/function docstrings). Clean 3-way merge; regions disjoint.
- `src/ghostexposure/inventory.py` — harden (fail-closed symlink/FIFO/unreadable handling in `build_inventory`) + polish (module/function docstrings). Clean 3-way merge.
- `src/ghostexposure/partition.py` — harden (`_pin_list` normalisation + non-object profile guard in `load_profile_pins`) + polish (docstrings for `load_profile_pins`, `_glob_hit`, `_pattern_hits`, `_module_to_paths`, `build_partition`, `partition_counts`) + deepen (`MAX_EVIDENCE_LINES`, `_text_pattern_evidence`, line-evidence fields in `_pattern_hits`, new `pattern_coverage()`, uniform evidence fields on pin/graph reasons). Clean 3-way merges; polish docstring for `_pattern_hits` still accurately describes deepen's implementation (regex with substring fallback lives in `_text_pattern_evidence`).
- `src/ghostexposure/exporter.py` — harden (`signatures_source` async/return-annotation/AnnAssign fidelity, export-to-file `ExportError`, defensive `verify_bundle` with `valid_entries`, duplicate-manifest detection) + polish (docstrings for `signatures_source`, `_sha`, `export_bundle`, `render_exposure_md`, `verify_bundle`) + deepen (`pattern_coverage` written to `exposure.json`, Pattern coverage section in `EXPOSURE.md`, coverage-vs-partition check in `verify_bundle`). Clean 3-way merge plus one merge-resolution fix, see below.
- `src/ghostexposure/cli.py` — polish (help text, epilogs, docstrings) + deepen (`pattern_coverage` import, scan line numbers and Pattern coverage summary, `pattern_coverage` in `--json`). Clean 3-way merge.
- `README.md` — polish (Quick start, Key terms, troubleshooting, etc.) + deepen (bundle-table rows describing line evidence and the per-pattern coverage record). One textual conflict, see below.

No other files differ from pristine. Merged differs from pristine in exactly the union of the lane changes: 11 modified files + 2 new test files.

## Conflicts and how they were resolved

1. **`secrets.py` — `redact_text` docstring (harden vs polish).** Both lanes rewrote the same docstring; harden also replaced the body with span-merging logic. Resolution: harden body kept verbatim; docstrings combined (polish's "Return text with each finding span replaced by REDACTED / findings as returned by find_literals / copy-only effect" plus harden's overlapping-span explanation, reworded to say merged spans are applied backwards). No duplicate logic; harden behaviour unchanged.

2. **`README.md` — bundle table rows (polish vs deepen).** Deepen rewrote the `exposure.json` and `EXPOSURE.md` rows; polish appended "Read this first." to the `EXPOSURE.md` row and added a `PROMPT.md` row directly below. Resolution: deepen's row text for both rows, polish's "Read this first." suffix kept on the `EXPOSURE.md` row, polish's `PROMPT.md` row kept.

3. **`exporter.py` — `verify_bundle` coverage check (harden x deepen, semantic, found by probing).** The plain 3-way merge applied cleanly but combined badly: deepen's new coverage block recomputed coverage from the raw `partition` list and read `surface_pack`/`pattern_coverage` entries with bare `.get` calls. On a corrupt bundle that also carries a `pattern_coverage` record (i.e. every bundle written by the merged tool), malformed partition entries, non-object coverage entries, or a non-list `surface_pack.patterns` made `verify_bundle` crash with `AttributeError`/`TypeError` — directly violating harden's guarantee that verify reports corrupt bundles as named problems and never crashes. Probe evidence (before fix): 4 of 5 tamper cases crashed. Merge-resolution fix applied to the merged tree only (not a lane change): the coverage block now recomputes from harden's validated `valid_entries`, filters recorded pack patterns to dicts with a string `id` and all required fields, reports non-object coverage entries and non-scalar `pattern_id` values as named problems, and sorts pattern ids with `key=str`. After the fix, all 9 tamper probes (including list-valued ids and a dict-shaped `pattern_coverage`) return `ok=False` with named problems, an untampered bundle still verifies `ok=True`, and the full suite still passes 74/74. Deepen's behaviour on every well-formed bundle is unchanged (`valid_entries` equals `partition` whenever all entries are valid).

## Anything suspicious

- Nothing else found. Every harden fix is present and covered by its regression tests in the merged suite (CRLF redaction, nested-span merge, truncated PEM, symlink/FIFO fail-closed, pack validation, pin normalisation, verify robustness, signatures fidelity). No duplicate definitions remain (checked: exactly one def each for `pattern_coverage`, `redact_text`, `find_literals`, `verify_bundle`, `build_partition`, `load_pack`, `build_inventory`). No `IMPROVE.md` was carried into the merged tree. Pristine tree untouched; lane trees unchanged by the merge (their diffs against pristine are identical to before the merge).
- Note: the merge-resolution fix in item 3 is the only code in merged that appears in no lane. It exists solely to make the harden and deepen guarantees hold simultaneously.
