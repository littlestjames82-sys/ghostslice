# GhostWatch - Agent B Report (tests / README / examples)
Date: Oct 14, 2026. Scope owned: tests/**, README.md, examples/**, this report.
Not touched: src/**, pyproject.toml, PLAN.md, IMPLEMENTATION_A.md (Agent A's).

## What was delivered

- `tests/conftest.py` - CLI helpers, project/bundle factories (real
  GhostSlice manifest shape: per-file sha256 of the SLICED text),
  fake-ghostslice installers (working and failing executables), and a
  header documenting the exact core interface the suite pins down.
- `tests/test_snapshot.py` (8 tests) - source sha256/size/mtime recorded,
  Python symbols via ast, bundle manifest-bytes hash + generated_at +
  file list recorded, default ignore dirs + .gitignore-lite honoured,
  parser-lite symbols for JavaScript, binary file hash-only with
  symbol_method "none", custom -o path, project-only snapshot with no
  bundle, missing project is a clean exit 2 with no traceback.
- `tests/test_check_stale.py` (11 tests) - fresh on no change; PLAN bar:
  planted body edit to a bundled file is stale by file name; unbundled
  edit and added file are context only (fresh); removed bundled file
  stale, removed unbundled file fresh; bundle manifest replaced since
  snapshot is stale; --json-out/--md-out reports written and the JSON
  manifest hash reproduces from the manifest bytes; missing bundle,
  missing project, and corrupt manifest are clean exit 2s.
- `tests/test_touch_and_symbols.py` (5 tests) - PLAN bars: touch-only
  (mtime moved, bytes identical) stays fresh and lands in touched_only;
  renamed bundled symbol is stale with the old name in removed and the
  new name in added; deleted bundled symbol stale; added symbol in a
  bundled file is named; symbol added to an out-of-bundle file stays
  fresh and appears only as changed context.
- `tests/test_no_baseline.py` (5 tests) - PLAN bar: with no snapshot,
  an all-old bundle is verdict unknown (exit 2), baseline
  manifest_heuristic, never a confident fresh; bundled file missing on
  disk is stale via missing_bundle_file; source newer than
  generated_at is flagged with a heuristic reason but verdict stays
  unknown; a symbols_included symbol that no longer exists is a
  definite stale; with no generated_at the manifest file's own mtime
  is the reference and the verdict is still unknown.
- `tests/test_strict_and_pack.py` (3 tests) - --strict-added: a file
  added after a project-only baseline and then included in a bundle
  is fresh by default and stale under --strict-added; a Pack bundle
  checked via --bundle reports pack_stale mirroring stale (False when
  fresh, True when stale); a Pack/bundle dir with no manifest is a
  clean exit 2.
- `tests/test_reexport.py` (5 tests) - PLAN bar: stale + --reexport
  with GhostSlice absent (PATH stripped, module unimportable) exits 1
  with reexport status "unavailable" and a reason, no traceback, and
  the bundle bytes are unchanged; the human summary prints
  "reexport: unavailable"; a fake GhostSlice that exits 3 gives
  status "failed"; a fake working GhostSlice gives status "ok",
  refreshes the snapshot to the new manifest hash, and a follow-up
  plain check is fresh; --reexport on a fresh bundle attempts nothing
  (reexport is null).
- `tests/test_watch_loop.py` (4 tests) - bounded watch on a fresh
  project exits 0 with "stale seen: False"; bounded watch on a stale
  project exits 1 and prints the settled stale verdict; missing
  project is a clean exit 2; a live loop started fresh, edited
  mid-run, settles to a printed stale verdict, and SIGINT exits
  cleanly with code 1 and the session summary.
- `README.md` - full v0.1 README: the GhostWatch vs `ghostslice watch`
  distinction, hard rules, snapshot/check/watch usage, findings and
  exit-code tables, snapshot format as shipped, out-of-scope, honest
  notes.
- `examples/` - `fixture-project/` (two-file Python project),
  `fixture-bundle/` (GhostSlice-shaped bundle: app.py full, util.py
  signatures with symbols_included, manifest hashes verified as
  sliced-text hashes), `demo-pack/` (data-only Pack pointing at the
  fixture bundle), and a step-by-step walkthrough `examples/README.md`
  covering fresh, stale, touch, no-baseline unknown, graceful
  reexport-unavailable, and the polling loop. The walkthrough was
  smoke-run on a /tmp copy: snapshot 0, fresh 0, stale 1,
  reexport-unavailable 1, no-baseline JSON names manifest_heuristic.

## Results

Command: `PYTHONPATH=src python3 -m pytest tests -q` (run three times;
watch file run separately once more, stable)

**41 passed, 0 failed.**

All five PLAN.md verification bars are covered by named tests:
planted-change, symbol (rename/delete/out-of-bundle), touch,
missing-baseline, and missing-GhostSlice.

## Honest notes / quirks found (core behaviours, not test bugs)

1. **Successful --reexport still exits 1 for that run.** By design in
   cli.py: the report keeps the stale verdict the caller asked about
   and records `reexport: {status: ok, snapshot_refreshed: true}`;
   the *next* check is fresh. Reasonable, but callers scripting on
   exit code should know a successful re-export does not flip the
   current run to 0. The test asserts this behaviour explicitly.
2. **Watch output is block-buffered when stdout is a file/pipe.**
   The CLI prints without flush=True, so in a redirected live loop
   nothing is readable until the process exits (or the buffer fills).
   In a terminal it appears live. The live-loop test signals SIGINT
   and reads the flushed output on exit; a future core polish would
   be flush=True on the watch prints.
3. **Heuristic possibly-stale findings reuse the changed_in_bundle
   class.** PLAN.md names them `possibly_stale`; the core reports
   them under `changed_in_bundle` with "(heuristic, no snapshot
   baseline)" in the reason and keeps the verdict unknown unless a
   definite finding exists. The tests assert the reason text and the
   unknown verdict, so the safety property (never confident fresh,
   never false stale) holds either way.
4. **Removed unbundled files land in changed_not_in_bundle** (reason
   "deleted since snapshot") rather than a removed class; only
   bundled deletions use removed_from_project. Verdict behaviour is
   correct (fresh); only the label is asymmetric.

## Assumptions

None outstanding: Agent A's core (PLAN.md, src/ghostwatch/cli.py,
core.py) landed in parallel while these tests were written, and the
conftest header, README, and tests were all reconciled to the shipped
interface: `snapshot <project> [--bundle] [-o]`,
`check <project> [--bundle] [--snapshot] [--strict-added] [--reexport]
[--json] [--json-out] [--md-out]`,
`watch <project> [--bundle] [--interval] [--max-polls] [--reexport]
[--write-report] [--json-out] [--md-out]`; snapshot `files` as an
object keyed by relative path with sha256/size/mtime_ns/symbols/
symbol_method; report findings including the extra touched_only
class; exit codes 0/1/2 for fresh/stale/unknown.

## Gates honoured

Local only, no network, no push, no publish, no announcements, no
spend. Tests write only to pytest tmp dirs (plus one /tmp smoke copy
of examples/, removed in spirit: it lives only in /tmp). src/**,
pyproject.toml, and PLAN.md were only read or executed, never edited.
