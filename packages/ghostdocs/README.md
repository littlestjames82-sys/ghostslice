# GhostDocs
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostdocs/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostdocs/actions/workflows/ci.yml/actions)

**Get your business documents ready for an AI assistant, without sending them anywhere.**

If your shop or office has years of help pages, policy documents, manuals,
and standard procedures, an AI assistant can only use them well if it is
fed the right pages. Feed it everything and it gets slow, expensive, and
confused by old versions. Feed it a hand-picked few pages and nobody can
show later exactly what it was given.

GhostDocs looks through a folder of your documents on your own computer
and prepares a clean, tidy set:

- It lists every document and roughly how big each one is.
- It finds copies and near-copies, and picks the newest dated one as the
  probable current version.
- It holds back any page that looks like it contains personal details
  such as card numbers, and tells you it did.
- It names any file it cannot read instead of quietly skipping it.
- It produces an export folder you can hand to an assistant, plus a list
  (a manifest) of exactly what went in, so the set can be checked later.

By Ghost Developer Studio. GhostDocs is the document companion to
GhostSlice, which does the same job for computer code.

## What GhostDocs does not do

- It does not answer questions. It prepares the reading material. The
  assistant does the answering.
- It does not change, fix, or delete your original documents. Ever.
- It does not send anything over the internet. There are no accounts,
  no uploads, and no tracking. Your documents stay on your machine.
- It does not read handwriting or scanned pages. If a PDF is just a
  picture of a page, GhostDocs will list it as not covered.
- It does not rewrite or summarise your documents with AI. What goes
  into an export is your own words, cut at heading boundaries.

## What it can read

| Format | Covered? |
|---|---|
| Markdown (.md) | Yes |
| Plain text (.txt) | Yes |
| Web pages saved as HTML (.html) | Yes, text only |
| PDF (.pdf) | Only if the PDF has a real text layer |
| Word documents (.docx, .doc) | Not in this version |
| Spreadsheets and slides | Not in this version |
| Scanned or photo PDFs | Not in this version (no OCR) |

Anything not covered is named in the scan and in the report. It is never
silently skipped, and it never appears in an export.

## The four everyday commands

You need Python 3.10 or newer. There is nothing to install and no
account to create: GhostDocs uses only the Python standard library,
and the commands below run it straight from this folder. From the
GhostDocs folder:

```bash
# 1. Look at a folder of documents
PYTHONPATH=src python3 -m ghostdocs scan path/to/your-documents

# 2. Make an export folder for an assistant
PYTHONPATH=src python3 -m ghostdocs export path/to/your-documents -o path/to/export

# 3. Make a plain-words report you can open in a browser
PYTHONPATH=src python3 -m ghostdocs report path/to/your-documents -o report.html

# 4. Confirm an export still matches its manifest list
PYTHONPATH=src python3 -m ghostdocs check path/to/export
```

A successful check prints `Bundle OK: hashes and totals match manifest.`
Any command can be followed by `--help` for its full options, for
example `python3 -m ghostdocs export --help` (with the `PYTHONPATH=src`
prefix above). A worked example with a sample document set is in
`examples/WALKTHROUGH.md`.

### Reading a scan

The scan prints, in order:

- A one-line summary: how many documents were read, how many files
  are not covered, and how many documents were held out.
- Estimated token totals: the raw total, how much of it is duplicate
  waste, and the smaller deduped total.
- A heat list, largest document first. `HELD OUT` means the document
  stays out of exports (see "Personal details" below). A `flags=`
  note names an extraction concern, for example `low-yield` on a PDF
  that produced very little text per page. A low-yield extraction is
  labelled, never hidden or presented as a clean read.
- Any duplicate clusters, naming the probable current member of each
  group and the older (stale) members.
- A not-covered list naming every file GhostDocs could not read and
  why. Nothing is silently skipped.

For scripts or a fuller record, add `--json` to a scan to get the
whole result as JSON, or `--top N` to show more (or fewer) documents
in the heat list. The default is 20.

### More export options

```bash
# Only the sections relevant to one topic
PYTHONPATH=src python3 -m ghostdocs export path/to/your-documents \
  -o path/to/export --task "returns policy"

# Try to keep the export under an estimated-token budget
PYTHONPATH=src python3 -m ghostdocs export path/to/your-documents \
  -o path/to/export --fit 4000

# Write only the chunk pack, or only the agent bundle (default is both)
PYTHONPATH=src python3 -m ghostdocs export path/to/your-documents \
  -o path/to/export --shape chunks
```

With `--fit`, non-authoritative documents are first reduced to
headings plus their first paragraph, then the lowest-priority
sections are dropped. If the export still cannot fit, it is written
anyway, a warning is printed, and the command exits with code 1 so
a script can tell it did not fit.

With the default `--shape both`, the export folder contains:

- `PROMPT.md` and `files/` - the documents, ready to hand over.
- `manifest.json` - the list of what went in, with a fingerprint of
  each file so the set can be verified later. It also records what
  was held out, what was skipped as superseded, and what was not
  covered, so the export can be audited, not just used.
- `chunks.jsonl` - the same material in section-sized pieces, for
  tools that load knowledge a piece at a time. Pieces are cut at
  headings, not at random lengths.

With `--shape bundle` only the first two are written, and with
`--shape chunks` only `chunks.jsonl` and `manifest.json` are written.

## Two things to know before you trust it

**"Probable current" is a guess.** When GhostDocs finds near-identical
pages it treats the newest dated one as the current version. Usually
that is right. Sometimes the older page is the one you still use. The
report shows its working, so check the picks that matter, especially
for policy and safety documents. If one folder is always the official
source, you can declare it in the settings file and its version wins.

**Sizes are estimates.** GhostDocs counts document size in tokens,
which is how AI assistants measure text. Its token numbers are careful
estimates, labelled as estimates in every output, not exact counts from
any one AI provider.

## Personal details are held back by default

Support documents often contain things customers pasted in: card
numbers, ID numbers, and similar. If a page contains shapes like
those, GhostDocs holds the whole page out of exports by default and
lists it in the report by file name and type of finding only. The
actual values are never printed in a scan, a report, or an export.

Including a held-back page is possible only with an explicit
`--allow-sensitive` flag on export, and the manifest records that you
did. Think carefully before using it.

## Settings (optional)

A file named `.ghostdocs.json` in your document folder can:

- Include or exclude files by pattern.
- Mark a folder as the authoritative source for duplicates.
- Set how each document is included: in full, headings only, or
  excluded.
- Choose whether older duplicate versions stay out of exports (the
  default) while still showing in reports.

No settings file is needed to get started. Patterns are filename
globs matched against paths inside the document folder. An example
that keeps only Markdown files, treats an `official/` folder as the
authoritative source, and shows one legacy manual as headings only:

```json
{
  "include": ["*.md"],
  "exclude": ["drafts/*"],
  "authoritative_sources": ["official/"],
  "modes": {"legacy-manual.md": "headings"},
  "superseded": "exclude"
}
```

The recognised keys are `include`, `exclude`,
`authoritative_sources`, `modes`, and `superseded` (`exclude` or
`include`). A mode is `full`, `headings`, or `exclude`. If the file
has a typing mistake, an unknown key, or an invalid value, GhostDocs
says so and stops (exit code 2) instead of silently ignoring it.

## Exit codes and common problems

| Exit code | Meaning |
|---|---|
| 0 | Success. For `check`, the bundle matches its manifest. |
| 1 | The work was done but something did not pass: an export could not fit its `--fit` budget, or `check` found a mismatch. |
| 2 | The command could not run: the document folder was not found, the `.ghostdocs.json` settings file is invalid, or (for `check`) the bundle has no `manifest.json`. |

- **"corpus folder not found"**: check the path to your document
  folder. GhostDocs needs the folder itself, not a single file.
- **A document is missing from an export**: check the scan first. It
  may be held out for sensitive shapes, skipped as a superseded
  duplicate, or listed as not covered. Each case is named in the scan,
  the report, and the export output.
- **A PDF shows as not covered or low-yield**: it probably has no real
  text layer (for example it is a scan or a photo of a page). GhostDocs
  does no OCR in this version, so convert or retype that document, or
  keep it out of the folder, and re-run the scan.
- **An older page was picked as current**: the probable-current pick
  is a guess by date. Name the folder that should win in
  `authoritative_sources` in `.ghostdocs.json` and re-run.

## Your responsibility

Only run GhostDocs on documents you have the right to process, for
example your own business documents or a client's documents they have
asked you to prepare. Prepared for Ghost Developer Studio, October
2026. Pricing and any public release are not decided yet.

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
