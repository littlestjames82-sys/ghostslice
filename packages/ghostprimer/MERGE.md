# GhostPrimer merge — Oct 18, 2026 improvement run

Merger: subagent, following the merge protocol (harden first, then
polish, then deepen; pristine tree never edited; nothing pushed).

## Verdict: FLAGGED

One multi-lane behavioural conflict could not be resolved without
losing one lane's pinned behaviour (see "FLAG 1" below). The merged
tree is left exactly as the hand-merge produced it: no test was
edited and no special-case code was invented to force the suite
green. All other lanes' changes survive, and the mandatory
rel-containment question is answered COVERED with evidence below.

## Test counts

Test command (all runs): `python3 -m pytest -q`

| Tree | Result |
|---|---|
| Baseline (pristine copy at same depth, `../pristine-check/`) | 43 passed, 0 failed |
| Harden lane | 55 passed, 0 failed (43 + 12 new in `tests/test_harden.py`) |
| Polish lane | 43 passed, 0 failed (docs/help/docstrings only) |
| Deepen lane | 56 passed, 0 failed (43 + 13 new in `tests/test_stale.py`) |
| **Merged** | **67 passed, 1 failed (68 collected)** |

Expected naive total: 43 baseline + 12 harden + 13 deepen = 68.
The merged tree collects exactly 68; the deviation is the single
failure in FLAG 1, not a lost or duplicated test. Because the
pristine baseline has zero failures, the merged failure set is NOT
a subset of the baseline failure set, so the acceptance criterion
is not met — hence FLAGGED, not CLEAN.

## Multi-lane files and how each was resolved

Method: for every multi-lane file the harden+polish combination was
first produced with a three-way merge (base = pristine,
current = harden, other = polish; `git merge-file`), which was
clean (no conflict markers) for all six files. Deepen's changes
were then hand-applied on top, preserving the polish wording/style.

- `src/ghostprimer/bundle.py` (harden + polish): three-way merge,
  clean. Harden's `_write_text_no_follow` / `_ensure_real_parent`,
  resolved-path checks before reading code/README, no-follow bundle
  writes, and the strengthened `check_bundle` all survive; polish's
  expanded docstrings (`sha256_text`, `build_bundle`, `check_bundle`)
  survive alongside them.
- `src/ghostprimer/memory.py` (harden + polish): three-way merge,
  clean. Harden's recall-bundle confinement, malformed-manifest and
  directory-source handling survive; polish docstrings survive.
- `src/ghostprimer/scan.py` (harden + polish): three-way merge,
  clean. Harden's fail-closed `is_private_memory` /
  `assert_project_local` and pre-read checks in `project_facts`
  survive; polish docstrings survive.
- `src/ghostprimer/cli.py` (harden + polish + deepen): harden+polish
  three-way merge clean (harden's OSError-to-exit-2 backstop and
  polish's full help/epilog survive). Deepen hand-applied on top:
  module docstring now lists `stale`, a `stale` quick-start line and
  epilog example were added, `staleness_report` is imported, a
  `stale` subparser was added between `check` and `doctor` written
  in polish's style (help + description + per-argument help, deepen's
  semantics and `--project` default unchanged), the `mcp` help now
  names `primer_stale`, and the `stale` dispatch
  (`staleness_report(args.bundle, project=args.project)`, JSON print,
  return its code) is deepen's verbatim.
- `src/ghostprimer/mcp_server.py` (harden + polish + deepen):
  harden+polish three-way merge clean (harden's non-object JSON /
  params handling and polish's docstring/tool descriptions survive).
  Deepen hand-applied: docstring tool list, the `primer_stale` tool
  entry (deepen's description/schema verbatim), its import, and its
  `_call_tool` branch (deepen's verbatim) all added.
- `README.md` (polish + deepen; harden did not touch it): polish
  README is the base. Deepen hand-applied: `ghostprimer stale
  <bundle> [--project <dir>]` added to the Commands block, deepen's
  `stale` bullet inserted after the `check` bullet (deepen's text
  verbatim), the `mcp` bullet now lists `primer_stale`, and deepen's
  staleness honest-limits bullet added at the end of "Honest limits".
  Polish's corrected `doctor` wording (no budget outcome) was kept;
  deepen's older `doctor` bullet wording was NOT reintroduced.

Single-lane files were copied outright: harden's
`tests/test_harden.py`; polish's `examples/README.md`,
`src/ghostprimer/__init__.py`, `__main__.py`, `doctor.py`,
`handoff.py`, `secrets.py`, `slicer.py`, `tokens.py`; deepen's
`src/ghostprimer/stale.py` and `tests/test_stale.py` (both
byte-identical to the deepen lane in the merged tree). No
`IMPROVE.md` files are present in the merged tree. No version bump
anywhere (`pyproject.toml` still 0.1.0, identical to pristine);
stdlib only.

## FLAG 1 — harden check_bundle x deepen stale gate (UNRESOLVED)

- Failing test (deepen's, unmodified):
  `tests/test_stale.py::test_stale_refuses_symlinked_source_escaping_project`
  — 67 passed, 1 failed.
- Scenario: build a bundle, then replace a bundled project source
  (`src/widgetforge/core.py`) with a symlink to a file outside the
  project, then run `ghostprimer stale <bundle>`. Deepen's test,
  written against pristine `check_bundle`, expects exit 1 with the
  source listed in stale's own `refused` list.
- What happens in the merged tree: exit 2. Harden strengthened
  `check_bundle` to verify every file entry's source with
  `scan.assert_project_local(root, root / rel)`, so the symlinked
  source now fails `check` itself. Deepen's `stale` is designed to
  gate on `check` ("any check failure makes stale exit 2 rather
  than pronounce on an unverified bundle", deepen IMPROVE.md and
  `stale.py` docstring), so it returns 2 with errors
  `bundle does not pass check; ... refused: source is outside the
  project root: .../src/widgetforge/core.py; total_sliced_tokens
  306 != recomputed 192`.
- Security outcome is NOT weakened: the outside file is refused and
  its content (`OUTSIDE_MARKER`) never appears in the output; the
  refusal is if anything earlier (at check, before stale's own
  re-read). What is lost is only deepen's pinned exit code (1 vs 2)
  and `refused`-list placement for this one scenario. Deepen's own
  refused path remains reachable, e.g. via `--project` pointing at a
  different tree than the manifest root that `check` verified.
- Why the merger did not fix it: every candidate resolution loses
  something pinned. Weakening/reordering harden's `check_bundle`
  source verification drops a harden fix (forbidden). Making
  `stale` special-case check failures that look like source
  refusals and re-map them to exit 1 / `refused` is new
  merger-invented behaviour that contradicts deepen's stated gate
  design. Editing deepen's test to expect 2 would silently rewrite
  a lane's pinned expectation. Per protocol step 3 this is flagged
  for a human/parent decision instead. Suggested decision: accept
  the composed semantics (a bundle whose source has been swapped
  for an escaping symlink no longer passes `check`, so `stale`
  exit 2 "could not check" is the coherent answer) and update that
  one deepen test expectation to exit 2, asserting the refusal text
  appears in `errors` and `OUTSIDE_MARKER` does not appear.

## Mandatory extra verification — rel containment in check_bundle

Verdict: **COVERED** (by the harden lane; no merger fix needed).

Harden's `check_bundle` (`src/ghostprimer/bundle.py`) handles a
forged manifest entry whose `rel` escapes `bundle / "files"` in
two successive layers, both before the exported file is read:

1. Absolute paths are rejected outright
   (`Path(rel).is_absolute()`), and, when a manifest root is
   recorded, `scan.assert_project_local(root, root / rel)` (plus a
   private-memory check) rejects a traversal `rel` whose source
   resolves outside the project root.
2. Independently, the exported file is resolved
   (`resolved_disk = (bundle / "files" / rel).resolve()`,
   `files_root = (bundle / "files").resolve()`) and rejected with
   `"<rel>: exported file path escapes the bundle"` unless it is
   `files_root` itself or lies under it. Because this uses the
   resolved path, a symlink planted inside `files/` pointing
   outside is caught as well. On either rejection the entry is
   skipped (`continue`), so `files_checked` is not incremented and
   the outside file's bytes are never read or hashed into a pass.

Evidence — two reproductions run against this merged tree
(real bundle built with `build_bundle`, manifest then forged,
`check_bundle` called on it):

- Case A, `rel = "../../outside_secret.txt"` naming a real file
  outside both bundle and project, with sha256 and token counts
  forged to match that outside file exactly (the pristine bypass):
  exit 1, errors `refused: source is outside the project root:
  .../proj/../../outside_secret.txt` and
  `total_sliced_tokens 8 != recomputed 0`, `files_checked: 0`.
  Rejected; the outside file was not accepted.
- Case B, containment isolated: `rel = "evil.txt"` (lexically
  inside, and a real in-project source exists at that path so the
  project-local layer passes), but `bundle/files/evil.txt` is a
  symlink to a victim file outside the bundle whose content the
  forged sha256/token counts match: exit 1 with the explicit error
  `evil.txt: exported file path escapes the bundle`,
  `files_checked: 0`. This proves layer 2 itself, not just the
  project-root layer in front of it.

## Merger-authored code

No new logic was authored. The only merger-authored text is
integration wording in the hand-merge, marked here clearly:

- `cli.py`: the `stale` subparser's help/description strings were
  written in polish's help style (deepen's original one-line help
  expanded), plus one-line `stale` mentions in the module docstring
  quick-start, the epilog examples, and the `mcp` subparser
  help/description. All argument names, defaults, dispatch, and
  semantics are deepen's verbatim.
- This `MERGE.md` is the only new file at the merged root.

## Other flags

- None. No other test failed; no harden fix was dropped; no
  IMPROVE.md remains in the merged tree; caches
  (`__pycache__`, `.pytest_cache`) created by the test runs were
  removed from the merged tree afterwards.
- A pristine copy at the same depth was kept at
  `../pristine-check/` for the baseline comparison above.

## Parent resolution (Oct 18, 2026)
FLAG 1 resolved by the parent: the composed exit-2 semantics are ACCEPTED. Harden's strengthened check_bundle refuses the escaping source first, and stale's documented gate (any check failure -> exit 2, could-not-check) is the correct composed behavior; the refusal happens earlier and no outside content is ever read. The one deepen test's expectation was updated accordingly (tests/test_stale.py, test_stale_refuses_symlinked_source_escaping_project): exit 2, refusal naming the source asserted in the report's errors, outside-marker absence still asserted. No lane code was changed. Final merged suite after this resolution: see the parent verification run recorded in the run report.
