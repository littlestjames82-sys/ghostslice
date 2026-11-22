# GhostReplay — merge report (2026-10-18)

Merged tree built as a fresh copy of pristine `~/workspace/ghostreplay/`,
then lane changes applied in order: harden, polish, deepen (3-way merge
per file, `git merge-file` with pristine as base, hand-resolved where
flagged). Pristine tree never edited. No IMPROVE.md carried into merged.

## Test counts (PYTHONPATH=src python3 -m pytest tests -q, all re-run)

- Pristine baseline: 21 passed
- harden lane: 34 passed (21 + 13 new)
- polish lane: 21 passed
- deepen lane: 27 passed (21 + 6 new)
- **merged: 40 passed, 0 failed** (21 + 13 harden + 6 deepen; polish adds
  no tests). Merged passes the union of all lanes, zero new failures
  versus every lane.

## Files by source

### Single-lane (copied verbatim)
- harden only: `tests/test_harden.py` (new)
- deepen only: `tests/test_deepen_rereads.py` (new)
- polish only: `src/ghostreplay/__main__.py`, `src/ghostreplay/profile.py`,
  `src/ghostreplay/tokens.py`, `examples/EXPECTED_OUTPUT.md`,
  `examples/run_demo.sh`

### Two-lane (3-way merge, no conflicts)
- `src/ghostreplay/bundle.py` — harden (`_token_count`/`_symbols`
  manifest validation) + polish (docstrings on `BundleError`,
  `load_manifest`, `find_bundle`)
- `src/ghostreplay/ledger.py` — harden (`errors="replace"` read, `_num`
  coercion in `trend_summary`) + polish (docstrings)
- `src/ghostreplay/secrets.py` — harden (dict-key sanitizing in
  `sanitize_obj`) + polish (`scan_text` docstring)
- `src/ghostreplay/transcript.py` — harden (`_validate_canonical`,
  bool-usage rejection) + polish (expanded docstrings)
- `src/ghostreplay/report.py` — polish (docstrings) + deepen
  (Turn timeline section in REPLAY.md)
- `README.md` — polish (contents, demo, commands table, config,
  troubleshooting, etc.) + deepen (corrected re-read definition,
  turn timeline, re-read hotspots bullets in "What a report shows")

### Three-lane
- `src/ghostreplay/cli.py` — harden (`_safe_session_component` path
  traversal guard, `import re`) + polish (module docstring, help text,
  epilogs) + deepen (propose summary line reports re-read hotspot
  count). No conflicts.
- `src/ghostreplay/analysis.py` — harden (`_inside_project` escape
  guard) + polish (docstrings) + deepen (tool-input-only re-read
  accounting, `turn_timeline`, `direct_read_turns`, new qualifier).
  One conflict, resolved below.
- `src/ghostreplay/propose.py` — harden (duplicate-session dedup,
  `load_proposal` changes validation) + polish (docstrings) + deepen
  (`reread_hotspots` aggregation + PROPOSAL.md section). One conflict,
  resolved below.

## Conflicts and resolutions

1. `analysis.py` — `file_token_estimate`: harden replaced
   `Path(project) / rel` with the `_inside_project` guard; polish added
   a docstring to the same function. Resolution: kept BOTH — polish
   docstring first, then harden's guarded body. No logic dropped.
2. `propose.py` — `build_proposal` opening: harden inserted the
   duplicate-session dedup block where polish inserted the function
   docstring. Resolution: kept BOTH — docstring first, dedup block
   immediately after, before `n = len(session_reports)`.

## Semantic interaction worth noting (not a conflict)

Harden's dedup runs at the top of `build_proposal`, so deepen's
`reread_hotspots` aggregation (and its `n`) now operates on the
deduplicated report list. That is the correct combined behaviour:
the same session submitted twice cannot inflate hotspot evidence
either. Deepen's hotspot tests (distinct sessions) pass unchanged.

Also: harden's `load_proposal` validation covers `changes`,
`diagnostic_changes`, and `recall_candidates`; deepen adds
`reread_hotspots` to proposal dicts but (as in the deepen lane itself)
`load_proposal` does not validate/default that key — consumers use
`proposal.get('reread_hotspots') or []`, so old proposal files still
load. Unchanged from the lanes; noted for completeness.

## Suspicious / flagged

- Nothing suspicious. No harden fix was dropped; grep-verified presence
  of every lane feature in merged (`_safe_session_component`,
  `_inside_project`, `_token_count`/`_symbols`, `_validate_canonical`,
  `_num`, key sanitizing, dedup, docstrings/help, `turn_timeline`,
  `reread_hotspots`). No conflict markers remain; all modules compile.
