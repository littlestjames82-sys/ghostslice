# GhostLedger
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostledger/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostledger/actions/workflows/ci.yml/actions)

**The books for agent work: what it cost, per project, per model, per agent, per day.**

GhostSlice estimates tokens before a run, GhostProxy sees tokens in
flight, and GhostBench measures tokens on proof tasks. None of them
answer the end-of-day question: what did I spend today, where did the
estimate and the actual diverge, and did an agent quietly burn 3x
what the slice said it should? GhostLedger ingests all three sources
plus manual entries into one local ledger and reports totals that
can be checked.

By Ghost Developer Studio. MIT licensed. **Zero dependencies**
(Python standard library only), **local-first**: no network calls,
no telemetry, ever. Ledger never approves, blocks, or dispatches
anything; Agent Seatbelt still governs what an agent does.

> Build status: v0.1. The commands, entry shape, and report format
> in this README describe the shipped core (`src/ghostledger/`).
> Test results and known limits are recorded honestly in
> `REPORT_B.md` (Agent B) and `IMPLEMENTATION_A.md` (core).

## Contents

- [Install](#install) and [Quickstart](#quickstart): get a first
  entry booked and a first summary printed.
- [Common workflows](#common-workflows): day ranges, one project,
  JSON for scripting, grouping the printed summary.
- [The loop warning](#the-loop-warning): what the 3x flag means,
  and what it does not mean.
- [Checking the books: `verify`](#checking-the-books-verify): the
  read-only audit that re-derives every booked entry.
- [Costs are estimates, always labelled](#costs-are-estimates-always-labelled):
  the price table, and why an unknown model is never shown as $0.
- [Reading the numbers](#reading-the-numbers): how to interpret a
  summary or report without fooling yourself.
- [Ledger entry format](#ledger-entry-format),
  [What each import reads](#what-each-import-reads),
  [Secrets discipline](#secrets-discipline),
  [Commands](#commands), and [Report format](#report-format):
  the reference sections.
- [Troubleshooting](#troubleshooting): exit codes, duplicates,
  unknown models, and the other surprises, explained.
- [Verification bar](#verification-bar-from-planmd) and
  [Out of scope for v0.1](#out-of-scope-for-v01): what is checked,
  and what Ledger deliberately does not do.

## The hard rules, up front

These are not settings. They are the design, and every section
below follows from them:

1. **Local books only.** One local ledger file, no network calls,
   no telemetry, no accounts, no cloud sync, ever. GhostLedger
   reads the files you point it at and writes only its own ledger
   and reports.
2. **Estimates and actuals are never blended silently.** Every
   dollar figure is an estimate from a local dated price table and
   is labelled as one. Estimate-vs-actual figures compare only the
   entries that carry an estimate. An entry whose model is not in
   the table books cost as unknown (`null`), never as $0 and never
   at a guessed rate.
3. **A warning is not a verdict.** An actual over 3x its estimate
   is flagged for a human to look at. Ledger never approves,
   blocks, throttles, or dispatches anything; acting stays with
   the human and Agent Seatbelt.

## Install

From a checkout, no install needed:

```bash
cd ghostledger
PYTHONPATH=src python3 -m ghostledger --help
```

Or install it (still zero dependencies):

```bash
pip install .
ghostledger --help
```

Requires Python 3.10 or newer.

## Quickstart

The examples below write `ghostledger` for brevity. If you run
from a checkout without installing, prefix each command with
`PYTHONPATH=src python3 -m` instead, for example
`PYTHONPATH=src python3 -m ghostledger summary`. Both forms take
exactly the same arguments. Every subcommand also has its own
`--help` (try `ghostledger add --help`) with per-flag explanations,
worked examples, and the exit-code list.

```bash
# Book a manual entry (cost estimated from the local price table)
ghostledger add --project ghostbus --model claude-sonnet \
  --agent builder-a --task "review pass" \
  --input-tokens 10000 --output-tokens 2000 --estimated-tokens 12000

# Import what the other Ghost tools already recorded
ghostledger import --slice-history ~/my-project/.ghostslice-history.jsonl
ghostledger import --proxy-report proxy-report.json
ghostledger import --bench-report bench-report.json
ghostledger import --source-file mystery.json   # auto-detects the shape

# Ask the end-of-day question
ghostledger summary
ghostledger summary --since 2026-10-01 --json
ghostledger report --out-dir ./ledger-out       # ledger-report.json + LEDGER.md

# Audit the books themselves (read-only)
ghostledger verify
```

What the first two commands print (the entry id and the ledger
path will differ on your machine; the cost is the hand-check from
the verification bar below: 10,000 in / 2,000 out on claude-sonnet
at $3/$15 per Mtok):

```text
$ ghostledger add --project ghostbus --model claude-sonnet \
    --agent builder-a --task "review pass" \
    --input-tokens 10000 --output-tokens 2000 --estimated-tokens 12000
added entry <id> to ./.ghostledger.jsonl

$ ghostledger summary
ghostledger: 1 entries, 12,000 total tokens, $0.0600 estimated cost
  Costs are ESTIMATES from a local dated price table (as of 2026-10-12), never billed amounts.
  estimate vs actual (entries with an estimate only): estimated 12,000 vs actual 12,000 (ratio 1.0)
  ghostbus: 1 entries, 12,000 tokens, $0.0600 est.
```

The ledger file is `./.ghostledger.jsonl` by default. Override it
with the global `--ledger PATH` flag or the `GHOSTLEDGER_FILE`
environment variable. **Global flags go before the subcommand**:
`ghostledger --ledger ./books.jsonl summary`, not
`ghostledger summary --ledger ./books.jsonl` (the second form is
an error, because `--ledger` is not a `summary` flag). Imports are
idempotent: re-importing the same file adds zero entries, never
double-books.

Exit codes: `0` ok, `1` loop warning present (`report`/`summary`)
or audit problems found (`verify`), `2` error. Exit `1` is the
tool doing its job (something crossed 3x, or the audit found a
problem, and deserves a look), not a failure; see
[Troubleshooting](#troubleshooting).

## Common workflows

```bash
# Just today, or a date range (both ends inclusive, on the entry's day)
ghostledger summary --since 2026-10-14 --until 2026-10-14
ghostledger summary --since 2026-10-01

# One project only
ghostledger summary --project ghostbus
ghostledger report --project ghostbus --out-dir ./ghostbus-books

# Group the printed summary differently (the JSON report always
# carries all four groupings; --by only picks the printed one)
ghostledger report --by day
ghostledger report --by agent --out-dir ./ledger-out

# JSON for scripting (summary --json prints and writes no files;
# report --json does the same instead of writing its two files)
ghostledger summary --json | python3 -m json.tool | head -n 40

# A different ledger file, and a different price table
ghostledger --ledger ~/books/october.jsonl summary
ghostledger --prices ~/my-prices.json summary

# The same ledger for a whole shell session
export GHOSTLEDGER_FILE=~/books/october.jsonl
ghostledger summary

# Audit the books themselves before trusting a report (read-only)
ghostledger verify
```

A runnable five-minute demo with sample inputs for all three
source tools lives in [`examples/`](examples/README.md): three
imports, one manual entry that trips the loop warning on purpose,
and a report to read.

## The loop warning

When an entry's `estimated_tokens > 0` and its actual
`total_tokens > 3 * estimated_tokens` (strictly greater), the entry
is flagged `loop_warning: true`, its ratio is shown, and it appears
in a dedicated Warnings section in every report and summary, which
then exit `1`. An entry at exactly 3.0x or below is not flagged.

**3x is a warning, not a verdict.** Legitimate retries happen. The
copy says "exceeded 3x its estimate", never that an agent looped as
a proven fact. Ledger reports the warning; acting on it stays with
the human and Seatbelt.

## Checking the books: `verify`

Reports are only worth trusting if the ledger underneath them
re-derives cleanly, so `ghostledger verify` audits the ledger file
itself, line by line, and modifies nothing. For every entry it
recomputes the content-hash `id` from the core fields, `day` from
`at`, `total_tokens` from input + output, and `ratio` / the 3x
`loop_warning` from total vs estimate (a consistently booked 3.6x
warning entry verifies clean: verify checks the books, not the
warning). It also flags malformed lines (which the report path
skips silently, an audit must count), duplicate ids, missing
fields, negative or non-integer token counts, and any
credential-named field, naming the key only, never its value.

Costs are re-derived only for entries booked under the *same*
price-table date as the table in hand. Entries booked under a
different date are counted in the output as not re-checked: never
silently passed, and never repriced, because rewriting booked
history would break the ledger's append-only honesty. Exit `0`
when no problems are found, `1` when any problem is found, `2`
when the ledger file does not exist. The `examples/` sample
history uses short illustrative ids (`led-001`, ...) instead of
real content hashes, so `verify` flags every sample entry's id;
it is a format example, not a booked ledger.

## Costs are estimates, always labelled

Every dollar figure is computed from a **local, dated price table**
(`prices.json`, same shape as GhostSlice's: `as_of`, `models[]` with
`input_per_mtok_usd` / `output_per_mtok_usd`). Resolution order:
`--prices PATH`, `GHOSTLEDGER_PRICES`, a sibling GhostSlice
checkout's table, then the bundled snapshot (as of 2026-10-12 at
build time). Every report carries the line:

> Costs are ESTIMATES from a local dated price table (as of
> 2026-10-12), never billed amounts.

These are **not live prices and not billed amounts**. Real bills
differ. An entry whose model is not in the table gets
`cost_estimate_usd: null` and the model is listed under
`unknown_models` in every report: unknown is stated, never guessed,
and never shown as $0. A model listed at a zero rate (local models)
is genuinely $0.00, which is a different thing and books as 0.0.
Model labels are matched to the table case-insensitively after an
exact match, and stored stripped of surrounding whitespace, so
`Claude-Sonnet` books the claude-sonnet estimate instead of a
false "unknown"; a genuinely unlisted model still books null.

Token counts are counts: a negative count is invalid evidence and
is never booked. `add` with a negative count exits `2` and writes
nothing; an imported record with a negative booked count is
counted as skipped (a negative `before_tokens` reference is simply
dropped from the note).

## Reading the numbers

A summary or report is only useful if its limits stay visible.
Keep these five points in mind when you read one:

- **The headline cost sums only what could be costed.** The totals
  bucket counts `entries_with_cost` next to `cost_estimate_usd`.
  If some entries used a model that is not in the price table,
  they contribute tokens but no dollars, and their models are
  named under `unknown_models`. The headline is a floor for the
  known part, not a total spend figure, whenever that list is
  non-empty. In the printed text summary an all-unknown ledger
  still prints `$0.0000 estimated cost` on the headline line; the
  `unknown models` line right below it, and `entries_with_cost`
  in the JSON, are what tell you that $0.0000 means "nothing could
  be costed", not "it was free". A zero-rate `local` entry is the
  opposite case: genuinely $0.00, and it does count in
  `entries_with_cost`.
- **The ratio compares like with like.** `estimate_vs_actual_ratio`
  is the summed actual of *only the entries that carry an
  estimate*, divided by their summed estimates, and
  `estimate_delta_tokens` is that same pair's difference. Entries
  with no estimate count in `total_tokens` but never inflate the
  ratio. When no entry carries an estimate the ratio is `null`
  (printed as `None` in the text summary), which means "no
  comparison was possible", not "perfect accuracy".
- **A ratio near 1.0 is not automatically good news.** Bench
  entries estimate `full_tokens` against a sliced actual, Slice
  entries estimate themselves, and manual entries estimate
  whatever you typed. Check `by_project` / the entry `source`
  before celebrating or worrying; the mix is shown per group
  precisely so it is not averaged away.
- **Loop warnings are per entry, not per project.** One flagged
  entry makes `summary` and `report` exit `1` and lists the entry,
  its ratio, and its estimate. A project can look calm in the
  grouped table and still hold the one runaway entry; the warnings
  section is the place to look first.
- **Dates group by the entry's `day`.** That is the date part of
  its `at` timestamp as booked, not the day you imported it
  (importers carry the source record's timestamp where the source
  provides one), and `--since` / `--until` filter on that same
  day, inclusively.

## Ledger entry format

One JSON object per line in `.ghostledger.jsonl`:

| Field | Meaning |
|---|---|
| `id` | Content hash of the entry's core fields; dedupe key on import/add |
| `at` / `day` | Timestamp (ISO) and its `YYYY-MM-DD` day, the by-day grouping key |
| `project` / `model` / `agent` | Grouping labels; missing model/agent book as null and group under `unknown` |
| `source` | `manual`, `slice`, `proxy`, or `bench` |
| `kind` / `task` | What the entry was (export, request, bench-task, run, ...) and its label |
| `input_tokens` / `output_tokens` / `total_tokens` | Booked counts. `--total-tokens` alone on `add` books as input so totals reconcile |
| `estimated_tokens` | The pre-run estimate the actual is compared against, or null |
| `ratio` | `total / estimated`, or null when there is no estimate |
| `loop_warning` / `loop_threshold` | The 3x flag and the threshold applied (3.0 in v0.1) |
| `cost_estimate_usd` | Estimated cost from the local table, or null when the model is unknown |
| `price_table_as_of` | Date of the price table the cost came from |
| `source_ref` | For imports: source file name + line/task index. No file bodies, ever |
| `note` | Free text; Slice imports keep `before_tokens=<n>` here as reference data |

## What each import reads

- **Slice history** (`.ghostslice-history.jsonl`): one entry per
  valid line. Booked input = `after_tokens` (what was actually
  sent), estimated = `after_tokens`, `before_tokens` kept in the
  note. Lines that are not JSON or carry no `after_tokens` are
  counted as skipped in the import output, never silently swallowed
  and never fatal to the good lines.
- **Proxy report** (GhostProxy's report JSON): records from the
  `requests`/`entries`/`records`/`calls` list, a bare list, or a
  single request object. Token keys are read tolerantly
  (`input_tokens`/`prompt_tokens`/`tokens_in`,
  `output_tokens`/`completion_tokens`/`tokens_out`).
- **Bench report** (`bench-report.json`): one entry per task in
  `tasks[]`. The booked actual is the task's sliced/proxied tokens
  when present - read from the top-level token fields first, then
  from `variants{}` (priority: `sliced`, then `proxied`,
  `verified`, `recalled`; a `variants.full.tokens` supplies the
  full count when `full_tokens` is absent) - and the estimate is
  `full_tokens` whenever a different actual was found, so a Bench
  entry shows the sliced-vs-full divergence ratio. A variant whose
  tokens are null, negative, or unparseable is treated as absent
  and the full count is the fallback actual. (Polish, Oct 14, 2026:
  this closes finding F2; the v0.1 importer booked actual as
  `full_tokens` because it never looked inside `variants{}`. See
  `POLISH.md`.)
- **`--source-file`** auto-detects: `.jsonl` is Slice history, JSON
  with `tasks[]` is Bench, anything else is treated as Proxy.

## Secrets discipline

Ledger files never contain API keys by construction. Importers drop
any field whose name suggests a credential (`api_key`, `auth`,
`secret`, `password`, `credential`, `bearer`, `session`, `cookie`,
`private_key`) before an entry is built. Token *counts*
(`*_tokens`) are numbers, not credentials, and are the only
token-named fields kept. Prompts, completions, and file bodies are
never stored: counts and labels only. The test suite plants a
labelled fake credential canary in a Proxy-shaped fixture and proves
it appears nowhere in the ledger after import.

## Commands

One line per command; `ghostledger <command> --help` gives the
full per-flag version of each row, and `ghostledger --help` lists
worked examples and the exit codes.

| Command | What it does |
|---|---|
| `ghostledger [--ledger PATH] [--prices PATH] add --project P [--model M] [--agent A] [--task T] [--kind K] [--input-tokens N] [--output-tokens N] [--total-tokens N] [--estimated-tokens N] [--at ISO] [--note TEXT]` | Append one manual entry. Prints the loop warning and the unknown-model note when they apply. Adding the identical entry twice does not double-book |
| `ghostledger import [--slice-history F ...] [--proxy-report F ...] [--bench-report F ...] [--source-file F ...] [--project P]` | Import from the other Ghost tools. Per file prints parsed / added / skipped. With nothing to import, exits 2 |
| `ghostledger report [--by project\|model\|agent\|day] [--since D] [--until D] [--project P] [--out-dir DIR] [--json]` | Writes `ledger-report.json` + `LEDGER.md` (all four groupings, estimate-vs-actual per group, warnings, unknown models, price date) and prints the summary. `--json` prints the summary JSON instead and writes no files. Exits 1 when a loop warning is present |
| `ghostledger summary [--since D] [--until D] [--project P] [--json]` | Printed quick view: entries, total tokens, estimated cost, estimate-vs-actual headline, warning count. Writes no files. Exits 1 when a loop warning is present |
| `ghostledger verify [--json]` | Audit the ledger file read-only: re-derive ids, totals, ratios, loop flags, and same-price-date costs per entry; flag malformed lines, duplicate ids, missing fields, bad counts, and credential-named fields. Writes nothing. Exits 1 when a problem is found, 2 when the ledger file is missing |
| `ghostledger --version` | Print the version |

`--since`/`--until` filter inclusively on the entry's day;
`--project` filters to one project.

## Report format

`ledger-report.json` (and the `summary --json` / `report --json`
output) carries: `tool`, `version`, `totals`, grouped totals under
`by_project`, `by_model`, `by_agent`, and `by_day`, `loop_warnings`
(the full flagged entries), `loop_threshold`, `unknown_models`,
`price_table_as_of`, `price_table_source`, and the `cost_note`
above. Each totals/group bucket has `entries`, `input_tokens`,
`output_tokens`, `total_tokens`, `estimated_tokens`,
`entries_with_estimate`, `actual_tokens_with_estimate`,
`estimate_delta_tokens`, `estimate_vs_actual_ratio`,
`cost_estimate_usd`, `entries_with_cost`, and `loop_warnings`.
The estimate-vs-actual figures compare only the entries that carry
an estimate: `estimate_vs_actual_ratio` is
`actual_tokens_with_estimate / estimated_tokens`, and
`estimate_delta_tokens` is their difference. Entries with no
estimate count in `total_tokens` but never inflate the ratio
(polish, Oct 14, 2026; the v0.1 formula divided the grand total
by the estimated sum and overstated divergence whenever coverage
was partial). Note the honest split in
the grouped cost column: a bucket's `cost_estimate_usd` sums only
the entries that have a cost (`entries_with_cost`), so a bucket
with unknown-model entries shows the known part, with the unknown
count visible in the same bucket.

Token counts from different sources are not perfectly comparable
(Slice estimates vs Proxy counts vs Bench static counts vs manual
entries). Every entry and group keeps its source visible so the
mix is shown, not averaged away.

Two labelled SAMPLE files in `examples/` show the formats:
`sample-history.jsonl` (8 ledger entries covering all four sources,
one planted 3.6x loop warning, one 2.9x under-threshold entry, one
unknown-model entry) and `sample-report.json` / `sample-report.md`
recomputed from it. They are format examples, never measured spend.

## Troubleshooting

| Symptom | What it means, and what to do |
|---|---|
| `summary` or `report` exits `1` | A loop warning is present. This is the warning working, not an error: read the `WARNING` lines (or the `loop_warnings` list in `--json`), find the entry, and decide yourself whether the overrun was a legitimate retry. Nothing was blocked. |
| A command exits `2` | A real error: a bad argument, an unreadable import file, a negative token count on `add`, or `import` with no source file. The message on stderr names the cause, and nothing was booked or written for that invocation. |
| `ghostledger: error: unrecognized arguments: --ledger ...` | Global flags were placed after the subcommand. Move them before it: `ghostledger --ledger PATH summary`. The same applies to `--prices`. |
| `duplicate entry ... not re-booked` on `add`, or `0 added` on re-import | The identical entry is already in the ledger (same content-hash `id`). This is dedupe working as designed; the books did not change. To book a genuinely separate run, change something real about it, such as its `--at` timestamp or `--task`. |
| `note: model '...' not in price table ...; cost unknown, not guessed` | The model has no row in the price table in use, so the entry books tokens with `cost_estimate_usd: null` and appears under `unknown_models` in reports. Check the spelling first: matching is case-insensitive, so a miss usually means the model is genuinely unlisted, not mistyped by case. To cost *future* entries for it, add the model to a local `prices.json` and pass that file with `--prices`. Entries already booked keep the cost they were booked with; Ledger does not silently reprice its own history. |
| Import prints `skipped` counts above zero | Those records could not be booked faithfully (not JSON, no usable token count, or a negative count) and were counted out loud instead of being silently swallowed or guessed at. The good records in the same file were still booked. |
| `error: nothing to import ...` | `import` was run with no `--slice-history`, `--proxy-report`, `--bench-report`, or `--source-file`. Give it at least one source file; each flag may be repeated for several files. |
| Summary shows `ratio None` / a group shows `n/a` | No entry in scope carries an estimate, so no estimate-vs-actual comparison exists. Book estimates (`--estimated-tokens` on `add`, or a source that provides them) to get a ratio. See [Reading the numbers](#reading-the-numbers). |
| Totals look too low for the files imported | Check for a filter left in the command (`--since`, `--until`, `--project`), and check which ledger file is in use (`--ledger`, `GHOSTLEDGER_FILE`, or the default `./.ghostledger.jsonl` in the current directory). Running from a different directory reads a different default ledger. |

## Verification bar (from PLAN.md)

- Manual round-trip: an `add` with a known model hand-checks
  against the dated table (10,000 in / 2,000 out on claude-sonnet
  at $3/$15 per Mtok = $0.06 estimated).
- Slice import: entry count equals valid history lines, totals
  equal the sum of `after_tokens`, re-import adds zero.
- Loop test: 3.1x is flagged and listed; 2.9x is not.
- Unknown model: cost reports as unknown (null), never $0-as-fact.
- No-secrets test: a Proxy-shaped fixture carrying an `api_key`
  field imports with that field absent everywhere in the ledger.

## Out of scope for v0.1

Calling any model or billing API, fetching live prices (no network
at all), blocking or throttling a runaway agent, storing prompts or
completions, accounts, cloud sync, telemetry, dashboards (a panel
in GhostSlice's dashboard is a v0.2 candidate once the numbers are
trusted), and rewriting Slice history, Proxy logs, or Bench
reports. Ledger reads them; it owns only `.ghostledger.jsonl` and
its own reports.

## Layout

```
src/ghostledger/    the core (Agent A): entry model + IO, price
                    table, Slice/Proxy/Bench importers, reports, CLI,
                    and the read-only ledger audit (verify)
tests/              format + fixture tests (run without the core) and
                    black-box CLI tests for add / import / report /
                    summary, loop boundaries, and the canary drop
examples/
  sample-history.jsonl   SAMPLE ledger, 8 entries, all four sources
  sample-report.json     SAMPLE report recomputed from the history
  sample-report.md       the same report in the LEDGER.md shape
  inputs/                one importable file per source tool
PLAN.md             the v0.1 plan this build follows
REPORT_B.md         tests/docs build report: honest pass/fail + findings
POLISH.md           Oct 14, 2026 polish round: audit, F2 fix, passes
```

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
