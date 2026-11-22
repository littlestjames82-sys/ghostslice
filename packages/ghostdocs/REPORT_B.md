# GhostDocs - Agent B Report (tests / README / examples)
Prepared Oct 14, 2026. Scope owned and edited by Agent B only: tests/**,
README.md, examples/**, this file. src/** and pyproject.toml were read
(read-only, after Agent A's core landed) but never edited.

## Result: PASS, 15/15 tests, run twice
`python3 -m pytest tests -q` from ~/workspace/ghostdocs:
- Final state: **15 passed, 0 failed**, twice in a row (8.87s, 5.26s).
- Breakdown: fixtures sanity 6, dedupe 2, PDF coverage 3,
  personal-data hold-out 2, reproduction (chunk pack) 2.

## Honest run history (read this before quoting the pass)
- The first full run scored 12 passed / 3 failed **while Agent A's core
  was still landing** (src/ files were being written during the run;
  the dedupe scan test that failed then passes standalone and in both
  final runs). Early numbers from that window are not meaningful.
- Two of the three failures exposed weaknesses in MY tests, not the
  core, and both were fixed to structured checks rather than loosened:
  1. The dedupe export test searched manifest *text* for the old file
     name. The core correctly records superseded files under
     `superseded_skipped` (bookkeeping, not inclusion). The test now
     parses manifest.json: files list must be exactly
     ["returns-policy-v2.md"] among returns files, and the skipped
     list must name v1 + copy.
  2. The PDF scan test used a 700-char text window around a file name,
     which can false-positive in JSON where entries sit close together.
     It now parses the scan JSON and reads the not_covered list itself,
     with the text-window check kept only as a fallback for non-JSON
     output.
- No core defects were found by this suite in its final form.

## Contract the tests drive (assumptions, then what actually landed)
Written against PLAN.md before core existed, then aligned by reading
the landed src/ghostdocs/cli.py (read-only):
- Assumed and confirmed: `ghostdocs scan <corpus> [--json]`,
  `ghostdocs export <corpus> -o <out>`, `ghostdocs report <corpus> -o
  <file>` (the -o is required in the landed CLI), manifest.json +
  chunks.jsonl in the export, chunk rows carrying source /
  heading_trail / date / sha256 / estimated_tokens / text.
- Adjusted during alignment: the chunk pack is not a separate flag in
  the landed core, the default export shape is "both" (bundle +
  chunks). tests/test_reproduction.py tries the default first, then
  `--shape chunks`, then `--format chunks`.
- Entrypoint discovery in conftest.py: `ghostdocs` on PATH, else
  `python -m ghostdocs` with src/ on PYTHONPATH. If no entrypoint
  exists the behavioural tests FAIL with a "core not ready" message,
  they do not skip, so a missing build cannot fake a green run.

## Fixtures built (all required cases from the task)
- tests/fixtures/dedupe_corpus: returns-policy-v1.md (Updated
  2024-01-15), returns-policy-copy.md (byte-identical to v1, sha256
  d07ab016... both), returns-policy-v2.md (near-duplicate edit, Updated
  2026-03-01, 30 days changed to 45 days; plain line Jaccard 0.833),
  opening-hours.md as unrelated control. Behaviour verified:
  cluster of three, v2 marked probable current (newest-date heuristic),
  deduped export contains the 45-day text and nowhere the 30-day text,
  control document survives.
- tests/fixtures/pdf_corpus: store-manual-text.pdf (real text layer,
  generated), scanned-flyer.pdf (image-only, zero text operators),
  warranty.md control. Behaviour verified: image PDF named not covered
  in scan, report, and export, and copied into no bundle; text PDF is
  read and not listed as not covered.
- tests/fixtures/personal_corpus: customer-note-example.md with FAKE
  planted data only (test SSN shape 123-45-6789, test card
  4111 1111 1111 1111, .invalid email, 555 phone) plus clean
  delivery-info.md. Behaviour verified: flagged page held out of the
  default export (no raw value anywhere in the export), and scan +
  report name it by path + finding type only, raw values never
  printed.
- tests/fixtures/generate_pdfs.py: stdlib-only deterministic
  regenerator for both PDF fixtures (correct xref, no timestamps).
  Re-running it reproduces the checked-in fixtures.

## README and examples
- README.md: plain-words, aimed at a non-developer reader. Covers what
  it does and does not do, a formats covered / not covered table, the
  scan / export / report / check commands, the "probable current is a
  guess" warning, token numbers labelled estimates, the personal-data
  hold-out and the explicit --allow-sensitive recording, the optional
  .ghostdocs.json settings, and the only-process-what-you-have-the-
  right-to note from the plan. No pricing, pricing/release stated as
  not decided.
- examples/sample-help-centre/: four small documents plus a
  .ghostdocs.json (superseded: exclude). The two returns pages
  duplicate on purpose (2024 says 30 days, 2026 says 45).
- examples/WALKTHROUGH.md: four commands (scan, export, report,
  check), each run verbatim by Agent B on Oct 14, 2026 and verified:
  scan clustered the returns pages with the 2026 page as probable
  current (74 tokens waste), export skipped the old page, report was
  written, and `check` printed "Bundle OK: hashes and totals match
  manifest."

## Observation for the parent / Agent A (not a failure)
On the sample corpus the scan prints "deduped: 157" estimated tokens
(document-level accounting: raw 231 minus duplicate waste 74) while the
export prints 155 exported tokens (section-level accounting). Both are
internally consistent (check passes, chunk totals equal manifest
totals), the 2-token gap is the accounting-basis difference. Worth a
line in user-facing docs if scan and export numbers are ever compared
side by side.

## Gates honoured
No network use, no push, no publish, no spend. Tests run the core as a
local subprocess against copies of the fixtures in pytest tmp dirs, so
checked-in fixtures are never written to by a run. Files outside the
Agent B ownership list were not edited.
