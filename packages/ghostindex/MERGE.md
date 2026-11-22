# GhostIndex merge of harden + polish + deepen lanes (2026-10-18)

Merged tree built from a fresh copy of the pristine tree
(`~/workspace/ghostindex/`, untouched), with lane changes applied in
the order harden, then polish, then deepen. Three-way merges
(`git merge-file`, pristine as base) were used per file; every
conflict was resolved by hand and verified by diffing the result
against each lane version (any line present in a lane version but
missing from the merge is accounted for below).

## Test counts

| Tree | Result |
|---|---|
| Pristine baseline (per all three IMPROVE.md files) | 56 passed |
| harden lane (per its IMPROVE.md) | 81 passed (56 + 25 new) |
| polish lane (per its IMPROVE.md) | 56 passed |
| deepen lane (per its IMPROVE.md) | 66 passed (56 + 10 new) |
| **merged (measured here, `python3 -m pytest -q`)** | **91 passed, 0 failed** (56 + 25 + 10) |

Merged passes everything the best lane passed, plus the deepen
lane's tests, with zero new failures versus every lane. The merged
parser was also checked programmatically against pristine: every
subcommand, action, nargs, and default is identical (only the
argparse `type=` callables differ, which is the harden fix itself).

## Files taken from a single lane (copied verbatim)

- `src/ghostindex/tokens.py` — polish (docstrings only)
- `src/ghostindex/__main__.py` — polish (module docstring)
- `examples/README.md` — polish
- `examples/sample_search_session.md` — polish
- `tests/test_harden.py` — harden (new, 25 tests)
- `tests/test_query_syntax.py` — deepen (new, 10 tests)

## Files merged from multiple lanes

- `src/ghostindex/indexer.py` — harden + polish, clean 3-way merge,
  disjoint regions: harden's `max_bytes < 0` ValueError and
  read-bytes size-cap re-check; polish's `UpdateReport` / `as_dict` /
  `known_roots` docstrings.
- `src/ghostindex/scanner.py` — harden + polish, clean 3-way merge,
  disjoint regions: harden's segment-aware `_glob_to_regex` rewrite
  and `_symlink_target_excluded` symlink hard-rule fix; polish's
  `language_for` / `load_dir` / `ignored` docstrings.
- `src/ghostindex/store.py` — harden + polish, clean 3-way merge:
  harden's corrupt-db probe and StoreError wrapping in `open_store`;
  polish's `StoreError` / `default_db_path` / `fts5_available`
  docstrings and expanded `open_store` docstring (polish's removal of
  the bare `pass` in `StoreError` kept, semantically identical).
- `src/ghostindex/search.py` — all three lanes. One harden/polish
  conflict and one polish/deepen conflict, both resolved by hand
  (below). Result carries: deepen's module-docstring syntax section,
  `parse_query` / `ParsedTerm` / `build_exclusion_query`, phrase and
  exclusion handling in `build_match_query`, `_term_predicates`,
  `_anchor_for`, and both search SQL queries; harden's limit
  validation at the top of `search()`; polish's docstrings for
  `Window`, `Hit`, `capped`, `summary_dict`, `_words`,
  `_match_lines`, `_windows_for`, and `search()`.
- `src/ghostindex/cli.py` — all three lanes. Three harden/polish
  conflicts in `build_parser`, resolved by hand (below); the rest
  merged cleanly, including harden's `_positive_int` /
  `_non_negative_int` helpers, doctor `sqlite3.Error` catch, and
  `main()` error safety net, alongside polish's docstrings, help
  rewrite, `RawDescriptionHelpFormatter` epilogs, and `json_arg`
  helper. Deepen's only cli change (search `query` help) was folded
  into the hand-resolved help text.
- `README.md` — polish + deepen, clean 3-way merge: polish's full
  README (quick-start notes, Typical workflow, Search tips,
  Troubleshooting) with deepen's query-syntax paragraph inserted
  after the search-options material (it landed after polish's
  `index`/`update` clarification paragraph, still directly before
  "Caps are never silent").

## Conflicts and how they were resolved

1. `search.py`, `search()` head (harden vs polish): harden put its
   limit-validation block where polish put the function docstring.
   Resolved by keeping both: polish docstring first, then harden's
   validation block, then the original body (with deepen's exclusion
   logic further down). No harden fix dropped.
2. `search.py`, `_term_predicates` docstring (polish vs deepen):
   both lanes rewrote the same docstring for the function deepen
   rewrote. Resolved with a combined docstring: deepen's
   positive-units/exclusions wording plus polish's per-kind matching
   detail (plain = substring, prefix = word-start) and a phrase
   clause. The only lane lines not carried verbatim anywhere are the
   two superseded docstring originals; their content survives in the
   combined text.
3. `cli.py`, `index --max-bytes` (harden vs polish): same argument
   edited by both. Resolved: harden's `type=_non_negative_int` with
   polish's help text, `json_arg(p)`, and the `roots` help.
4. `cli.py`, `update --max-bytes`: same resolution as (3).
5. `cli.py`, search `query` / `--limit` / `--context` (all three
   lanes): harden changed the `type=` of `--limit` and `--context`,
   polish rewrote all three help strings, deepen rewrote the `query`
   help to document phrase/prefix/exclusion syntax. Resolved:
   harden's types, polish's help for `--limit` / `--context`, and a
   hand-combined `query` help that keeps polish's "quoted as one
   string, e.g. ..." framing and adds deepen's AND-default, phrase,
   prefix, and exclusion syntax. Verified in live `--help` output.
   (`--max-tokens` needed no hand work: the lanes edited different
   lines of the same call and the 3-way merge combined harden's
   `type=_positive_int` with polish's help automatically.)

Lines present in a lane version but absent from the merged tree,
other than the docstrings in (2): only pristine lines that a lane
intentionally replaced (e.g. the pre-deepen `build_match_query` body
that harden's copy still carried, and pre-polish README lines that
deepen's copy still carried). Every harden code fix is present and
pinned by its tests.

## Anything suspicious

- Nothing unresolved. No conflict required dropping a harden fix.
- One judgement call, noted in (5): the merged `query` help is a new
  sentence combining polish and deepen wording, so it matches
  neither lane verbatim; it documents the same flags and syntax with
  no behaviour change.
- No IMPROVE.md files are present in the merged tree (checked).
  Pristine tree was never edited; nothing was pushed to GitHub.
