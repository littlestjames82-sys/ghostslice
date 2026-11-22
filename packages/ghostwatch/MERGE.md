# GhostWatch — merge of harden + polish + deepen (Oct 18, 2026)

Merger output. Pristine tree `~/workspace/ghostwatch/` was never edited;
nothing was pushed anywhere. Lanes applied in order: harden, polish, deepen.

## Test counts (all run in this session, `PYTHONPATH=src python3 -m pytest tests -q`)

| Tree | Result |
|---|---|
| Baseline (pristine, per all three IMPROVE.md records) | 51 passed |
| harden lane (re-run by merger) | 65 passed |
| polish lane (re-run by merger) | 51 passed |
| deepen lane (re-run by merger) | 65 passed |
| **merged (this tree)** | **79 passed, 0 failed** |

Merged = 51 baseline + 14 harden tests + 14 deepen tests (polish added no
tests). Zero new failures versus every lane; merged passes strictly more
than the best single lane (65). Lane counts above were re-run by the
merger, not just copied from the IMPROVE.md records (they agree).

## Files by lane

Single-lane files (copied verbatim from that lane, verified byte-identical):

- polish: `examples/README.md`, `src/ghostwatch/__init__.py`,
  `src/ghostwatch/__main__.py`
- harden: `tests/test_harden_pass.py` (new)
- deepen: `tests/test_freshness_analysis.py` (new)

Multi-lane files (hand-merged, see Conflicts):

- `src/ghostwatch/core.py` — harden + polish + deepen
- `src/ghostwatch/cli.py` — harden + polish + deepen
- `README.md` — polish + deepen

All other files are pristine. No lane `IMPROVE.md` was carried into this
tree.

## Conflicts and how they were resolved

No harden fix was dropped. There were no irreconcilable conflicts; every
overlap was in adjacent or complementary regions and both sides survive.
Verified mechanically: `diff merged vs polish` for core.py/cli.py contains
*only* harden+deepen additions, and `diff merged vs deepen` contains *only*
harden+polish changes (expanded docstrings replacing the one-line
originals, plus the harden logic).

### core.py

1. `_parse_ts` — harden rewrote the body (naive timestamps read as UTC,
   overflow guard); polish added a one-line docstring; deepen consumes it
   via `_age_seconds`. Resolution: polish docstring + harden body.
   Deepen's age math therefore inherits the timezone-independent parsing.
2. `read_bundle_info` — polish expanded the docstring; harden changed the
   `symbols_included` line to filter non-strings. Both kept.
3. `check_project` — polish expanded the docstring; harden added the
   `missing_bundle_file` loop for bundled files absent from both baseline
   and disk; deepen added `size_before/size_after/size_delta` to the
   removed/added/changed findings, hoisted `bundle_replaced` (initialised
   `False` so the heuristic path can pass it to `compute_freshness`),
   captured `checked_at` once, and attached the `freshness` object.
   Resolution: all three combined in place; no region was edited by two
   lanes in incompatible ways. Combined behaviour worth noting: harden
   `missing_bundle_file` findings are counted by deepen's
   `compute_freshness` (`stale_paths`/drift/score), which is the intended
   interaction — the deepen code already listed that finding class.
4. `render_markdown` — polish added a docstring; deepen added the
   Freshness analysis section and the size-delta line format. Both kept.
5. Remaining polish docstrings (`utc_now`, `extract_symbols`,
   `save_snapshot`, `load_snapshot`, `default_snapshot_path`,
   `resolve_bundle`, `exit_code_for`) and harden's `_validate_snapshot`
   non-string-symbol rejection touch regions no other lane edited;
   applied directly. Each merged definition appears exactly once
   (grep-verified, no duplicate logic).

### cli.py

1. `_write_reports` — harden introduced `_write_text_out` (creates parent
   dirs) and routed both writes through it; polish added a docstring.
   Resolution: polish docstring + harden implementation.
2. `_print_summary` — polish added a docstring; deepen added the
   freshness score/severity/drift lines plus recommendation. Both kept.
3. `cmd_snapshot` / `cmd_check` / `cmd_watch` — polish added docstrings;
   harden wrapped the snapshot/report writes in `try/except OSError`
   returning exit 2. Both kept in each command.
4. `build_parser` — the deepest overlap. Polish restructured the parser
   (per-subcommand descriptions, help for every flag, `common(...,
   writing_snapshot=...)`, `report_args`, `stale_args` helpers) but kept
   `type=float`/`type=int` for watch; harden added `_interval_arg` /
   `_max_polls_arg` validators and `import math`. Resolution: polish's
   parser structure and help text wholesale, with the two watch arguments
   switched to harden's validator types while keeping polish's
   `metavar`/help. Smoke-tested after merge: `watch --help` shows the
   polish help, and `--interval -1`, `--interval nan`, `--max-polls 0`
   each fail as clean usage errors with exit 2.

### README.md

Polish rewrote the intro/Quickstart/Status/snapshot sections and fixed
the `--strict-added` table row; deepen inserted one Freshness analysis
paragraph in the Check section, between the symbol-staleness paragraph
and the Pack staleness paragraph — a region polish did not edit.
Resolution: polish README as base with deepen's paragraph inserted
verbatim at its original anchor. `diff merged vs polish` is exactly that
one paragraph.

## Anything suspicious

- Nothing suspicious found. All three lanes respected the shared hard
  rules (stdlib only, no version bump, reports-only / never silently
  refreshes) and their changes compose: the only cross-lane behavioural
  interaction is the beneficial one in core.py note 3 above.
- One deliberate behaviour combination to be aware of: in `check`, a
  report-write failure now returns exit 2 (harden) even when the verdict
  was computed, and the freshness lines (deepen) print only on the
  success path via `_print_summary`. This matches harden's documented
  rationale (CI should notice the missing artifact).
- Polish's two documented-but-unfixed quirks remain as polish left them:
  `snapshot --snapshot` is accepted and ignored (help says so), and
  `check --write-report` is a symmetry no-op (help says so). Harden's
  validators do not change either.
