# GhostLeads v0.1 Polish Report
Oct 14, 2026. House loop: audit first, then two distinct improvement passes, demonstrate-then-fix.
Baseline before polish: 27 passed. Final: **40 passed** (27 existing, 13 new regression tests).
No version bump, no push, no publish, no announcements, no spend. Offline only throughout; no send command added; no em dashes added to any draft copy or docs.

## Audit findings (each demonstrated with a probe before any fix)

Prospect shapes checked against Ryan's real Sep 25, 2026 list (read-only, no real prospect data copied into tests or examples): most leads are phone-only, several carry alternate or older phone numbers under directory variants (including a one-letter name variant), ratings run from 2.3 to 5 stars, and the dead sites are retired Google business.site pages.

### Demonstrated defects
1. **Country-code phone variants never merged.** `1-423-555-0142` and `(423) 555-0142` produced different dedupe keys (11 digits vs 10), so the same business imported twice stayed two leads.
2. **A lead known phone-only in one row and phoneless in another never merged, in either order.** The dedupe key switched shape depending on whether that record happened to carry a phone, so the common directory pattern (one listing with a phone, one without) silently duplicated. Probe: merge reported added 1 / total 2 instead of merged 1 / total 1.
3. **Directory name variants never merged.** `Buck's` vs `Bucks` and `C & C` vs `C and C` normalised to different names (apostrophe became a space; `&` was dropped), defeating the phone match.
4. **A hand-edited or corrupted store crashed the CLI with a traceback.** `Lead.from_dict` bypassed all import validation, so a stored rating of `"high"` died inside scoring with a TypeError, and a bogus `website_status` scored a silent zero.
5. **A JSON import file with a UTF-8 BOM failed the whole import**, while the CSV reader already tolerated a BOM. Inconsistent and hostile to files saved by spreadsheets and editors.
6. **A JSON boolean rating was silently stored as 1.0.** `float(True)` turned `rating: true` into an invented low rating with a reputation angle attached.
7. **Multi-line field values could inject structure into a pack.** A name containing a newline followed by `##` printed as a real markdown heading inside the generated pack, in three places.
8. **Slug collisions silently destroyed packs.** Two leads whose names slug alike (for example differing only by punctuation) wrote to the same file under `--all`; the run reported two packs written and one file existed.
9. **Contradictory website fields produced a self-contradicting pack with no warning.** `has_website = no` with `website_status = live` scored and pitched as "no dedicated website" while its own snapshot said live.

### Verified correct, pinned with tests, not changed
- Rating boundaries are exact: 3.79 scores +10, exactly 3.8 and 4.49 score the middle +3, exactly 4.5 scores +8. Added boundary tests (previously only 3.7, 4.0, 4.2, and 4.8 were covered).
- Unknown fields score zero, the all-unknown lead scores 0, and the 100 cap exists (it is unreachable with the current weights, whose maximum raw total is 90; harmless, left alone).
- Malformed rows (no name, rating out of range, non-object JSON rows) are skipped with row numbers and reasons; a missing input file fails cleanly.
- Packs carry DRAFT ONLY at head and foot, blanks stay blank, and no em dash appears in any generated pack.

### README inaccuracies found
- The dedupe paragraph described key matching that did not cover the mixed-phone case (finding 2).
- The input table said "a retired template page address is read as template"; the actual rule is `business.site` reads as template.
- The pack section called the lead snapshot a "Header".

## Pass 1: import and dedupe robustness
- `models.phone_digits`: a leading US country code `1` on an 11-digit number is stripped, so format variants share digits (finding 1).
- `store.same_lead` (new predicate, replaces key-only matching in `merge_leads`): same normalised name, and either matching phone digits when both records have phones, matching non-blank town when exactly one has a phone, or matching towns (blank equals blank) when neither has one. Two records with different phones never merge (finding 2, and the two-branches guardrail).
- `models.normalise_name`: `&` reads as "and" and apostrophes are removed rather than spaced (finding 3).
- `models.Lead.from_dict`: stored records now go through the same validation as import rows; invalid values raise ValueError, which the CLI already reports as a clean exit 2 with no traceback (finding 4).
- `store.read_import_file`: JSON is read as utf-8-sig, matching CSV (finding 5).
- `models.parse_rating`: booleans are rejected as not-a-number (finding 6).
- `models._clean`: all whitespace runs, newlines included, collapse to one space, so imported fields are single-line by construction (finding 7).
- Regression tests: `tests/test_polish_import_dedupe.py`, 10 tests, including the different-phones do-not-merge guardrail and the rating boundary pins.

### Regression found and fixed inside Pass 1
The first version of the new predicate required a non-blank town whenever a phone was missing, so a lead with neither phone nor town duplicated itself on re-import. Re-running the walkthrough verbatim caught it (sample import went 5 to 6 leads and produced a second Mystery Works pack). The neither-has-a-phone branch now treats two blank towns as a match, a regression test covers both the sparse fixture and the shipped sample file, and the walkthrough again holds exactly: second import adds 0, merges 5, total stays 5.

## Pass 2: pack quality and README accuracy
- `packs.write_packs`: within one run, slug collisions get a `-2`, `-3` suffix instead of overwriting a pack written moments earlier; re-running a single lead in a fresh run still overwrites its own pack, as the plan states (finding 8).
- `packs.build_pack`: a lead whose `has_website` and `website_status` contradict each other gets a "Data conflict to check" line in its snapshot naming both fields, instead of the pack quietly picking a side. Scores are unchanged; the scorer's additive table is plan-locked and locked by tests (finding 9).
- README: dedupe paragraph rewritten to describe the actual matching rules (including the country code and the different-phones guardrail), the `business.site` normalisation line corrected, the pack "Header" bullet renamed to the lead snapshot it actually is, and the snapshot bullet now mentions the conflict flag.
- Regression tests: `tests/test_polish_packs.py`, 3 tests (collision, conflict flag present and absent, single-pack re-run still overwrites).

## What was left alone, deliberately
- **Scoring weights, tiers, and the double signal for `has_website = false` plus `website_status = none`.** Plan-locked and test-locked (the 48-point fixture depends on it). A contradiction is now flagged in the pack rather than rescored.
- **One-letter name spelling variants** (the Dautel/Dautell shape in the real list). Fuzzy name matching risks merging genuinely different businesses; with different phones on file they stay separate, and the import merge counts surface the case for a human.
- **Alternate phone numbers for the same business stay unmerged.** That is the documented v0.1 guardrail: different phones may be branches, and only Ryan can tell.
- **Unrecognised `has_website` strings** (for example "maybe") still read as unknown rather than skipping the row. Unknown scores zero and shows as blank in the pack, so the failure mode is visible, not silent invention.
- **Notes text is shown as imported**, including any claim in it. It is labelled "as imported" in the pack and the verification checklist covers it.
- No dashboard, no new commands, no network, no enrichment. The four-command surface is unchanged.

## Final verification
- `python3 -m pytest tests -q`: **40 passed, 0 failed** (27 pre-existing plus 13 polish regressions).
- Walkthrough run verbatim end to end: import 5, scores 85 / 68 / 48 / 13 / 0 exactly as documented, re-import adds 0 and merges 5, all 5 packs written, zero em dash characters in README, walkthrough, or any generated pack.
