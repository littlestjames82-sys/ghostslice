# MERGE.md - ghostmcpdoctor, merged tree (Oct 18, 2026)

Merger: three improvement lanes merged onto a fresh copy of the pristine
tree at `~/workspace/ghostmcpdoctor/` (pristine never edited, nothing
pushed). Lane order applied: harden, then polish, then deepen.
Method: single-lane files copied verbatim; multi-lane files combined
with a three-way merge (`git merge-file`, base = pristine), then
verified file by file (greps for every lane feature, no conflict
markers, no duplicate logic).

## Test counts (python3 -m pytest -q, same directory depth for all)

| Tree | Result |
|---|---|
| Pristine baseline | 44 passed |
| harden lane | 61 passed (44 + 17 new, per its IMPROVE.md and re-run by the merger: 61 passed) |
| polish lane | 44 passed (per its IMPROVE.md and the merger's lane run: 44 passed) |
| deepen lane | 57 passed (44 + 13 new, per its IMPROVE.md and the merger's lane run: 57 passed) |
| **merged** | **74 passed, 0 failed** (`74 passed in 42.89s`) |

Merged = 44 baseline + 17 harden + 13 deepen + 0 polish (docs/help
only), exactly as expected. Merged passes at least what the best lane
passed (61), with zero new failures versus every lane.

## Files by lane

From harden only (copied verbatim):
- `tests/test_harden_regressions.py` (new, 17 tests)

From polish only (copied verbatim):
- `examples/README.md`, `examples/WALKTHROUGH.md`
- `src/ghostmcpdoctor/__main__.py` (module docstring)
- `src/ghostmcpdoctor/reports.py` (docstrings for build_report,
  render_markdown, write_reports)

From deepen only (copied verbatim):
- `tests/test_jsonc.py` (new, 13 tests)

From multiple lanes (hand-verified three-way merges, see Conflicts):
- `src/ghostmcpdoctor/scanner.py` - harden + polish + deepen
- `src/ghostmcpdoctor/checks.py` - harden + polish
- `src/ghostmcpdoctor/cli.py` - harden + polish
- `README.md` - polish + deepen

All other files are pristine, unchanged. No lane `IMPROVE.md` was
copied into the merged tree. No version bump, LICENSE untouched.

## Conflicts and how they were resolved

No file produced a textual merge conflict (zero `<<<<<<<` markers in
any three-way merge); every overlapping file had its lane changes in
different or complementary regions. The overlaps, and the combined
result verified in the merged tree, were:

1. `scanner.py` (all three lanes)
   - `_is_broad_path`: harden rewrote the body (normalised forms,
     trailing slashes, pure `..` traversals, drive roots, home and
     home ancestors); polish added a one-line docstring above the old
     body. Resolution: harden body kept in full, polish docstring
     kept above it. The docstring lists the original roots and is
     accurate, though not exhaustive of the new spellings.
   - `scan_config`: polish added the docstring, deepen changed the
     parse call from `json.loads(text)` to `parse_config_text(text)`,
     harden changed neither. Resolution: both survive; the merged
     function has the polish docstring AND calls
     `parse_config_text` (strict-first, JSONC fallback).
   - Other scanner changes are in disjoint regions and all survive:
     harden's `_secret_shaped` / `_is_wildcard_value` /
     `_parse_disabled` / `_command_display_basename`, `Server.cwd_raw`,
     resolved-path de-dup in `expand_inputs`, URL/backslash handling
     in `_looks_like_path`; polish docstrings on `Server`,
     `ConfigScan`, `client_for_path`, `_looks_like_path`,
     `scan_configs`; deepen's `_strip_jsonc_comments`,
     `_strip_trailing_commas`, `strip_jsonc`, `parse_config_text`.
     No duplicate definitions of any of these.
2. `checks.py` (harden + polish)
   - `_command_exists`: harden rewrote the body (`os.path.expandvars`
     for `$HOME`/`${HOME}`, first-token check for commands embedding
     arguments); polish added its docstring. Both survive.
   - `_resolve`: harden added the `${HOME}` prefix branch; polish
     added the docstring. Both survive.
   - `check_servers`: polish added the header docstring; harden
     changed the cwd resolution inside the loop to use the internal
     `cwd_raw` (`eff_cwd`) so a redacted cwd still resolves. Both
     survive, no duplicate logic.
   - Polish docstring on `finding` also survives.
3. `cli.py` (harden + polish)
   - `_cmd_report`: polish added its docstring; harden added the
     `isinstance(report, dict)` guard, the `_report_shape_ok()` call,
     and the try/except around exit-code recompute + re-render
     (clean exit 2, no traceback). Resolution: polish docstring kept
     on the harden-hardened body; both behaviours present.
   - Disjoint and both present: harden's new `_report_shape_ok()`
     helper; polish docstrings on `_print_summary`, `_cmd_scan`,
     `main`, plus the expanded `--help` description/epilog and all
     argument help text in `main` (argument names, order, defaults
     unchanged).
4. `README.md` (polish + deepen)
   - Different regions: polish added "At a glance", the Quickstart
     output sketch and gotchas, the completed `report` table row,
     "What to do with a finding", and Troubleshooting; deepen rewrote
     the Limits paragraph. Resolution: all polish sections present,
     and the Limits paragraph is deepen's version (see the surviving
     behaviour change note for the JSONC wording). Pristine's
     "Plain JSON only" wording is superseded by deepen's, as intended.

No harden fix was dropped. No conflict was unresolvable, so nothing
had to be left flagged or partially merged.

## Deliberate behaviour change that SURVIVED the merge (required)

**ghostmcpdoctor flagging home-ancestor paths as broad.**
The harden rewrite of `_is_broad_path` in
`src/ghostmcpdoctor/scanner.py` flags an absolute ancestor of home
as BROAD-FILESYSTEM, not just home itself: e.g. `/home` when home is
`/home/user`, also reached via `~/..` or `$HOME/..`, on the ground
that granting an ancestor grants at least everything under home.

Verified in the merged tree, in code and by direct probe:
- Code: the ancestor check is present in the merged `_is_broad_path`
  (`home_norm.startswith(norm.rstrip("/") + "/")` after
  `posixpath.normpath` normalisation).
- Tests: pinned by harden's regression tests in
  `tests/test_harden_regressions.py`, which pass in the merged run.
- Probe (merged tree, home = `/home/user`): `/home` -> broad,
  `/home/user` -> broad, `~/..` -> broad, `$HOME/..` -> broad,
  `/` -> broad, `~/` -> broad; narrow guards hold:
  `/home/user/project` -> not broad,
  `../sibling/server.py` -> not broad. All 8 probe cases matched.

## Anything suspicious

- Nothing suspicious found. No conflict markers, no duplicated
  functions or logic, no dropped lane changes: for every multi-lane
  file, diffing merged against each lane shows only the other lanes'
  changes. Single-lane files are byte-identical to their lane.
- Minor note only: polish's `_is_broad_path` docstring (kept
  verbatim) enumerates the original broad roots; the harden body it
  now sits above also flags trailing-slash spellings, pure `..`
  traversals, `${HOME}` forms, and home ancestors. The docstring is
  true but not exhaustive; no behaviour is affected.
