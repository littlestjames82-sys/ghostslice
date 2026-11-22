# GhostLogs merge — harden + polish + deepen

Merged tree built as a fresh copy of the pristine tree
(`~/workspace/ghostlogs/`, untouched), then lane changes applied in
order: harden, then polish, then deepen. Multi-lane files were
combined with a 3-way merge (base = pristine) and verified by hand;
single-lane files were copied from their lane.

## Final test counts

Command: `python3 -m pytest -q` (run in each tree at the same
directory depth).

| Tree | Result |
| --- | --- |
| pristine (baseline, per lane reports) | 30 passed |
| harden lane (per its IMPROVE.md) | 51 passed |
| polish lane (per its IMPROVE.md) | 30 passed |
| deepen lane (per its IMPROVE.md) | 38 passed |
| **merged** | **59 passed, 0 failed** |

Merged = 30 baseline + 21 new harden tests + 8 new deepen tests
(polish added no tests). Merged passes at least the best lane
(harden, 51) and every lane's test files are present and passing,
so there are zero new failures versus any lane. Collection check:
test_harden.py 21, test_deepen_overview.py 8, the seven baseline
files 30.

## Files by source lane

Copied from one lane only:

- harden: `tests/test_harden.py` (new file)
- deepen: `tests/test_deepen_overview.py` (new file)
- polish: `examples/README.md`,
  `examples/incident-pack/INCIDENT.md`,
  `examples/incident-pack/manifest.json`,
  `src/ghostlogs/__main__.py`, `src/ghostlogs/tokens.py`

Hand/3-way merged (multiple lanes, all changes survive):

- `README.md` — harden (redaction bullet naming bearer/Basic header
  tokens and both GitHub token styles) + polish (Install, options
  table, exit codes, Custom patterns, Config file, Reading the
  pack, Troubleshooting) + deepen (evidence overview in the pack
  contents and its counting-rules paragraph). All three in
  different regions.
- `src/ghostlogs/cli.py` — harden (config value type checks in
  `_load_config`; output-directory pre-check and OSError-to-exit-2
  wrap in `_cmd_pack`) + polish (module/function docstrings,
  argparse help, descriptions, epilogs; no logic) + deepen (one
  overview summary print reading `m["summary"]`, placed after the
  windows line and after harden's wrapped build). Verified by
  reading the merged `_cmd_pack` end to end: no duplicate logic.
- `src/ghostlogs/patterns.py` — harden (`load_pattern_file`
  converts OSError to ValueError) + polish (docstrings for
  `compile_cli_patterns`, `find_timestamp`, `is_continuation`) +
  deepen (new `hour_bucket()` plus its bucket regexes). Different
  regions.
- `src/ghostlogs/redact.py` — harden (RFC 6750 bearer charset, new
  `basic-auth` shape, url-password allows ':', `github_pat_`
  support, dotted `sk-` keys) + polish (docstrings for
  `_looks_placeholder` and `redact_line`). Different regions; no
  harden fix was altered.
- `src/ghostlogs/analyze.py` — polish (class and `analyze()`
  docstrings) + deepen (evidence-overview tallies counted once per
  line before any claim decision, carried on `Analysis`). Different
  regions.
- `src/ghostlogs/pack.py` — polish (`_Redactor`, `PackResult`,
  `build_pack` docstrings) + deepen (manifest `summary` section,
  `## Evidence overview` section in INCIDENT.md, one LIMITS entry,
  `MAX_BUCKETS_IN_MANIFEST` / `MAX_BUCKETS_IN_DOC`). Different
  regions.

## Conflicts

None. Every multi-lane file merged cleanly (git merge-file returned
0 conflicts on all 16 lane applications), because the lanes touched
disjoint regions of every shared file. No conflict had to be forced,
and no harden fix was dropped or weakened: all harden markers were
grep-verified in the merged tree (config type rejection, pattern
file ValueError, directory pre-check, `_BASIC_RE`, `github_pat_`,
RFC bearer charset, dotted `sk-` charset) and all 21 harden tests
pass in merged.

## Documented lane notes carried over, not "fixed"

- Deepen at budget 850 shipping the exemplars tier instead of
  trimmed is a documented side effect of the overview being
  measured by the tier ladder; accepted as designed. The pack
  still fits with exit 0.
- Harden deliberately left Slack webhook URLs and detached
  private-key body lines uncovered (never claimed shapes). Left
  uncovered in merged, as documented; not treated as a merge task.

## Anything suspicious

- Combination staleness in the polish-supplied examples and README
  prose: polish regenerated `examples/incident-pack/` and wrote
  the README / `examples/README.md` transcripts against pre-deepen
  code, so the checked-in example pack has no manifest `summary`
  and no `## Evidence overview` section, and the README sample
  transcript (708 tokens at budget 2000) lacks the new `overview:`
  line; the README "Reading the pack" list also names five
  INCIDENT.md sections where merged code now emits six (Evidence
  overview sits between Timeline anchors and Error windows). These
  files were kept exactly as the polish lane shipped them per the
  single-lane rule; no test compares the checked-in example pack
  against current code output, so nothing fails, but a regeneration
  of the example pack and a small README touch-up are the natural
  follow-up. Not done here to avoid inventing merged-only content
  during the merge.
- No IMPROVE.md files are present in the merged tree, and test
  caches (`__pycache__`, `.pytest_cache`) were removed after the
  verification run. Pristine was never edited; nothing was pushed.
