# GhostLeads
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostleads/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostleads/actions/workflows/ci.yml/actions)

**Score the local business leads you already found, and draft a pitch pack for the best ones. All on your own computer.**

GhostLeads is a studio-internal tool for Ghost Developer Studio. It takes a list of businesses you researched yourself, in a CSV or JSON file, scores each one for a website outreach angle, removes duplicates, and writes a draft pitch pack you can check before you decide whether to contact anyone.

It does not find businesses. It does not contact businesses. Finding leads is your research. Sending anything is your manual step, outside this tool.

By Ghost Developer Studio. GhostLeads is the business-side companion in the GhostSlice suite: the other tools govern what an agent reads and does, this one governs your own outreach pipeline.

> **At a glance**
>
> - **You give it:** a CSV or JSON file of leads you researched yourself. Only `name` is required per lead.
> - **It gives you:** a ranked list (score 0 to 100, Tier 1 to 3, with a reason for every point) and, on request, one Markdown draft pack per lead.
> - **It keeps:** one local JSON store file that you choose with `--store`. No accounts, no cloud, no upload.
> - **Drafts-only rule:** there is no send command and no network use of any kind. Every pack says `DRAFT ONLY. Not sent.` You verify and send manually, outside this tool, or you do not send at all.

## Contents

- [Quick start](#quick-start)
- [What GhostLeads does not do](#what-ghostleads-does-not-do)
- [Input format](#input-format)
- [The four commands](#the-four-commands)
- [How scoring works](#how-scoring-works)
- [Duplicates](#duplicates)
- [What is in a pack](#what-is-in-a-pack)
- [Troubleshooting and common questions](#troubleshooting-and-common-questions)
- [Two things to know before you trust it](#two-things-to-know-before-you-trust-it)

## Quick start

You need Python 3.10 or newer. Run these commands from the GhostLeads folder. The sample file uses fictional businesses, so this run is safe to try end to end.

```bash
# 1. Import leads you researched into a local store file
PYTHONPATH=src python3 -m ghostleads import examples/sample_leads.csv --store leads.json

# 2. Score every lead and print the ranked table
PYTHONPATH=src python3 -m ghostleads score --store leads.json

# 3. List leads, optionally filtered
PYTHONPATH=src python3 -m ghostleads list --store leads.json --tier 1

# 4. Draft a pitch pack (with no selector, only the top lead is drafted)
PYTHONPATH=src python3 -m ghostleads pack --store leads.json --out packs/
```

If you installed the package, you can use the short form instead: `ghostleads` in place of `PYTHONPATH=src python3 -m ghostleads`. Both forms run the same code.

Expected result on the sample file: 5 leads imported, top score 85 (Tier 1), and one pack written by step 4. A step-by-step run with expected scores for all five sample leads is in `examples/WALKTHROUGH.md`.

The usual workflow after the first import is: import more files into the same store as you research them, re-run `score` or `list` to see who ranks highest, then run `pack --lead NAME` or `pack --all` when you are ready to review drafts.

## What GhostLeads does not do

- It does not scrape, search, crawl, or look anything up. There is no network use of any kind.
- It does not send email, texts, messages, or forms. There is no send command.
- It does not find phone numbers, emails, or any other detail that is not already in your file.
- It does not invent business details. If a field is blank in your file, it stays blank in the score and in the pack. Unknown is never treated as a gap.
- It does not judge a business. A low score only means a weak website angle from the fields you supplied, nothing more.

## Input format

A CSV file with a header row, or a JSON file holding a list (or an object with a `leads` list). Only `name` is required. Leave any field you do not know blank: blank means unknown, and unknown scores zero rather than being guessed.

### Smallest useful examples

A CSV with two leads, one fuller and one name-only:

```csv
name,trade,town,phone,email,has_website,website_status,google_profile,rating,notes,source
Hilltop Quarry Hauling,Hauling,Exampleton,423-555-0142,,false,dead,unclaimed,3.7,,my-notes
Mystery Works,,,,,,,,,,
```

The same idea in JSON (a list, or wrap it as `{"leads": [ ... ]}`):

```json
[
  {"name": "Hilltop Quarry Hauling", "trade": "Hauling", "town": "Exampleton",
   "phone": "423-555-0142", "has_website": false, "website_status": "dead",
   "google_profile": "unclaimed", "rating": 3.7}
]
```

Full fictional examples you can import as-is are in `examples/sample_leads.csv` and `examples/sample_leads.json`.

### Fields

| Field | Values | Notes |
|---|---|---|
| name | text | Required. Rows with no name are skipped and reported. |
| trade | text | Blank if unknown. |
| town | text | Blank if unknown. |
| phone | text | Blank if unknown. Example files use fictional 555 numbers. |
| email | text | Blank if unknown. Most leads are phone only, and email is never required. |
| has_website | true/false, yes/no, 1/0, blank | Blank means unknown, and unknown scores zero. It is not treated as no website. |
| website_status | live, dead, template, none, unknown | `404` is read as dead. `business.site` is read as template. |
| google_profile | claimed, unclaimed, listing-only, none, unknown | Blank or unknown scores zero. |
| rating | 0 to 5, or blank | Out of range values are rejected on import, never quietly fixed. |
| notes | text | Your own notes, kept with the record. |
| source | text | Where the lead came from, shown in the pack so you can re-verify it. |

Notes for people preparing a file by hand:

- Header names are matched case-insensitively. Common aliases are also accepted: `business` or `business_name` for `name`, `city` or `location` for `town`, and `type` or `category` for `trade`.
- In JSON, write `rating` as a number (for example `4.2`), not as `true` or `false`, and `has_website` as `true` or `false` without quotes if you know it.
- A row with a bad rating or an unrecognised `website_status` or `google_profile` value is skipped, and import prints the row number and the reason. Valid rows in the same file still import.
- Files saved with a UTF-8 byte order mark (common from spreadsheets and editors) are accepted for both CSV and JSON.

The store is one local JSON file. You choose its path with `--store` (default: `leads.json` in the current folder). It is the only state the tool keeps.

## The four commands

| Command | What it does | Default behaviour to know |
|---|---|---|
| `import FILE` | Read a CSV or JSON file, validate and dedupe it, score the leads, and save the store. | Prints imported, added, merged, and skipped counts. Creates the store if it does not exist yet. |
| `score` | Recompute every score and tier from the stored fields, save them back, and print the ranked table. | Add `--json` for the full stored records as JSON instead of the table. |
| `list` | Print leads ranked by score, with optional filters. | Filters: `--tier 1|2|3`, `--town X`, `--trade Y`, `--min-score N`. Town and trade matching is exact and case-insensitive. Add `--json` for full records. |
| `pack` | Write one Markdown draft pack per selected lead. Drafts only, nothing is sent. | With no selector, only the single highest scoring lead is packed, so a stray run never floods your disk. Use `--lead NAME` for one named lead (name or slug) or `--all` for every lead. Output folder defaults to `packs/`, set with `--out`. |

Full examples:

```bash
PYTHONPATH=src python3 -m ghostleads import examples/sample_leads.csv --store leads.json
PYTHONPATH=src python3 -m ghostleads score --store leads.json
PYTHONPATH=src python3 -m ghostleads score --store leads.json --json
PYTHONPATH=src python3 -m ghostleads list --store leads.json --tier 1
PYTHONPATH=src python3 -m ghostleads list --store leads.json --town Exampleton --json
PYTHONPATH=src python3 -m ghostleads pack --store leads.json --out packs/
PYTHONPATH=src python3 -m ghostleads pack --store leads.json --out packs/ --all
PYTHONPATH=src python3 -m ghostleads pack --store leads.json --out packs/ --lead "Hilltop Quarry Hauling"
```

Run `ghostleads --help`, or `ghostleads <command> --help` for any command, to see its exact options where you are working.

Exit codes, the same for every command: `0` means ok, `1` means no leads matched (for example an empty store, a filter with no results, or a `--lead` name that matches nothing), and `2` means the command could not run (for example a missing store, an unreadable import file, or invalid data in the store). Errors are printed to stderr with a short reason, not a traceback.

A worked run is in `examples/WALKTHROUGH.md`. The sample files use clearly fictional businesses, fictional 555 phone numbers, and `.example` addresses, so you can try every command safely.

## How scoring works

Scoring is additive, capped at 100, and every point carries a reason that is shown in the output and in the pack. It is never just a number.

| Signal | Points |
|---|---|
| No dedicated website | +30 |
| Website status: dead | +20 |
| Website status: template only | +15 |
| Website status: none | +10 |
| Google profile: unclaimed | +20 |
| Google profile: none | +15 |
| Google profile: listing only | +10 |
| Rating below 3.8 (reputation angle) | +10 |
| Rating 4.5 or above (strong reviews to showcase) | +8 |
| Rating 3.8 to 4.49 | +3 |
| Phone on file | +5 |
| Email on file | +5 |

Tiers: 60 and above is Tier 1, 40 to 59 is Tier 2, below 40 is Tier 3.

How to read a score:

- **Tier 1 (60 to 100):** strongest website angle in your data. Look at these first.
- **Tier 2 (40 to 59):** a real but partial angle. Worth reviewing after Tier 1.
- **Tier 3 (below 40):** weak angle from the fields supplied, or too little known. A low score is not a judgement on the business.
- **Reasons matter more than the total.** Two leads can share a score for different reasons, and the reasons tell you what the draft pitch can honestly say.
- **Unknown scores zero.** A lead with everything unknown scores 0. That honesty is the point: the tool never rewards a field you did not supply.

Worked check: a lead with no website (+30), a dead website status (+20), an unclaimed profile (+20), a 3.7 rating (+10), and a phone on file (+5) scores 85, Tier 1. The sample file and walkthrough show this exact calculation.

Rating cuts both ways and the reason says which: a low rating is a reputation rebuild angle, a high rating is proof worth showcasing on a real site. A lead with a live website, a claimed profile, and a middle rating scores low, and a lead with everything unknown scores zero.

## Duplicates

Import dedupes against the store and inside the file. Two rows are the same lead when the normalised name matches (an `&` reads as "and", and apostrophes are ignored, so directory spelling variants line up) and either the phone digits match, or the towns match and at least one of the two rows has no phone to compare. Phone digits ignore formatting and a leading US country code `1`, so `1-423-555-0100` and `(423) 555-0100` are the same number. Two rows with different phones on file never merge: they may be two branches, or one business with an old and a new number, and only a human can tell which.

Near-spelling variants merge too, under a higher bar. One directory may mistype a name (Dautel in one listing, Dautell in another): if exactly one word differs by a small typo (a letter added, dropped, swapped, or two slips in a long word, with the first letter unchanged), the rows can still merge, but only with corroboration from the other fields you supplied. A matching phone is enough on its own. Without a matching phone, the towns must match and be known, and either the emails must agree, or the trades must agree plus one known business attribute (rating, website status, or Google profile) must agree. Town and trade alone never merge two differently spelled names, and a sparse misspelled row with nothing else in common stays a separate lead: a missed merge is visible and fixable by hand, while a wrong merge would silently hide a lead.

The first record wins. A later duplicate can only fill in fields that are blank in the first record. It can never overwrite a different value you already had. Import prints how many leads were imported, merged, and skipped, so you can spot a merge that looks wrong.

If a business you expected to merge stays as two leads, check the name spelling first (one-letter variants do not merge automatically), then check whether both rows carry different phones, which blocks a merge by design.

## What is in a pack

One Markdown file per lead, named from the business name (for example `hilltop-quarry-hauling-pitch-pack.md`). If two leads in one run would produce the same file name, later packs in that run get a `-2`, `-3` suffix instead of overwriting the pack written just before them.

- Lead snapshot: name, trade, town, phone, and email, exactly as stored. Unknown fields show as `(blank)`, never filled in. If two stored fields contradict each other (for example, no website, but the website status says live), the snapshot flags the conflict instead of picking a side.
- Score snapshot: score, tier, and every score reason, plus the import source so you can re-verify the lead.
- Suggested angle: sentences built only from the score reasons. No reason, no angle.
- Draft pitch: a short outreach draft using only known fields. It offers a free custom website concept, names Ghost Developer Studio and Ryan Cotten, and gives the studio public contact phone (423) 408-2150 as the studio contact only. It is never presented as the lead's phone.
- Verification checklist: re-check the business is still operating, the website status is still accurate, and the phone still matches, before any manual send.
- A closing line on every pack: DRAFT ONLY. Not sent. Sending is Ryan's manual step.

Copy rules are enforced in code: no em dash character appears in a generated pack, and no business detail appears in a pack unless it is in the stored record.

## Troubleshooting and common questions

**`error: store not found` (exit 2).** You ran `score`, `list`, or `pack` before any import, or with a different `--store` path than the import used. Run `import` first, and use the same `--store` value for every command in a session.

**A row was skipped on import.** Import prints `skipped row N: <reason>` for each one. The usual causes are a missing `name`, a `rating` outside 0 to 5 or not a number, or an unrecognised `website_status` or `google_profile` value. Fix that row in your file and import again: rows already in the store will merge rather than duplicate.

**`pack` only wrote one file.** That is the default on purpose. Add `--all` to pack every lead, or `--lead NAME` to pack one named lead.

**Why does a lead score 0?** Every scored field is unknown or scores zero: for example a name-only lead, or a lead with a live website and a claimed profile and no rating or contact details on file. Add only facts you have actually verified, then re-run `score`.

**Why does the draft mention (423) 408-2150?** That is the Ghost Developer Studio public contact number, printed in the draft pitch as the studio contact so a lead can reply to Ryan. It is a deliberate constant in the code (`STUDIO_CONTACT` in `packs.py`). It is never used as a lead's own phone number.

**Can GhostLeads send the pitch for me?** No. There is no send command and no network code. Review the draft, run the verification checklist in the pack, and send manually outside the tool if you decide to send at all.

**I edited the store JSON by hand and now commands fail.** The store is validated on load with the same rules as an import row. A bad stored value (for example a rating of `"high"`) fails with a clean `cannot read store` error and exit 2. Fix or remove the bad value in the JSON and try again.

## Two things to know before you trust it

**Imported data goes stale fast.** A business can close, get a website, or change its phone after you researched it. GhostLeads scores the data it was given. That is why every pack carries a re-verify warning and a checklist. Verify first, every time.

**A score is a ranking aid, not a verdict.** Use it to decide who to look at next, then use your own judgement.

## Your responsibility

Only import businesses and contact details you gathered yourself through legitimate research, and handle them under the rules that apply to you. The store is a local file. This tool never uploads it.

## Status

Version 0.1. Local CLI only, Python standard library only, no accounts, no cloud, no telemetry. Pricing and any public release are not decided. Nothing about this tool is announced or published by building it.

---
<!-- ghost-studio-footer -->
## More from Ghost Developer Studio

Ghost Developer Studio builds developer tools, AI-agent safety software, and practical apps, and sells by showing working software, not slide decks.

- [Roadmap board](https://github.com/littlestjames82-sys/ghost-roadmaps): where every studio product stands
- [Agent Seatbelt](https://github.com/littlestjames82-sys/agent-seatbelt): deterministic guardrails for AI coding agents
- [Ghost Hands](https://github.com/littlestjames82-sys/ghost-hands): governed, recorded, replayable agent hands
- [GhostSlice](https://github.com/littlestjames82-sys/ghostslice): agent context and prompt optimizer
- [GhostIDE](https://github.com/littlestjames82-sys/ghostide-android): fully offline AI code editor for Android
- [All studio projects](https://github.com/littlestjames82-sys?tab=repositories)
