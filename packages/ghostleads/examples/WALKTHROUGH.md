# GhostLeads walkthrough

A full run on the fictional sample file, from an empty store to reviewed draft packs. Every business here is made up, every phone number is a fictional 555 number, and every email ends in `.example`. Nothing in this walkthrough is a real lead, and nothing is sent anywhere.

**Time needed:** about 5 minutes. **You will create:** one store file (`/tmp/ghostleads-demo.json`) and a folder of draft packs (`/tmp/ghostleads-packs/`). Both are in `/tmp` so the walkthrough leaves nothing in the project folder. Delete them when you are done, or keep them to experiment.

**Drafts-only reminder:** GhostLeads never sends anything. The packs in step 4 are drafts for you to read. Sending, if it happens at all, is a separate manual step outside this tool.

Run every command from the GhostLeads folder (the folder containing `README.md`). If you installed the package you can replace `PYTHONPATH=src python3 -m ghostleads` with `ghostleads` throughout.

## 0. Check the tool responds (optional)

```bash
PYTHONPATH=src python3 -m ghostleads --help
PYTHONPATH=src python3 -m ghostleads --version
```

Expected: help lists exactly four commands (`import`, `score`, `list`, `pack`) and the version prints as `ghostleads 0.1.0`. There is deliberately no fifth command for sending or looking businesses up. Run `PYTHONPATH=src python3 -m ghostleads pack --help` (and likewise for the other commands) to see each command's options.

## 1. Import

```bash
PYTHONPATH=src python3 -m ghostleads import examples/sample_leads.csv --store /tmp/ghostleads-demo.json
```

Expected shape: the command reports how many leads were imported, how many were merged as duplicates, and how many rows were skipped. The sample file has 5 clean rows, so expect:

```text
imported rows: 5
added: 5  merged (duplicates): 0  total in store: 5
```

What just happened: each row was validated, normalised, scored, and saved into the store file. No store existed before this command, so all 5 rows were added and none merged. If a row had failed validation (for example a rating above 5), you would see an extra `skipped row N: ...` line here and that row would not be in the store.

Prefer JSON? `examples/sample_leads.json` holds 2 of the same leads in JSON form. Import it into a different store file to compare, or into the same store to watch those 2 rows merge instead of duplicating.

## 2. Score

```bash
PYTHONPATH=src python3 -m ghostleads score --store /tmp/ghostleads-demo.json
PYTHONPATH=src python3 -m ghostleads score --store /tmp/ghostleads-demo.json --json
```

The first form prints a ranked table (highest score first). The second prints the full stored records as JSON, including the `reasons` list for each lead. Import already scores, so this step mainly shows the ranking and lets you re-score after a hand edit to the store.

Expected ranking, from the scoring table in the README:

| Lead | Math | Score | Tier |
|---|---|---|---|
| Hilltop Quarry Hauling | 30 no website + 20 dead + 20 unclaimed + 10 rating 3.7 + 5 phone | 85 | Tier 1 |
| Cedar Sign Works | 30 + 15 template + 10 listing only + 8 rating 4.8 + 5 phone | 68 | Tier 1 |
| Riverbend Fictional HVAC | 30 + 10 none + 0 claimed + 3 rating 4.0 + 5 phone | 48 | Tier 2 |
| Maple Street Corner Bakery | 0 live + 0 claimed + 3 rating 4.2 + 5 phone + 5 email | 13 | Tier 3 |
| Mystery Works | every optional field unknown | 0 | Tier 3 |

Mystery Works is the honesty check: it has no website field at all, so it earns no no-website points. Unknown scores zero. In the `--json` output, check that Hilltop's reasons name each part of its 85 points. A score in GhostLeads always comes with its reasons.

## 3. List with a filter

```bash
PYTHONPATH=src python3 -m ghostleads list --store /tmp/ghostleads-demo.json --tier 1
PYTHONPATH=src python3 -m ghostleads list --store /tmp/ghostleads-demo.json --town exampleton --json
```

The tier filter should return only Hilltop Quarry Hauling and Cedar Sign Works. The town filter is case-insensitive, so `exampleton` should return the same two leads.

Other filters to try: `--trade HVAC`, `--min-score 60`, and combining filters (for example `--tier 1 --town Exampleton`). A filter that matches nothing prints an empty table and exits with code 1: that means "no leads matched", not an error in your file.

## 4. Draft packs

```bash
PYTHONPATH=src python3 -m ghostleads pack --store /tmp/ghostleads-demo.json --out /tmp/ghostleads-packs/
PYTHONPATH=src python3 -m ghostleads pack --store /tmp/ghostleads-demo.json --out /tmp/ghostleads-packs/ --all
```

The first command drafts exactly one pack, for Hilltop Quarry Hauling, the highest scoring lead. That single-pack default is deliberate, so a stray run never floods your disk. The second drafts all five, one Markdown file per lead. To draft one named lead instead, use `--lead "Cedar Sign Works"`.

Each run prints one `pack: <path>` line per file written, then the reminder line:

```text
DRAFT ONLY. Not sent. Sending is Ryan's manual step.
```

### How to read a pack

Open the Hilltop pack first. In order, you will find:

1. **Lead snapshot:** the stored fields exactly as imported. This is what you claimed to know when you researched the lead.
2. **Score:** the total, the tier, and every reason behind the points.
3. **Suggested angle:** sentences built only from those reasons.
4. **Draft pitch:** a short outreach draft using only known fields. It names Ghost Developer Studio and Ryan Cotten and gives the studio public contact (423) 408-2150 as the studio contact only, never as the lead's phone.
5. **Verification checklist:** the checks to run before any manual send, because imported data goes stale.

Then open the Mystery Works pack and check the honesty rules yourself:

- Trade, town, phone, email, and rating show as `(blank)`, not filled in.
- There is no suggested angle about a dead site, an unclaimed profile, or a rating, because none of that is known.
- There is no price, no web address, and no phone number other than the studio contact (423) 408-2150, shown as the studio contact only.
- The pack starts and ends with the draft line: DRAFT ONLY. Not sent.

## 5. Duplicates, if you want to see them

Import the same file a second time into the same store:

```bash
PYTHONPATH=src python3 -m ghostleads import examples/sample_leads.csv --store /tmp/ghostleads-demo.json
```

Every row should merge instead of duplicating, and the lead count should stay at 5:

```text
imported rows: 5
added: 0  merged (duplicates): 5  total in store: 5
```

To see the matching rules work harder, edit a copy of the sample file (never the original) so one row spells the phone as `1-423-555-0142` or writes `Bucks` style name variants with `&` written as `and`, then import the copy. Those rows still merge: phone digits ignore formatting and a leading US country code `1`, and `&` reads as "and". Two rows carrying *different* phones never merge, by design: they may be two branches, and only a human can tell.

## If something looks different

- **`error: store not found`:** the `--store` path differs from the one you imported with, or the import has not run yet. Use the exact same path in every step.
- **Fewer than 5 leads after import:** read the `skipped` lines printed by import. They name the row and the reason.
- **Only one pack file:** you ran `pack` without `--all` or `--lead`. That is the default, not a failure.
- **A score differs from the table above:** check the row in the sample file was not edited, then compare its fields against the scoring table in the README. Every point must be explained by a reason in the `--json` output.

## Clean up and next steps

Delete the demo store and packs with `rm /tmp/ghostleads-demo.json` and `rm -r /tmp/ghostleads-packs/`, or leave them in `/tmp`, which clears itself.

For real use: research leads yourself, save them in the CSV or JSON format shown in the README, import them into a store you keep (for example `--store leads.json` in a working folder), work from the top of the ranking, and treat every pack as a draft to verify and approve by hand. GhostLeads stops at the draft.
