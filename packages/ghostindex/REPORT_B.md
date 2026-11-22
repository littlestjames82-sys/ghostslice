# GhostIndex v0.1 - Agent B report (tests, README, examples)

Ownership respected: everything below lives in `tests/**`, `README.md`,
`examples/**`, and this file. Nothing under `src/**`, `pyproject.toml`,
or `PLAN.md` was edited.

## Final result against the real core

Command: `python3 -m pytest tests -q` from the repo root (the suite
discovers the CLI as `python -m ghostindex` with `PYTHONPATH=src`;
`GHOSTINDEX_CMD` and a PATH install are also supported).

**44 passed, 1 failed, 0 skipped** - identical across two consecutive
full runs (45 tests total: 10 fixture, 11 build/search, 7 hard-rule,
5 excerpt, 4 incremental, 8 docs/examples).

The one failure is a genuine core defect, kept strict on purpose.
See Defect D1.

## What was built

- `tests/conftest.py` - session CLI fixture (skips CLI tests cleanly
  when no CLI is discoverable), per-test tmp copies of the fixture
  projects so edits never dirty the repo fixtures, `indexed` fixture
  (index both projects, assert the `--db` file exists).
- `tests/helpers.py` - black-box CLI driver. Discovery order:
  `GHOSTINDEX_CMD`, `ghostindex` on PATH, `python -m ghostindex`
  (src layout, then flat). Where the PLAN left the placement of
  `--db` open, the helper probes suffix form, prefix form, then the
  `GHOSTINDEX_DB` env var, and caches the accepted form; the real core
  takes the suffix form (`ghostindex index <roots> --db <path>`).
  Result normalisation accepts the core's `--json` hit shape
  (`root`, `rel`, `windows[]` with `start_line`/`end_line`/`text`,
  `excerpt_tokens_est`, `file_tokens_est`) plus reasonable alternates,
  and an update-count parser that sums the per-root count lines a
  multi-root report prints.
- `tests/fixtures/` - `project_alpha` (auth module with a shared term,
  a 60-line reference file with a unique middle term, a 10,053-char
  single-line file, a `.gitignore`d file and a `*.log` file with
  planted terms, a binary `payload.zip` with a planted term, a
  `node_modules` file with a planted term), `project_beta` (payments
  module sharing the term, beta-only term, guide with a unique word),
  and `outside_project` (never named as a root).
- `tests/test_fixtures.py` - the planted terms and ignore coverage
  really hold in the fixture files (runs with no core).
- `tests/test_build_search.py` - index creates a real sqlite FTS5
  database (schema inspected via stdlib sqlite3); unique term returns
  only the owning project; shared term spans both; exit codes 0/1/2
  exactly as the PLAN specifies (no-match = 1, search with no index
  = 2, no traceback); `--root` filter; `--limit 1` returns exactly one
  hit; default AND search misses a two-term query no single file
  holds while `--any` hits it; `list` and `stats` name both roots and
  the db path; `doctor` reports sqlite + FTS5; `remove` drops only
  that root and deletes no project files.
- `tests/test_hard_rules.py` - the pinned hard rules: terms planted
  only in a `.gitignore`d file, a `*.log` file, `node_modules`, and a
  binary file are each unsearchable (exit 1); a project outside the
  named roots is unsearchable; `index` + `search` + `update` leave
  every root file byte-identical (sha256 snapshots) and the db lives
  only at the `--db` path; a file created after indexing is NOT found,
  proving search answers come from the index, not a live rescan.
- `tests/test_excerpts.py` - excerpt lines (markers and line-number
  gutters stripped) appear verbatim in the source files; excerpts
  include neighbouring context lines, not just the match; the
  middle-term excerpt is under half the file's length and its token
  estimate is below the whole-file estimate; `--max-tokens 5` bites;
  and the long-line bound test (D1, failing).
- `tests/test_incremental.py` - no-change update reports added 0,
  changed 0, removed 0; no-roots update covers indexed roots; the
  PLAN verification bar end to end: edit one file (unique term
  replaced), delete one file, add one file, and `update` reports
  exactly 1 added, 1 changed, 1 removed, after which the new term
  hits, the old term misses (exit 1), the deleted file's unique word
  misses, and the added file hits; a ranking fixture where a file
  about the term beats a file mentioning it once in passing.
- `tests/test_docs_examples.py` - README states the job, sqlite/FTS5,
  offline, commands, exit-code meaning, and limits; README contains
  no em dash character; examples hold both projects, the gitignore
  coverage, and a consistent captured session.
- `README.md` - plain words: the job, quick start, command table,
  search options and exit codes, what is and is not indexed, result
  shape, honest limits (keyword-only, bm25 knows no code structure,
  gitignore subset, the D1 long-line limit stated plainly, FTS5
  stores a text copy, no watching, no network).
- `examples/` - `project_alpha` and `project_beta` tiny projects
  sharing the phrase "sunflower festival" (alpha also has a
  `.gitignore`d scratch file with a planted term), `README.md`, and
  `sample_search_session.md`, which was generated by running the real
  CLI (index, cross-project search, the ignored term returning no
  matches with exit 1, stats), so every number in it is real output.

## Defect found (not fixed here; core is Agent A's)

**D1 - A single very long line defeats the per-hit excerpt cap.**
PLAN (MVP item 3): excerpts are "capped per hit and in total by
estimated tokens"; the core sets the per-hit cap at 200 tokens
(`src/ghostindex/search.py`: `DEFAULT_PER_HIT_TOKENS = 200`).
Reproduction: the fixture `tests/fixtures/project_alpha/src/longline.py`
has one 10,053-char line containing the term `needlelongline`.
`ghostindex search needlelongline --json` returns a hit whose single
window is 10,073 chars with `excerpt_tokens_est` 2168, equal to
`file_tokens_est` 2168: the "excerpt" is the whole file content.
Root cause, in `src/ghostindex/search.py::_build_hit` (lines 145-157):
when one window exceeds the cap, trimming is line-granular; it keeps
appending whole lines until the running estimate crosses the cap and
a match line is included. For a one-line window it appends that line
(about 2,168 estimated tokens) and stops, so no within-line
truncation ever happens and the cap is unenforceable for long lines
(minified bundles, generated one-liners). The multi-window and
whole-file cases are correctly capped; only the single-long-line
case escapes. Pinned by
`tests/test_excerpts.py::test_excerpt_from_a_very_long_line_is_bounded`,
which asserts the excerpt is at most 4,000 chars and shorter than the
source line; it fails with an excerpt of 10,073 chars. The limit is
also stated in the README's honest-limits section. Suggested fix
direction for the core owner: truncate an over-long single line
around the match position once the line alone exceeds the cap.

## Test-side bugs found and fixed during alignment (full disclosure)

The first run against the landed core was 28 passed, 9 failed. Eight
of the nine were my own harness bugs, fixed in `tests/**` only:

1. The update-count parser took the first per-root line of a
   multi-root report; the PLAN's exact counts are the sums across
   roots. Parser now sums, with word-boundary patterns so
   "unchanged" is not counted as "changed".
2. The ignored-term tests also asserted the term never appears in
   stdout; the CLI's "no matches for '<term>'" line echoes the query
   itself. The exit-code assertion (the real contract) is kept; the
   stdout assertion was removed with a comment saying why.
3. The excerpt adapter did not understand the core's windowed JSON
   shape (`windows[]`, `*_tokens_est` field names). The adapter now
   builds the excerpt from the windows and reads those fields. Six
   excerpt/hard-rule failures traced to these three causes.

The ninth failure is D1 above, which survived every adapter fix
because it is in the core.

## Assumptions recorded

- Search JSON is the agent-facing shape the PLAN promises; where a
  reasonable core might name hit fields differently, the adapter
  normalises rather than failing, and strictness lives in the
  behavioural assertions (paths, exit codes, counts, verbatim text).
- `--max-tokens` is asserted loosely (output must shrink materially,
  not to an exact figure) because the PLAN caps by estimated tokens
  and one minimum excerpt is a legitimate floor.
- No test touches the network, a real home directory, or the default
  state-dir database: every run passes an explicit `--db` inside a
  pytest tmp dir.

Gates held: stdlib only (pytest plus stdlib in tests), local only,
no network, no GitHub push, no PyPI/publish, no announcements,
no spend.
