# GhostLeads - Agent B Report (tests / README / examples)
Prepared Oct 14, 2026. Scope owned and edited by Agent B only: tests/**,
README.md, examples/**, this file. PLAN.md, src/**, and pyproject.toml
were read (read-only, after Agent A's core landed) but never edited.

## Result: PASS, 27/27 tests, run twice cleanly in a row
`python3 -m pytest tests -q` from ~/workspace/ghostleads:
- Final state: **27 passed, 0 failed**, twice in a row (18.43s, 19.81s),
  plus one earlier clean pass (12.64s).
- Breakdown: fixtures sanity 6, scoring 6, import and dedupe 6,
  pack 4, list filters and gates 5.

## Honest run history (read this before quoting the pass)
- The very first full run scored 21 passed / 6 failed **while Agent
  A's core was still landing** (src files were being written in the
  same minutes, and the run overlapped a manual demo run). Every
  later run, once the core was complete and runs were sequential,
  passed 27/27 three times in total. No test was loosened, skipped,
  or xfail-marked to reach green, and no core defect was found by
  this suite in its final form.

## Contract the tests drive (from PLAN.md, confirmed against landed core)
Agent A's landed CLI matches the plan exactly, so no alignment
fallbacks were needed beyond entrypoint discovery:
- `ghostleads import <file.csv|file.json> [--store leads.json]`
- `ghostleads score [--store] [--json]`
- `ghostleads list [--store] [--tier] [--town] [--trade]
  [--min-score] [--json]`
- `ghostleads pack [--store] [--out] [--lead NAME] [--all]`
- conftest.py entrypoint discovery: `ghostleads` on PATH, else
  `python -m ghostleads` with src/ on PYTHONPATH. If no entrypoint
  exists the behavioural tests FAIL with a "core not ready"
  message. They do not skip, so a missing build cannot fake green.

## What the tests verify
- Scoring (PLAN verification bar 1): no website (30) plus dead site
  (20) plus unclaimed profile (20) plus rating 3.7 (10) plus phone
  (5) scores exactly 85, Tier 1, with reasons naming the website,
  dead, and unclaimed signals. Template plus listing-only plus a
  4.8 showcase rating scores exactly 68, Tier 1. A none status,
  claimed profile, and 4.0 rating scores exactly 48, Tier 2.
- Honesty (PLAN bar 2): a live site, claimed profile, and mid
  rating scores exactly 13, Tier 3. A lead with every optional
  field unknown scores exactly 0: unknown is never scored as no
  website. All scores are in 0 to 100, output is ranked
  descending, and CSV and JSON imports of the same leads score
  identically.
- Import and dedupe: phone-format variants of one business
  (parenthesised vs bare digits, different name case) merge to
  one record, the first town wins, and a blank email is filled
  from the later row only. A nameless row is skipped and reported.
  Re-importing the same file adds nothing. A rating of 7.5 is
  rejected per-row with a reported reason and never stored
  clamped. website_status 404 normalises to dead (score 55 in
  fixture) and business.site to template (score 50). A missing
  input file fails non-zero with a message.
- Packs: a default pack run writes exactly one pack, for the
  highest scoring lead. `--all` writes all 5. Every pack is
  marked DRAFT ONLY / not sent, contains the verification
  checklist, the free website concept offer, Ghost Developer
  Studio, and Ryan Cotten, and contains no em dash character.
  A full lead's pack carries its stored trade, town, phone,
  rating, score, and reasons verbatim.
- Pack no-invention (PLAN bar 4): the single-lead sparse fixture
  (name only) produces a pack with no dead-site, unclaimed,
  no-website, or reputation angle, no dollar amount, no URL,
  no `.example` address, and no phone-shaped number other than
  the studio contact (423) 408-2150, which appears only as the
  studio contact.
- Gates: `--help` exposes only import, score, list, and pack,
  with no send, scrape, crawl, lookup, or enrich command, and a
  source scan of src/ghostleads finds no network module imports
  (urllib.request, http.client, socket, requests, smtplib, and
  similar).

## Fixtures built (all clearly fictional)
- tests/fixtures/scoring_leads.csv: 5 fictional businesses whose
  exact expected scores are worked out in the test docstring.
- tests/fixtures/dedupe_leads.csv: phone-format duplicate pair,
  one solo lead, and one nameless row that must be skipped.
- tests/fixtures/leads.json: JSON twin of the high and low leads
  for the CSV/JSON parity test.
- tests/fixtures/sparse_lead.csv: name-only lead for the
  no-invention pack test.
- tests/fixtures/bad_rating.csv: one 7.5-rating row and one
  valid row.
- Every fixture business is fictional: notes say FICTIONAL,
  source is fictional-example, phones are 555-01xx numbers, and
  the one email uses a `.example` address. No real Sep 25
  prospect, phone, or business detail appears in any fixture,
  example, or test.

## README and examples
- README.md: plain words. Covers what the tool does not do (no
  scraping, no sending, no finding details, no invented details),
  the input field table with normalisation rules, the four
  commands, the full scoring table and tier cutoffs, the dedupe
  rule (first wins, fill blanks only), pack contents and copy
  rules, the stale-data warning, and status with pricing and
  release stated as not decided. No em dash appears in the
  README or examples (checked by grep and by a sanity test).
- examples/sample_leads.csv and sample_leads.json: the fictional
  5-lead and 2-lead sample files.
- examples/WALKTHROUGH.md: import, score, filtered list, and
  pack commands, each run verbatim by Agent B on Oct 14, 2026
  and verified: import reported 5 added, 0 merged, 0 skipped;
  the ranked table was 85, 68, 48, 13, 0 exactly as the
  walkthrough table states; the default pack wrote only the
  Hilltop pack; `--all` wrote 5 packs; and the Mystery Works
  pack was read in full and confirmed blank-where-unknown with
  no invented angle, price, URL, or phone.

## Gates honoured
Local only, no network use, no scraping, no sending, no push,
no publish, no announcements, no spend. Tests run the core as a
local subprocess against copies of fixtures in pytest tmp dirs
with the store inside the tmp dir, so checked-in fixtures and
any real lead list are never written to by a run. Files outside
the Agent B ownership list were not edited.
