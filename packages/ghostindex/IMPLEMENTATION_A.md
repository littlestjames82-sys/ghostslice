# GhostIndex v0.1 - Implementation Notes (Agent A, core)

Built Oct 14, 2026 from `PLAN.md`. Python stdlib only, no network,
no PyPI, no GitHub push, no announcements, no spend.

## What was built (Agent A ownership: PLAN.md, src/**, pyproject.toml, this file)

```
PLAN.md                         full plan in GhostSlice format (written first)
pyproject.toml                  ghostindex 0.1.0, zero dependencies, console script
src/ghostindex/__init__.py      version 0.1.0
src/ghostindex/__main__.py      python -m ghostindex
src/ghostindex/tokens.py        Slice estimator delegation + documented fallback
src/ghostindex/scanner.py       walk, ignore dirs/binary exts mirrored from Slice,
                                .gitignore matcher, .ghostslice.json ignore list
src/ghostindex/store.py         sqlite schema (projects / files / FTS5 docs),
                                default db path, FTS5 probe
src/ghostindex/indexer.py       build + hash-based incremental update, remove_root
src/ghostindex/search.py        FTS5 MATCH builder, bm25 ranking, excerpt windows
src/ghostindex/cli.py           index / update / search / list / stats / remove / doctor
```

Tests, README, and examples are Agent B's surface and were not touched.

## Design decisions

- **Index location.** One sqlite db for all roots, default
  `~/.local/state/ghostindex/index.db` (honours `XDG_STATE_HOME`),
  overridable per-invocation with `--db` or persistently with
  `GHOSTINDEX_DB`. Indexing and searching never write into a project
  root; if a `--db` path happens to live inside an indexed root, the
  walk skips that exact file so the index never indexes itself.
- **Schema.** `files` holds metadata (root, rel, sha256, size, mtime,
  language, line count, estimated tokens). `docs` is a standalone
  FTS5 table whose rowid IS the files id; columns are `rel` (indexed,
  so filename terms hit), `body` (indexed), `root` (UNINDEXED, scopes
  results). Tokenizer is unicode61. FTS5 availability is probed at
  open time; a Python build without FTS5 gets a hard error, never a
  silent degraded mode.
- **Incremental update is the only code path.** `index` and `update`
  both call the same routine: re-walk, compare size + mtime as a fast
  path, then sha256; only hash-changed files are re-read and their
  FTS rows rewritten. Vanished, newly ignored, newly binary, or
  over-cap files are deleted from both tables. Counts (added /
  changed / removed / unchanged / skipped, with ignore-rule detail)
  are printed on every run so a no-op update is provable.
- **Scanner parity with Slice.** Ignore dirs, binary extensions, and
  the extension-to-language map are mirrored from
  `ghostslice/scanner.py` v1.0.6. Content-level binary defence is a
  NUL sniff on the first 8 KiB at read time (catches extensionless
  binaries and unknown binary extensions like `.dat`). Non-UTF-8 text
  is decoded with replacement characters rather than dropped, and
  that is counted in code, not hidden. Directory symlinks are never
  followed; file symlinks resolving outside the root are skipped.
- **.gitignore subset.** Per-directory `.gitignore` files apply to
  their subtree, last match wins, `!` negation, trailing-slash dir
  patterns, leading-slash anchoring, `*` / `?` / `**` globs. This is
  a pragmatic subset of git's wildmatch, as the PLAN's Risks section
  states; the common cases are pinned by the smoke fixtures below.
- **Estimator delegation.** `tokens.py` prefers GhostSlice's
  calibrated estimator (import, `GHOSTINDEX_GHOSTSLICE_SRC` /
  `GHOSTSLICE_SRC`, or a sibling `ghostslice/src` checkout) so index
  numbers agree with Slice's own. Fallback is Slice's raw v1 split at
  factor 1.0 with a method string that says "uncalibrated". The
  method in force is stored per project and printed by list/stats.
- **Excerpts, not files.** Search builds a safe FTS5 MATCH string
  (every term quoted; a trailing `*` makes a prefix term; terms ANDed
  by default, `--any` ORs them). Hits are bm25-ranked. For each hit,
  match lines are found by substring scan of the stored body, windows
  of +/- context lines (default 3) are merged, and the result is
  capped per hit (default 200 estimated tokens, with a single
  oversized first window trimmed line by line) and across the result
  set (`--max-tokens`, default 2000; hits are dropped whole once the
  budget is spent, after at least one hit). Files matched only by
  name return a bounded head excerpt labelled "name match".
- **Exit codes.** search: 0 matches, 1 no matches (including a root
  filter that legitimately contains none), 2 could not run (no db,
  `--root` not indexed, empty query). remove: 1 when the root is not
  indexed. index/update: 2 on a non-directory root. doctor: 2 only
  when FTS5 is missing or the db is unreadable.

## Smoke + verification results (all run Oct 14, 2026, this machine)

Fixture: two hand-built projects in /tmp (9 files), with traps:
a unique term (`quorvex`) planted in a normal file, in `node_modules`,
in a `.gitignore`d file, and in a NUL-bearing `.dat` binary.

- `ghostindex index projA projB`: projA added 3; projB added 3,
  skipped 1 binary-content (the .dat, caught by NUL sniff), ignored
  dirs 1 (node_modules), ignored files 1 (the .gitignore'd file).
  Estimator resolved to GhostSlice's calibrated v2 method.
- `search quorvex`: exactly 1 hit, projB `src/zanzibar.py`; excerpt
  ~170 estimated tokens vs ~2,790 whole-file. No trap file appears.
- Ranking: `search tessellate --json` on projA ranked
  `docs/tessellation.md` (bm25 -1.2774, the file about the term)
  above `src/main.py` (-0.9657, one passing mention).
- Root filter: `search quorvex --root projA` -> no matches, exit 1.
  No-match search exits 1; search with no db exits 2; indexing a
  non-directory exits 2.
- Incremental: after renaming the term in zanzibar.py, deleting
  projA's guide, and adding one projA file, `update` reported
  projA added 1 / removed 1 / unchanged 2 and projB changed 1 /
  unchanged 2, exactly the planted deltas. The old term then found
  nothing (exit 1) and the new term hit zanzibar.py. A second
  `update` reported everything unchanged on both roots.
- Name and prefix: `search zanzibar` returned the file as a labelled
  name-only match; `search 'brandnew*'` prefix-matched.
- `.ghostslice.json` ignores: a third fixture root whose profile
  ignores `skipme.py` indexed 2 files with 1 profile-ignored, and
  search returned only `keepme.py`.
- Housekeeping: list/stats/doctor/remove all run; removing a root
  twice exits 1 the second time. Default db path resolves to
  `~/.local/state/ghostindex/index.db`.
- Non-destructive: sha256 of every fixture file taken before and
  after `search` + `update` runs is identical; the db existed only
  at the `--db` path.
- Fallback estimator: with the package copied outside the workspace
  and HOME redirected so no GhostSlice is reachable, indexing works
  and prints the fallback (uncalibrated) method string.
- Real-repo smoke: `ghostindex index ~/workspace/ghostslice` indexed
  143 files, ~569,561 estimated tokens, in about 2.8 s; db size
  2,871,296 bytes. `search FAMILY_CALIBRATION` put
  `src/ghostslice/calibration.py` first and the defining file
  `src/ghostslice/tokens.py` second (top hits, as the PLAN bar
  requires); `search estimate_tokens` included tokens.py in the
  top 5.
- Install: fresh venv `pip install .` (normal build isolation)
  succeeds; the installed `ghostindex` console script reports 0.1.0
  and searches an existing index correctly. `pip install
  --no-build-isolation` fails in a bare Python 3.12 venv (no bundled
  setuptools); that is a venv property, not a package dependency:
  the package declares `dependencies = []`.
- Stdlib audit: imports across src are argparse, dataclasses,
  datetime, fnmatch, hashlib, json, math, os, pathlib, re, sqlite3,
  sys. No urllib / http.client / requests / socket anywhere in src.

## Known limits (honest)

- The update fast path trusts size + mtime: a same-size edit that
  lands without changing the stored mtime (coarse filesystem clocks,
  or a tool that resets mtimes) can be missed until the file's mtime
  moves. The hash check runs whenever size or mtime differs. This is
  the same tradeoff git's stat cache makes.
- Match lines for excerpts are found by substring scan, while FTS5
  matches on unicode61 tokenization. For punctuation-heavy terms the
  two can disagree; when no body line reproduces the match, the hit
  falls back to a head excerpt and is labelled a name match, so the
  excerpt shown may not contain the literal term in that rare case.
- bm25 is text relevance only. It knows nothing about code structure,
  so a heavily commented mention can outrank a terse definition (seen
  in the real-repo smoke: calibration.py above tokens.py for
  FAMILY_CALIBRATION). Excerpts show the match lines so the reader
  can judge.
- Lockfiles (package-lock.json and friends) are indexed: they are
  text and Slice's scanner includes them too. They can add search
  noise on dependency-heavy repos. Skipping them by default is a
  v0.2 candidate, not a silent v0.1 behaviour.
- FTS5 stores a full copy of every indexed file's text (the
  GhostSlice repo's 143 files produced a ~2.9 MB db). `remove` is
  the supported way to reclaim space; sqlite does not shrink the
  file until a VACUUM, and v0.1 does not vacuum automatically.
- Notebooks (.ipynb) are indexed as their raw JSON text. Non-ASCII
  case folding may differ between FTS5 and the substring scan.
- Scale beyond the GhostSlice repo (hundreds of files, ~570K tokens)
  is untested in this build round; no monorepo stress test was run.

## Polish round addendum (Oct 14, 2026)

Two statements above are superseded by the polish round; see
POLISH_REPORT.md for the full record.

- The FTS5/VACUUM limit bullet no longer holds as written. `remove`
  now runs FTS optimize + VACUUM after deleting a root's rows, a
  standalone `ghostindex vacuum` command reclaims space freed by
  updates, and `stats` reports `reclaimable_bytes` (the sqlite
  freelist) so the held space is visible before reclaiming it.
  Measured on a 217,088-byte fixture index: removing every file used
  to leave the file at 217,088 bytes; it now compacts to 53,248.
- The excerpt description ("a single oversized first window trimmed
  line by line") predates the D1 fix: over-long single lines are now
  truncated within the line around the match (see FIX_REPORT.md), so
  the per-hit cap holds for minified and generated one-liners too.
- `doctor` now prints the database size in bytes (text and
  `db_bytes` in --json), which PLAN.md's risk section and the README
  always said it did but the first build did not.
