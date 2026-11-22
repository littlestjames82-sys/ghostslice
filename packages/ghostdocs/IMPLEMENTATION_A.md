# GhostDocs v0.1 - Agent A (core) implementation notes

Built Oct 14, 2026 from PLAN.md. Python stdlib only, no network, no LLM,
no OCR, extractive only. Agent A owned: `src/**`, `pyproject.toml`, this file.
Tests / README / examples belong to Agent B and were not touched.

## What shipped

Package `src/ghostdocs/` (Python >= 3.10, zero dependencies):

- `extract.py` - text extraction for Markdown, plain text, HTML
  (script/style stripped, headings preserved as Markdown levels) and PDF
  (text layer only). Per-document quality data: format, chars, PDF page
  count, chars/page, flags (`low-yield`, `no-text-layer`,
  `near-empty-text-layer`, `page-count-unknown`, `lossy-decode`).
- `sections.py` - section model. Chunk boundaries are heading sections,
  never arbitrary splits. Date detection (ISO and "Month D, YYYY"),
  headings-mode rendering (trail + first paragraph).
- `scan.py` - corpus scan: per-document/section token heat, exact duplicate
  clusters (sha256), near-duplicate clusters (line-shingle Jaccard >= 0.85,
  GhostSlice method, OR word-count cosine >= 0.90, added because a few edited
  lines in a short document break most line shingles - caught in smoke
  testing), probable-current member (authoritative source wins, else newest
  date, labelled heuristic), stale flags, wasted-token totals.
- `profile.py` - `.ghostdocs.json`: include/exclude globs,
  `authoritative_sources`, per-source modes, `superseded` retention
  (default `exclude` from exports, kept in reports). Unknown keys and bad
  modes fail loudly.
- `sensitive.py` - sensitive-shape guard (SSN, Luhn-checked credit card,
  api-key shapes, password assignments hold a document out; email/phone are
  reported but do not hold). Findings are path + line + type only, never
  values. Held-out documents are excluded from exports by default
  (`--allow-sensitive` is an explicit, recorded opt-in).
- `selection.py` - TF-IDF section selection for `--task`, same method family
  as `ghostslice task`. No embeddings.
- `export.py` - two export shapes: agent bundle (`PROMPT.md` + `files/` +
  `manifest.json`) and JSONL chunk pack (`chunks.jsonl`, one chunk per
  section with source path, heading trail, date, sha256, token estimate).
  Section-based token accounting so file, bundle and chunk totals agree
  exactly. Deduped by default (only the probable-current cluster member is
  exported). `--fit N`: downgrades non-authoritative docs to headings mode,
  then drops lowest-priority sections; an unfittable target still writes the
  bundle, marks `fitted: false` and exits 1 (an empty bundle is not a fit).
- `report.py` - single-file offline HTML report, plain words first
  (technical appendix second): heat, duplicate clusters with waste, stale
  list, held-out list (path + type only), not-covered list, deduped saving.
- `cli.py` - `ghostdocs scan [--json]`, `ghostdocs export -o DIR
  [--task T] [--fit N] [--shape bundle|chunks|both] [--allow-sensitive]`,
  `ghostdocs report -o FILE`, `ghostdocs check BUNDLE` (hash + total
  validation against the manifest).

Coverage honesty (hard rules, implemented and tested):
- DOCX, legacy DOC, ODT, spreadsheets, slides, RTF: listed as NOT COVERED
  with a reason in scan, report, export manifest and CLI output. Never
  silently skipped.
- Image-only / no-text-layer PDFs: NOT COVERED with reason
  "no extractable text layer", never in any bundle.
- Unrecognised extensions are ignored as non-documents, known document
  formats are never ignored.

## PDF extraction: honest limits of the stdlib approach

The fixture PDF (FlateDecode stream, `(text) Tj` operators) extracted
correctly. Real-world limits, recorded as required by the plan instead of
adding a dependency:

- Only literal `( ... )` string operands of Tj/TJ in raw or FlateDecode
  content streams are read. Hex strings, Type0/CID fonts, ToUnicode maps,
  and encoded glyph runs yield little or no text.
- Multi-column and table layouts come out in stream order, not reading
  order.
- Such PDFs surface via the chars/page quality flags (`low-yield`,
  `near-empty-text-layer`) or land on the not-covered list; they do not
  silently produce garbage bundles. A genuine corpus needing more than this
  needs Ryan's call on a non-stdlib extractor (format-scope cut for v0.1
  per PLAN risks section).

## Smoke test (run Oct 14, 2026, fixtures in /tmp/gd-corpus)

Fixtures: edited near-duplicate policies (2024 vs 2025), an exact copy,
onboarding TXT, HTML help page, MD note with a planted SSN, a DOCX file,
a text-layer PDF built with zlib/Flate, an image-only PDF, and a
`.ghostdocs.json` profile.

- `ghostdocs scan` - PASS: 7 documents, 348 estimated tokens raw, 1 cluster
  (near, current `policy-new.md` by newest-date heuristic, stale
  `policy-old.md`, waste 183, deduped 165), 1 held out, 2 not covered
  (DOCX + image-only PDF, both named with reasons). HTML extracted with
  script/style removed; PDF extracted (13 tokens).
- `ghostdocs export` - PASS: 6 sections, 146 estimated tokens, held-out SSN
  document excluded, superseded copies skipped, not-covered named. Planted
  SSN string verified ABSENT from every output file.
- `ghostdocs check` - PASS: hashes and totals match manifest. Chunk sum
  (146) equals manifest chunk total equals exported total.
- Reproduction - PASS: second export of the unchanged corpus produced
  identical manifest totals.
- `ghostdocs report` - PASS: report names the image-only PDF on the
  not-covered list and contains zero occurrences of the planted SSN.
- `--task "refund returns"` - PASS: narrowed to the 2 refund-policy
  sections.
- `--fit 60` - PASS: 59 tokens, exit 0. `--fit 5` - PASS after a fix
  (originally reported fitted on an empty bundle): bundle written,
  exit 1. Authoritative-source profile flip verified: pinning
  `policy-old.md` makes it the probable current with reason
  `authoritative-source`, overriding the date heuristic.
- `python3 -m py_compile src/ghostdocs/*.py` - PASS.

## Agent B test suite

Agent B's behavioural suite landed during this build (`tests/`, 15 tests).
Final run after alignment fixes: **15 passed**. Two core adjustments came
out of it: scan JSON now orders clusters and coverage gaps before the
document list (a filename's first mention carries its context), the summary
key is `coverage_gaps`, and the export manifest carries an explicit
`excluded_documents` list alongside `held_out` / `superseded_skipped`.
An earlier reproduction failure traced to the chunk-variant list in the
then in-progress test file, not the core; in the landed suite the default
export (bundle + chunks) satisfies the chunk-pack tests on the first
variant tried.

## Known gaps for parent verification / Agent B awareness

- Per-pattern coverage of the sensitive guard is shape-based; obfuscated
  personal data will not be caught. Hold-out is a gate, not a guarantee.
- Date detection reads the first explicit date in the text; documents whose
  first date is not the version date will be mis-ordered in clusters (the
  authoritative-source pin is the documented override).
- `scan --json` duplicate kind reports "near" for a mixed cluster that
  contains an exact pair plus an edited member; membership and waste are
  correct, the kind label describes the loosest link.
