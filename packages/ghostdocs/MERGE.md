# GhostDocs — MERGE of harden + polish + deepen (2026-10-18)

Merged tree built from a fresh copy of the pristine tree
(`~/workspace/ghostdocs/`, never edited), lanes applied in order
harden, then polish, then deepen. No `IMPROVE.md` is present in this
tree. Nothing was pushed to GitHub.

## Final test counts (all run: `PYTHONPATH=src python3 -m pytest -q`)

| Tree | Result |
|---|---|
| pristine (baseline) | 15 passed |
| harden | 43 passed |
| polish | 15 passed |
| deepen | 23 passed |
| **merged** | **51 passed** |

51 = 15 baseline + 28 harden (`test_hardening.py`) + 8 deepen
(`test_html_sections.py`). Merged passes everything every lane passed,
with zero new failures versus any lane.

## Files by source lane

### Polish only (copied verbatim from polish)
- `README.md`
- `examples/WALKTHROUGH.md`
- `src/ghostdocs/__init__.py`
- `src/ghostdocs/__main__.py`
- `src/ghostdocs/selection.py`
- `src/ghostdocs/sensitive.py`
- `src/ghostdocs/tokens.py`

### New test files (no conflicts, both kept)
- `tests/test_hardening.py` — from harden (28 tests)
- `tests/test_html_sections.py` — from deepen (8 tests)

### Hand / three-way merged (harden logic + polish docstrings/help)
Verified by diffing the merged file against each lane: against harden
it differs only by polish additions, and against polish only by harden
additions.

- `src/ghostdocs/cli.py` — harden: corrupt/malformed manifest and chunk
  handling in `check`, unlisted-file detection, `--top`/`--fit` negative
  rejection. Polish: expanded module/command docstrings, descriptive
  parser help, examples epilog, per-argument help/metavars. Different
  regions (harden is inside `cmd_check`/`main` tail; polish is
  docstrings and parser construction), merged cleanly.
- `src/ghostdocs/export.py` — harden: stale-artifact cleanup on
  re-export (previous-manifest tracking, traversal-guarded deletion,
  stale `PROMPT.md`/`chunks.jsonl` removal). Polish: docstrings for
  `ExportResult`, `choose_docs`, `export_corpus`. Clean merge.
- `src/ghostdocs/profile.py` — harden: `is_authoritative` path-boundary
  fix, `modes`-must-be-object and list-of-strings validation in
  `load_profile`. Polish: docstrings for `Profile` and its methods and
  for `load_profile`. Clean merge; polish's `is_authoritative` docstring
  remains accurate for the hardened body.
- `src/ghostdocs/report.py` — harden: `write_report` creates missing
  parent directories. Polish: docstrings for `render_report` and
  `write_report`. Clean merge.
- `src/ghostdocs/scan.py` — harden: in-corpus skip-dir judgement,
  unreadable files named not-covered, unknown formats named
  not-covered. Polish: docstrings for `Doc`, `NotCovered`, `Cluster`,
  `Corpus`, `scan_corpus`. Clean merge.
- `src/ghostdocs/sections.py` — see Conflict 1 below.
- `src/ghostdocs/extract.py` — see Conflict 2 below (the heading fix).

### Unchanged from pristine
`IMPLEMENTATION_A.md`, `PLAN.md`, `REPORT_B.md`, `LICENSE`,
`pyproject.toml`, all fixtures and pre-existing tests, and
`examples/sample-help-centre/*` (no lane changed them).

## Conflicts and how they were resolved

### Conflict 1 — `sections.py`: `find_date` docstring (harden vs polish)
The only textual three-way conflict outside `extract.py`. Both lanes
rewrote the same docstring: harden's describes the new behaviour
(first date in document order across both formats, real-calendar-date
validation); polish's describes the old behaviour ("only the first
match is used"), which would be misleading after the harden fix.
Resolution: kept harden's function body and docstring verbatim, and
appended polish's still-accurate closing note ("Returns `None` when
the text carries no such date; callers then fall back to the file
modification date"). Polish's other `sections.py` docstrings
(`Section`, `Path_title`, `first_paragraph`) were in untouched regions
and were kept in full. No harden logic was dropped.

### Conflict 2 — `extract.py`: the HTML heading bug (harden vs deepen) — reconciled to ONE fix
Both lanes fixed the same bug in `_HTMLText` (the `#` markers were
emitted at the end tag, after the heading text, so no HTML document
ever split into sections), in the same code region, differently:

- Harden: buffers heading text, `_flush_heading()` emits
  `"\n# Title\n"`; heading start flushes a previous heading; end tag
  flushes only when it matches the current level; EOF handled by
  `parser.close()` in `extract_html` plus an explicit
  `parser._flush_heading()` call after the try block.
- Deepen: same buffering/`_flush_heading()` core, plus a superset of
  handling — `_HEADING_TAGS`, `<head>`/`<title>` skipped as metadata
  (so a title cannot form a fake preamble section), a block element
  implicitly closes an unclosed heading, inline markup inside a
  heading adds no breaks, any heading end tag flushes, and EOF is
  flushed by a `close()` override on the parser itself.

Resolution: **deepen's `_HTMLText` was taken as the single heading
fix** (verified byte-identical to deepen's class in the merged file),
because it is the more complete/correct version and its 8 dedicated
tests cover cases harden's version does not (head/title metadata,
unclosed headings, inline markup/entities). Harden's redundant
post-`close()` `_flush_heading()` call in `extract_html` was removed
so there is exactly one EOF-flush mechanism (deepen's `close()`
override) — the two fixes were not stacked. The one harden-only text
lost is a two-line comment inside `_flush_heading` whose explanation
is covered by deepen's class docstring; no harden behaviour was lost:
harden's HTML heading test passes against deepen's implementation
(full suite green, see counts).

All of harden's *other* `extract.py` fixes were kept in full and are
unaffected by the heading choice: UTF-16-only-with-BOM decoding and
UTF-8 BOM stripping in `_decode_text_bytes`, PDF hex-string and
UTF-16BE string extraction (`_decode_pdf_string`), and single-EOL
stripping before `endstream` in `_pdf_streams`. Polish's `extract.py`
docstrings (`Extraction`, `extract_html`, `extract_pdf`,
`extract_file`) were also kept.

## Anything suspicious
- Nothing suspicious found. No lane changed a file the others' reports
  did not claim (verified with `diff -rq` against pristine for every
  lane before merging). No duplicate logic remains in merged files;
  a scan for conflict markers in the merged tree is clean.
- Note (inherited, not a merge issue): harden intentionally narrows
  `is_authoritative` prefix matching to a path boundary and names
  unknown-format files as not-covered — both are documented behaviour
  changes in harden's `IMPROVE.md` and are preserved here.
