# GhostLeads v0.1 - Implementation Notes (Agent A, core)

Built Oct 14, 2026 from `PLAN.md`. Python stdlib only, fully offline,
no scraping, no network, no send command, no PyPI, no GitHub push,
no announcements, no spend.

## What was built (Agent A ownership: PLAN.md, src/**, pyproject.toml, this file)

```
PLAN.md                         Slice-format plan, scoring shaped on the Sep 25, 2026 prospects file
pyproject.toml                  ghostleads 0.1.0, zero dependencies, console script
src/ghostleads/__init__.py      version 0.1.0
src/ghostleads/__main__.py      python -m ghostleads
src/ghostleads/models.py        Lead dataclass, field normalisation, dedupe keys
src/ghostleads/scoring.py       additive scorer with reasons, tiers, unknowns list
src/ghostleads/store.py         local JSON store, CSV/JSON import, fill-blanks dedupe merge
src/ghostleads/packs.py         draft pitch pack generator (no-invention, no em dash)
src/ghostleads/cli.py           import / score / list / pack commands
```

Agent B owns tests/**, README.md, examples/** (separate handoff).

## Commands

```
ghostleads import <file.csv|file.json> [--store leads.json]
ghostleads score [--store leads.json] [--json]
ghostleads list [--store leads.json] [--tier 1|2|3] [--town X] [--trade Y] [--min-score N] [--json]
ghostleads pack [--store leads.json] [--out packs/] [--lead NAME] [--all]
```

Exit codes: 0 ok, 1 no leads matched / empty selection, 2 could not run
(missing store, unreadable import, invalid data). Pack with no selector
packs only the top scoring lead; --all is required to pack everything.

## Design decisions

- **Fields.** Exactly the task spec plus optional email, notes, and source:
  name (required), trade, town, phone, email, has_website,
  website_status, google_profile, rating. CSV headers are
  case-insensitive, with business/city/type accepted as aliases for
  name/town/trade. Ratings outside 0 to 5 and unknown enum values are
  rejected per row with a named skip, never clamped or guessed.
- **Normalisation.** website_status: 404/dead/gone maps to dead,
  business.site/google-site maps to template, facebook-only and
  directory-only map to none. google_profile: GBP/google-listing maps
  to listing-only. has_website parses true/false/yes/no/1/0; blank
  stays None (unknown) and scores zero.
- **Scoring (PLAN.md).** No website +30; status dead +20, template
  +15, none +10; profile unclaimed +20, none +15, listing-only +10;
  rating below 3.8 +10 (reputation angle), 4.5 or above +8 (strong
  reviews to showcase), middle +3; phone +5, email +5; capped at 100.
  Tiers: 60+ Tier 1, 40-59 Tier 2, below 40 Tier 3. Every point
  appends a human reason string stored on the lead.
- **Dedupe.** Key is normalised name (lowercase, punctuation and
  LLC/Inc/The stripped) plus phone digits, or plus lowercased town
  when no phone. First record wins; a duplicate only fills blank or
  unknown fields (fill_blanks_from) and never overwrites a known
  value. Import prints added / merged / total and each skip.
- **Packs.** One markdown file per lead, slug-named, containing the
  snapshot (unknown shown as (blank)), score with all reasons, an
  angle section built only from scored facts, a fixed-template draft
  pitch that omits unknown trade/town instead of guessing, a
  re-verification warning, and a pre-send checklist. Every pack opens
  and closes with DRAFT ONLY. The studio contact in the draft is
  Ryan's public number (423) 408-2150 from MEMORY.md, used only as
  studio contact, never as a lead field.
- **Copy rules enforced in code.** build_pack strips the em dash
  character (defined as an escape, so the literal never sits in
  template copy) as defence in depth, and no template sentence
  references a field unless that field is known. There is no send,
  scrape, or enrichment code path anywhere, and no network module is
  imported.

## Smoke test (Agent A, /tmp, real Sep 25 shapes)

Imported a 5-row CSV (Woodland Tree Service dead-site shape, Buck's
unclaimed 3.7 shape, a live-site realty control, an all-blank-fields
lead, and a Woodland duplicate row with a different phone format)
plus a 1-row JSON (Goldston's shape):

- Import 1: added 4, merged 1, total 4. Import 2: added 1, total 5.
- Scores: Woodland 78 Tier 1, Buck's 75 Tier 1, Goldston's 63 Tier 1,
  live-site control 18 Tier 3, all-unknown lead 0 Tier 3.
- Dedupe fill-blanks verified: the merged Woodland record gained the
  duplicate row's email and rating, and kept its original
  listing-only profile (no overwrite).
- Pack --all wrote 5 packs; no em dash in any pack, the all-unknown
  pack shows (blank) fields and states no angle, and packs for the
  sparse lead contain none of the merged lead's details.
- Error paths: missing store exits 2, a rating of 9 is skipped with
  its reason while valid rows still import, a nameless row is skipped,
  pack with no selector writes exactly one pack (the top lead).

## Known limits

- Dedupe can miss a business that changed phone and town spelling at
  once, and can over-merge same-name branches sharing a phone. Merges
  are counted in import output for Ryan to spot.
- Scoring is only as fresh as the import. Nothing in v0.1 re-checks
  a business, by design (no network).
- README.md is declared in pyproject.toml and owned by Agent B;
  it landed during this build, and Agent B's own suite was run
  against this core by Agent A as a cross-check: 27 passed.
