# GhostLeads - Offline Lead Manager and Scorer for Local Businesses
Working name, prepared Oct 14, 2026. Wave 3 tool #22 for Ghost Developer Studio.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostLeads: plain job, plain name. It manages and scores leads Ryan already found. It does not find leads by scraping.
- Checked against the family: business-side companion to the GhostSlice suite, the first tool in Wave 3 aimed at Ryan's East Tennessee website outreach rather than at an agent workflow.
- Alternatives held in reserve: GhostProspects (longer, same meaning), GhostOutreach (implies sending, which v0.1 must never do).

## The problem
On Sep 25, 2026 Ryan built a real prospect list by hand: 14 East Tennessee businesses in Tier 1 and Tier 2 plus 4 email-verified Tier 3 leads, saved at ~/workspace/your_files/east-tn-website-prospects.md. Every entry was verified as having no dedicated website: Facebook only, a dead Google business.site page, or directory listings only.

That work does not scale and does not repeat well:
- The scoring is in Ryan's head and in prose notes (no website, dead site, unclaimed profile, low rating, strong rating worth showcasing).
- Dedupe is manual. The same shop appears under directory variants, alternate phones, and near-duplicate names (Dautel vs Dautell is the standing example).
- A pitch pack per lead is hand-built each time, which risks drifting copy, invented details, and formatting Ryan has already corrected (no em dashes in copy he will post).
- There is no single local store to ask: who is next, who scores highest, who is phone-only.

Today the list lives in one markdown file and the next lead is whoever Ryan remembers.

## Position in the Ghost stack
- GhostSlice and its companions govern what an agent reads and does.
- GhostLeads governs Ryan's own outreach pipeline: which local business to approach next, and with what draft.
- It shares the house rules, not the code: stdlib only, local only, no network, drafts first, sending is a human gate.
- LoadMaster and QuoteShot are customer-facing job tools. GhostLeads is studio-internal. No overlap.

Story: Ryan researches a business by hand (or a future, separately gated source supplies a list) -> GhostLeads imports it -> scores and dedupes it -> drafts a pitch pack -> Ryan verifies and sends manually, or does not send at all.
No step in v0.1 finds, contacts, or messages a business.

## How it uses the Sep 25 scoring shape, concretely
The scorer encodes the exact signals Ryan already used in the prospects file:
- No dedicated website scores highest. Facebook only and directory only still count as no website.
- A dead website scores above a merely missing one: Google retired business.site in 2024 and Woodland Tree Service, TNK Tree Service, Johnson Tree Experts, and Common Grounds Services all show dead template pages. A dead link is a concrete talking point.
- Template-only presence (a live business.site or equivalent) scores below dead, above a real site.
- An unclaimed Google or directory profile scores high (Buck's Heating and Air: unclaimed Birdeye profile is the standing example).
- Rating cuts both ways and the reason must say which: a low rating is a reputation rebuild angle, a high rating is proof worth showcasing on a real site. Middle ratings score low.
- Reachability is a small bonus, never the main score: a phone on file, and an email on file where one was publicly verified. Most Tier 1 and Tier 2 leads are phone-only, so email must never be required.

Reuses, does not rebuild:
- The prospect fields from the Sep 25 file: name, trade, town, phone, plus email, presence notes, and rating where known.
- Ryan's approved copy shape: studio introduction, what was noticed about that business, a free custom website concept offer, services and quote form angle, and a clear next step. Copy is a template in code, not free-generated text.
- The house draft rule: no em dashes in any copy Ryan would post or send.

## MVP (v0.1) - local CLI first, no dashboard
Rationale: same as Slice v0.1. A CLI proves scoring and pack generation on the real Sep 25 list shape in days.

Input format (CSV or JSON, local files only):
- Required: name
- Optional, blank where unknown: trade, town, phone, email, has_website, website_status, google_profile, rating, notes, source
- has_website accepts true/false, yes/no, 1/0, and blank for unknown. Unknown is not treated as no website.
- website_status accepts: live, dead, template, none, unknown (404 and business.site are normalised to dead / template on import).
- google_profile accepts: claimed, unclaimed, listing-only, none, unknown.
- rating accepts a number from 0 to 5, or blank. Out of range values are rejected on import, not silently clamped.

Local store:
- A single JSON file (default leads.json, path chosen with --store). It is the only state.
- Each lead keeps its raw imported fields, a normalised dedupe key, a score, a tier, and a list of score reasons. Reasons are always shown, never just a number.

1. Import: `ghostleads import <file.csv|file.json> [--store leads.json]`
   - Parses CSV with csv.DictReader or JSON (a list, or an object with a leads key). No other formats in v0.1.
   - Normalises fields, validates rating and enum values, and skips rows with no name, reporting each skip by line or index.
   - Dedupes against the store and inside the file: same normalised name plus same phone digits, or same normalised name plus same town when no phone is present. On a duplicate, the first record wins and later non-blank fields fill blanks only. No field is ever overwritten with a different non-blank value.
   - Prints imported, merged, and skipped counts. Writes the store only on success.

2. Score: `ghostleads score [--store leads.json] [--json]`
   - Recomputes every score from stored fields, saves them back, and prints a ranked table.
   - Scoring (additive, capped at 100, every point carries a reason):
     - has_website is false: +30, reason no dedicated website
     - website_status dead: +20, template: +15, none: +10, live: +0, unknown: +0
     - google_profile unclaimed: +20, none: +15, listing-only: +10, claimed: +0, unknown: +0
     - rating below 3.8: +10 reputation angle, rating 4.5 or above: +8 strong reviews to showcase, rating 3.8 to 4.49: +3, no rating: +0
     - phone present: +5, email present: +5
   - Tiers from score: 60 and above Tier 1, 40 to 59 Tier 2, below 40 Tier 3. These mirror the hand tiers: a no-website, dead-site, unclaimed lead lands in Tier 1 without hand tuning.
   - Unknown fields score zero and are listed as unknown in the pack. Unknown is never scored as a gap.

3. List: `ghostleads list [--store leads.json] [--tier 1|2|3] [--town X] [--trade Y] [--min-score N] [--json]`
   - Ranked by score descending, then name. Filters are exact, case-insensitive for town and trade.
   - Human output is a plain table: score, tier, name, trade, town, phone. JSON output is the full stored records.

4. Pack: `ghostleads pack [--store leads.json] [--out packs/] [--lead NAME] [--all]`
   - Generates one markdown pitch pack per selected lead. With no selector it packs the single highest scoring lead only, so a stray run never floods the disk. --all packs every lead.
   - File name is a slug of the business name. Existing pack files for the same lead are overwritten only when that lead is selected again, and the pack says it is a draft.
   - Pack contents, in order:
     - Header: business name, trade, town, phone, email, with any unknown field shown as blank, never filled in.
     - Score snapshot: score, tier, and every score reason, plus a re-verify before pitching warning with the import source and date fields as stored.
     - Suggested angle: sentences built only from score reasons (dead site, unclaimed profile, rating angle, no website). No angle is stated for a field that is unknown.
     - Draft pitch: short outreach draft using only known fields. If trade or town is unknown, the sentence omits that detail instead of guessing it. The draft offers a free custom website concept, names Ghost Developer Studio and Ryan Cotten, and gives the public contact phone (423) 408-2150 only as studio contact, never as the lead's phone.
     - Verification checklist: re-check the business is still operating, the website status is still accurate, and the phone still matches, before any manual send. Select Buildings and Backwoods in the Sep 25 list are the reason this checklist exists: one was flagged possibly closed, one possibly inactive.
     - A closing line in every pack: DRAFT ONLY. Not sent. Sending is Ryan's manual step.
   - Copy rules enforced in code and testable: no em dash character anywhere in a generated pack, and no business detail appears in a pack unless it is in the stored record.

## Out of scope for v0.1
- Scraping, searching, crawling, or any network call of any kind. No web search, no Google, no directory lookups, no map lookups.
- Sending anything: no email, no SMS, no Messenger, no form submission. There is no send command.
- Enrichment: no finding emails or phones that are not already in the imported file.
- Inventing or inferring business details: no guessed years in business, owners, services, ratings, or addresses. Blank stays blank.
- CRM features: no accounts, no cloud sync, no pipeline stages beyond score and tier, no reminders.
- Free-generated pitch text from a model. Pitch copy is fixed templates filled from stored fields only.

## Build estimate
- Lead model, CSV and JSON import, normalisation, dedupe: 1-2 days
- Scorer with reasons and tiers: 1 day
- Store, list, and score CLI: 1 day
- Pack generator with copy rules: 1-2 days
- Tests (scoring fixtures from the Sep 25 shapes, dedupe variants, pack no-invention and no-em-dash checks), README, examples: 1-2 days
Total: roughly 1 week to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands, if it is ever released. It is a studio-internal tool first.
- No paid layer is designed or built in v0.1.

## Verification bar
- Scoring test: a lead with no website, a dead site, and an unclaimed profile scores Tier 1, and every point is explained by a reason.
- Honesty test: a lead with a live website, a claimed profile, and a mid rating scores Tier 3, and a lead with all optional fields unknown scores only on what is actually known.
- Dedupe test: the same business imported twice with directory spelling variants and the same phone merges to one record, with no non-blank field overwritten.
- Pack test: a pack for a lead with no email, no rating, and no trade contains none of those details, shows them blank, and contains no em dash character.
- Offline test: the package imports no network modules and the CLI works with no network access.

## Risks / honest notes
- Imported data goes stale fast. The Sep 25 file itself says re-verify before pitching. GhostLeads scores the data it was given; it cannot know a business closed, got a site, or changed its phone. Every pack carries that warning.
- Scoring is a ranking aid, not a judgement on a business. A low score means a weak website angle from the stored fields, nothing more.
- Dedupe by name plus phone can miss a business that changed its number, and can over-merge two branches with a shared name in different towns when phones are missing. The town tiebreak and the fill-blanks-only merge are the v0.1 guardrails, and merges are counted in import output so Ryan can spot them.
- Contact details in the store are third-party business contacts from Ryan's own research. The store is a local file, never uploaded by this tool.

## Next gate
Ryan's go on: (1) GhostLeads as working name, (2) CLI-first with the import / score / list / pack command set, (3) scoring weights and tier cutoffs above, (4) pack copy template as drafted in code, reviewed by Ryan before any pack is used. No outreach is sent by this tool at any gate.
