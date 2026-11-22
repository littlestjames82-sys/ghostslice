# GhostDeps — merge of harden / polish / deepen lanes

Tool: ghostdeps
Date: 2026-10-18
Base: pristine tree `~/workspace/ghostdeps/` (never edited)
Merge order applied: harden, then polish, then deepen
Method: per-file comparison against pristine (`diff -rq` + individual
diffs); single-lane files copied, multi-lane files combined with
3-way merge (pristine as base) and hand-resolution where noted.

## Final test counts

Command: `python3 -m pytest -q` in each tree.

| Tree | Result |
| --- | --- |
| Pristine baseline | 24 passed (per all three lane IMPROVE.md files) |
| harden lane | 43 passed (24 + 19 new in `tests/test_harden.py`) |
| polish lane | 24 passed (no new tests, no regressions) |
| deepen lane | 32 passed (24 + 8 new in `tests/test_cargo_lock.py`) |
| **merged** | **51 passed in 38.30s, zero failures** |

51 = 24 baseline + 19 harden + 8 deepen, with polish documentation
changes included. Merged passes at least what the best lane passed
(harden, 43) and has zero new failures versus every lane. Lane counts
are taken from each lane's IMPROVE.md; the merged count was run live
in the merged tree.

## Files by lane

Unchanged from pristine: everything not listed below (PLAN.md,
FIX_REPORT.md, IMPLEMENTATION_A.md, POLISH_REPORT.md, REPORT_B.md,
LICENSE, pyproject.toml, examples projects, and all pre-existing
tests).

### Harden only (copied from harden)

- `src/ghostdeps/ignores.py` — utf-8-sig reads; non-object
  `.ghostslice.json` now warns instead of silently applying nothing.
- `tests/test_harden.py` — new, 19 regression tests.

### Polish only (copied from polish)

- `examples/README.md` — run context, why examples exit 1, reading
  the machine-readable pack.
- `src/ghostdeps/__init__.py` — expanded package docstring.
- `src/ghostdeps/__main__.py` — new module docstring.

### Deepen only (copied from deepen)

- `tests/test_cargo_lock.py` — new, 8 Cargo.lock tests.

### Harden + polish (clean 3-way merge, different regions)

- `src/ghostdeps/cli.py` — harden: `pack` write/render failures now
  return exit 2 with a message instead of a traceback. Polish:
  docstrings for `_analyse`/`cmd_pack`/`cmd_doctor`/`main` and full
  argparse help/descriptions/epilogs. Both survive.
- `src/ghostdeps/imports_scan.py` — harden: utf-8-sig reads, Python
  scan OSError/RecursionError recorded as parse failure, new
  `_strip_rust_comments` used by the Rust scanner. Polish:
  docstrings for `ImportIndex`/`add()`/`scan_imports()`. Both survive.
- `src/ghostdeps/names.py` — harden: `js_package_name` rejects
  malformed scoped specifiers, whitespace names, and Windows drive
  paths, and strips the `node:` prefix. Polish: `js_builtin()`
  docstring. Both survive.

### Polish + deepen (clean 3-way merge, different regions)

- `README.md` — polish: Quick start, pack-vs-doctor table, reading
  the four sections, exit-code table, Common questions. Deepen:
  `Cargo.lock` summary parsing documented in the Rust bullet and the
  honest-limits lockfile note. Verified: merged vs polish differs
  only by the deepen hunks, and merged vs deepen differs only by the
  polish hunks.

### Harden + polish + deepen

- `src/ghostdeps/xref.py` — clean 3-way merges, different regions.
  Harden: wildcard specs (`1.2.*`, `==1.2.*`, `1.2.x`, `1.*`) no
  longer recorded as exact pins (`_spec_pin`), and the banned-wording
  guard now scrubs evidence strings via new `_evidence_strings` /
  `_scrub_evidence`. Polish: `build_pack()` and `render_deps_md()`
  docstrings. Deepen: stale Cargo.lock comment corrected and a
  Cargo.lock summary-level line added to the DEPS.md Limits section.
  All three survive.
- `src/ghostdeps/manifests.py` — harden + deepen merged cleanly;
  polish produced the merge's one real conflict (see below).
  Harden: type-guarded manifest parsing (`_as_dict`/`_as_list`/
  `_req_list`/`_poetry_spec`/`_js_spec`), utf-8-sig reads, parser
  failure isolation in `discover_sources`, `parse_pep508` remainder
  rejection, wider requirements-include matcher. Polish: docstrings
  for `SourceResult`/`record()`, `_parse_pyproject`,
  `_parse_requirements`, `_parse_package_json`, `_parse_cargo_toml`,
  `_cargo_section`, `_is_requirements`. Deepen: new
  `_parse_cargo_lock` + `_cargo_lock_dep_name`, `cargo.lock`
  registered in `_PARSERS` and removed from `DETECTED_ONLY_NAMES`.

## Conflicts and resolutions

1. `src/ghostdeps/manifests.py` — `_cargo_section` (the only
   conflict in the whole merge). Harden and polish changed the same
   region differently:
   - Harden replaced the loop header `(table or {}).items()` with a
     type guard (`if table is not None and not isinstance(table,
     dict): _note(...); return`) followed by
     `_as_dict(table).items()`.
   - Polish kept the original loop line and added the docstring
     `"""Append one Cargo dependency table (string or inline-table
     form) to ``res``."""` directly above it.
   Resolution: kept BOTH — the polish docstring, then harden's type
   guard and `_as_dict(table).items()` loop. Polish's superseded
   `(table or {})` loop line was dropped because harden's version
   replaces it; no logic was duplicated. No harden fix was dropped.
   After this hand-resolution, the deepen changes were merged in
   cleanly on top.

No other file conflicted. No harden-lane fix was dropped anywhere.

## Anything suspicious

- Nothing suspicious found. All lane changes are present in merged,
  verified by marker checks per file (e.g. `_strip_rust_comments`,
  `_scrub_evidence`, `_parse_cargo_lock`, CLI exit-2 message, polish
  docstrings/help epilogs, README Quick start + Cargo.lock text) in
  addition to the combined test suite passing.
- No `IMPROVE.md` files were carried into merged (removed / never
  copied; verified none present).
- Test caches (`__pycache__`, `.pytest_cache`) were removed from
  merged after the test run, so the tree is file-clean.
- The initial pristine copy emitted harmless tar ownership warnings
  in the sandbox; the copy was verified `diff -rq`-identical to
  pristine before any lane changes were applied.
