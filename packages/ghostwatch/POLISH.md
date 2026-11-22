# GhostWatch v0.1 - Polish Round (Oct 14, 2026)

Sole-owner polish after Wave 3 parent verification (41 tests passing).
House loop: audit first, two improvement passes, demonstrate-then-fix,
a regression test per fix. No version bump, no push/publish/announce,
stdlib only, local only. Final suite: **51 passed** (41 original +
10 new), run in full at the end.

## Audit findings

All bugs below were demonstrated on the shipped v0.1 code before any
fix (throwaway fixtures in /tmp, since removed):

1. **Watch output block-buffered when redirected (REPORT_B quirk 2,
   required fix).** `watch` printed without `flush=True`. With stdout
   redirected to a file, a live watch showed **0 bytes while running**
   after 2s; the verdict only appeared at exit, and a SIGTERM lost
   the buffered output entirely.
2. **Corrupt snapshot crashed with a traceback.** `load_snapshot`
   validated only the top level. A snapshot whose per-file entry was
   a string (or whose `bundle` field was a string) passed validation
   and `check` died with `AttributeError: 'str' object has no
   attribute 'get'` (exit 1 + traceback) instead of a clean exit 2.
3. **.gitignore-lite broke git semantics for anchored and dir-only
   patterns.** Patterns were stripped of `/` on load, losing the
   anchor and dir-only information, and `fnmatch` let `*` cross
   directory boundaries. Demonstrated: `/notes.txt` also ignored
   `src/notes.txt`; `logs/` also ignored a *file* named `logs`;
   `docs/*.md` would also match `docs/sub/b.md`. Related minor: a
   top-level file named `build` was eaten by the default ignore-dir
   list.
4. **Check re-read and re-hashed every file, every time.** Recorded
   honestly in IMPLEMENTATION_A.md as a known limit. Baseline on a
   300-file tree: fresh check hashed 300 files (~0.3-1.2s per run).
5. **README inaccuracy (found by reading, not a demo).** The honest
   notes claimed "v0.1 uses mtime/size as a cheap pre-filter and
   only re-hashes files whose stat moved" - not true of the shipped
   code (finding 4). The Status section also still said "v0.1 in
   build... built in parallel", stale after verification.

## Pass 1 - correctness (flush, corrupt snapshots, gitignore)

- **cli.py:** `_print_summary` gained a `flush` parameter; `watch`
  passes `flush=True` for every verdict summary, and its header and
  stopped lines flush too. One-shot `check`/`snapshot` prints are
  unchanged (they exit immediately). Re-demonstration after the fix:
  164 bytes readable while the watch was still running.
- **core.py `_validate_snapshot`:** structural validation shared by
  `load_snapshot` and `check_project` - per-file entries must be
  objects, `symbols` must be a list when present, `sha256` a string
  when present, `bundle` an object or null. A corrupt snapshot is now
  a clean exit 2 naming the offending entry, no traceback.
- **core.py ignore rewrite:** patterns are parsed once into
  (body, anchored, dir_only). Leading `/` anchors to the root,
  trailing `/` is directory-only, any pattern containing `/` is
  root-anchored, and matching is segment-wise so `*` never crosses
  `/`. `**/` (collapsed to `*/`) also tries path suffixes, matching
  git's any-depth behaviour. Default ignore dirs now only match
  directory components, so a file named `build` survives.
- Regression tests: `tests/test_polish_pass1.py` (7 tests) - anchored
  pattern root-only, dir-only pattern spares the same-named file,
  mid-slash glob does not cross directories, default dirs spare a
  same-named file, two corrupt-snapshot clean-exit-2 tests, and a
  live watch test asserting header + verdict are readable from a
  redirected file *while the process is still running*.

## Pass 2 - performance pre-filter + README accuracy

- **core.py:** `snapshot_project` accepts `baseline_files`; `check`
  passes the baseline it is diffing anyway. A file whose size AND
  `mtime_ns` are unchanged reuses the baseline sha256/symbols
  without being read; any stat change forces the full read+hash, so
  touched-only detection (mtime moved, hash equal) is unchanged.
  The `snapshot` command never reuses: a baseline must always be
  authoritative. Snapshot and report gained a `files_reused`
  counter next to `files_hashed`; the Markdown report shows both.
- **Equivalence evidence:** (a) on the same 300-file bench tree with
  planted edits (bundled edit, unbundled edit, touch, add, delete),
  findings were identical to the recorded pre-fix output - verdict
  stale, changed_in_bundle 1, changed_not_in_bundle 2,
  touched_only 1, added_not_in_bundle 1 - while hashing only the 4
  changed files (296 reused); (b) fresh check: 0 hashed, 300 reused;
  (c) all 41 original tests, which pin verdicts/findings across the
  fixture corpus, pass through the new path; (d) dedicated tests in
  `tests/test_polish_pass2.py` (3 tests), including a size change
  with the original mtime restored byte-for-byte, which is caught
  because size is half the filter.
- **Honest perf note:** on 300 small files the wall-clock gain was
  within noise (interpreter startup and the tree walk dominate);
  what provably drops is bytes read + hashed (300 -> 0 on an
  unchanged check), which is where the cost scales on real trees.
  The residual trade-off is documented in the README: a content
  change preserving both size and `mtime_ns` exactly would be
  missed by the reuse path, the same trade-off git's index makes.
- **README:** Status updated to built + verified with a pointer
  here; the .gitignore description now states the anchored/dir-only
  semantics actually implemented; the polling-cost note rewritten
  to describe the pre-filter as shipped (it previously described it
  before it existed); snapshot example gained `files_reused`.

## Left alone, on purpose

- **Successful `--reexport` still exits 1 for that run**
  (REPORT_B quirk 1): by design - the run reports the stale verdict
  it was asked about; the next check is fresh. No evidence against.
- **Heuristic findings reuse `changed_in_bundle`** with the
  "(heuristic, no snapshot baseline)" reason (quirk 3): the verdict
  safety property (never confident fresh, never false stale) holds;
  renaming the class would churn the report format for no gain.
- **Removed unbundled files land in `changed_not_in_bundle`**
  (quirk 4): label asymmetry only, verdict correct; same reasoning.
- **Negations and full `**` semantics** remain lite, as labelled.
- IMPLEMENTATION_A.md's "pre-filter not yet implemented" line is a
  dated build record and was left as written; this file supersedes
  it on that point.

## Final verification

`PYTHONPATH=src python3 -m pytest tests -q` - **51 passed, 0
failed** (41 original + 7 pass 1 + 3 pass 2). Watch/reexport/polish
files re-run separately afterwards: 19 passed.
