# GhostPacks - Agent B Report (tests / README / examples)
Date: Oct 14, 2026. Scope owned: tests/**, README.md, examples/**, this report.
Not touched: src/**, pyproject.toml, packs/** (Agent A's).

## What was delivered

- `tests/conftest.py` - CLI helpers, pack/project factories, and a real
  GhostSlice export helper (uses the sibling ~/workspace/ghostslice
  checkout, `GHOSTSLICE_SRC` override). All assumed core interface
  details are centralised here, with a header documenting them.
- `tests/test_lint_safety.py` (8 tests) - valid pack passes; pack with a
  script file (.py/.sh/.js parametrised), a nested script file, or an
  executable-bit file fails lint naming the file; absolute path in the
  fragment fails; kind != "context" fails; missing manifest fails.
- `tests/test_score_honesty.py` (6 tests) - unscored pack passes lint
  and `show` labels it unscored; scored pack with its report passes and
  shows its score; claimed score with a missing report file, or with no
  report reference at all, fails lint.
- `tests/test_merge_unknown_key.py` (5 tests) - fragment with unknown
  key `bogus_pack_key_xyz` fails merge with the key named, failed merge
  leaves profile + lockfile untouched, valid merge applies modes/ignore
  and records lockfile provenance (id + version), declining at the
  preview leaves the project untouched.
- `tests/test_merge_remove_roundtrip.py` (3 tests) - merge/export/
  remove/export totals round-trip (real GhostSlice exporter),
  remove-of-never-merged fails cleanly, remove after a user edit
  reports not-cleanly-reversible and preserves the edit.
- `README.md` - full v0.1 README: hard rules, pack format, CLI usage,
  starter packs, honest notes.
- `examples/` - `demo-python-pack/` (valid, deliberately unscored;
  verified: `lint` OK, `show` prints unscored), `fixture-project/`
  (two-file Python project, baseline profile), `bench-report.template.json`,
  and a walkthrough `examples/README.md` using the real CLI syntax.
- All example JSON validated with `json.tool`. The three starter packs
  in packs/** (Agent A) were also smoke-checked read-only: all lint OK,
  all labelled unscored.

## Results (honest pass/fail)

Command: `PYTHONPATH=src python3 -m pytest tests -q` (run twice, stable)

**22 passed, 1 failed.**

All five behaviours the task named are covered. Four pass against
Agent A's core as shipped. One fails, and the failure is a real core
integration defect, not a test bug:

### FAIL: test_merge_remove_roundtrip_restores_export_totals

PLAN.md's verification bar: merge a pack, export, remove the pack,
export again, and the second export must match the pre-merge totals
exactly. Measured on the test fixture (real GhostSlice exporter):

- baseline export: original 249 / sliced 179
  (files: src/app.py, src/util.py, .ghostslice.json)
- after merge: original 465 / sliced 395 in the pytest fixture
  (440 / 370 in a hand rerun with a leaner fragment)

Root cause, verified by listing the merged export's manifest files:
GhostSlice scans GhostPacks' own bookkeeping as project content.
The merged export includes `.ghostslice-packs.json` (the lockfile) and
`.ghostslice-packs-backup/<stamp>-demo-python-0.1.0.ghostslice.json.bak`
(the kept pre-merge backup). After `remove`, the backup file remains
on disk, so the post-remove export is also inflated (275 / 205 in the
hand rerun vs the 249 / 179 baseline). GhostSlice already ignores its
own `.ghostslice-history.jsonl` by name in the scanner, but knows
nothing about GhostPacks' files.

Fix options (Agent A / parent call, outside my file ownership):
1. GhostPacks merge adds `.ghostslice-packs.json` and
   `.ghostslice-packs-backup/**` to the merged profile's `ignore`
   list (does not fix post-remove exports, where the restored
   profile no longer carries those ignores but the files remain), or
2. GhostSlice's scanner learns the GhostPacks bookkeeping names the
   way it already knows the history ledger, or
3. GhostPacks keeps bookkeeping outside the scanned tree.

The test was deliberately NOT weakened to hide this: it asserts the
PLAN.md bar verbatim.

## Assumptions (all verified against Agent A's core as it landed)

Agent A's core arrived in parallel while these tests were written.
Initial assumptions in conftest were reconciled with the shipped
`src/ghostpacks/cli.py` and `pack.py`; the final state is:

- Package layout `src/ghostpacks/`, run as `python -m ghostpacks`
  with PYTHONPATH=src. Matches.
- CLI syntax: `lint <pack>`, `show <pack>`, `merge <pack> <project>`,
  `remove <project> <pack-id>`; confirmation on stdin unless `--yes`.
  Matches the shipped CLI (an earlier draft of the helpers used
  --project flags and was corrected to this).
- Pack format: `pack.json` + `profile.json`, `kind: "context"`,
  profile keys exactly the `.ghostslice.json` schema keys. Matches.
- Bench claim shape: `bench: {"score": <number>, "report": "<file>"}`
  (a top-level `score` also counts as a claim in the core). Matches;
  README and examples were updated from an earlier savings_percent
  draft to this shape.
- Merge writes `.ghostslice-packs.json` lockfile with a `packs` list
  and keeps a backup under `.ghostslice-packs-backup/`. Matches.
- The round-trip's GhostSlice exports use the sibling checkout
  (v1.0.6, manifest totals keys total_original/sliced/saved_tokens).

## Gates honoured

No network, no push, no publish, no spend. Tests write only to pytest
tmp dirs. Starter packs and src were only ever read or executed,
never edited.
