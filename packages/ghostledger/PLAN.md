# GhostLedger - Local Token and Cost Ledger for GhostSlice
Working name, prepared Oct 14, 2026. Wave 3 paired tool #15 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostLedger: plain job, plain name. It ledgers what agent work cost, in tokens and in estimated dollars.
- Checked against the family: sits next to GhostSlice, GhostProxy, and GhostBench the way a ledger sits next to the work itself. Treat as a working name until a name check runs at build gate, same as GhostSlice did Oct 12.
- Alternatives held in reserve: GhostCost (too narrow, tokens matter even at $0 on local models), GhostBurn (cute, unclear to a stranger).

## The problem
GhostSlice estimates tokens before a run, GhostProxy sees tokens in flight, and GhostBench measures tokens on proof tasks. None of them answer the question a solo developer asks at the end of the day:

- What did I spend today, per project, per model, per agent?
- Where did the estimate and the actual diverge?
- Did an agent loop, quietly burning 5x what the slice said it should?

Today that data is scattered: `.ghostslice-history.jsonl` lines in each project, Proxy logs, Bench report JSON, and mental arithmetic. There is no one local ledger, no estimate-vs-actual view, and no loop warning. Without it, cost control is vibes.

## Position in the Ghost stack
- GhostSlice governs what an agent READS and estimates what it will cost (scanner, AST slicer, token estimator, `.ghostslice-history.jsonl`).
- GhostProxy governs what is SENT in flight (local fail-open proxy, request ledger).
- GhostBench governs PROOF (same tasks, sliced vs full, published per-task results).
- GhostLedger governs the BOOKS: it ingests estimates and actuals from all three, plus manual entries, and reports totals that can be checked.
- Agent Seatbelt still governs what an agent DOES. Ledger never approves, blocks, or dispatches anything.

Story: Slice estimates -> Proxy / agent runs -> Ledger books it -> Bench proves it -> Ledger books that too.
No overlap: Slice history stays the export log, Proxy's ledger stays the request log, Bench reports stay per-run proof. Ledger is the consolidated, queryable copy.

## How it pairs with the suite, concretely
Reuses, does not rebuild:
- Slice history: reads any `.ghostslice-history.jsonl` (lines with `at`, `kind`, `before_tokens`, `after_tokens`, `saved_tokens`, optional `estimator`, `bundle`). An export line becomes a ledger entry: input tokens = `after_tokens` (what was actually sent), estimated tokens = `after_tokens`, full-project reference kept in `note` data as `before_tokens`. Ledger never rewrites Slice history.
- Proxy reports: reads GhostProxy local report JSON if present (a dict with a `requests`/`entries`/`records` list, or a single request object) using tolerant key lookup (`input_tokens`/`prompt_tokens`, `output_tokens`/`completion_tokens`, `model`, `agent`, `at`/`timestamp`). Missing fields are recorded as unknown, never invented.
- Bench reports: reads `bench-report.json` (`tasks[]` with `full_tokens` and sliced/proxied token fields, `project`, `task`, `model_for_cost_estimates`, `run_id`). Each task becomes one entry: actual = sliced/proxied tokens when present else `full_tokens`, estimated = `full_tokens` when a sliced actual exists.
- Price table: same local dated `prices.json` shape as GhostSlice (`as_of`, `models[]` with `input_per_mtok_usd` / `output_per_mtok_usd`). Resolution: `--prices` flag, `GHOSTLEDGER_PRICES` env, sibling GhostSlice checkout, bundled snapshot. Every cost figure is labelled an ESTIMATE from that dated table, never a billed amount, never a live price.
- Secrets discipline: importers drop any key whose name suggests a credential (`api_key`, `auth`, `secret`, `password`, `credential`, `bearer`, `session`, `cookie`) on sight. Token *counts* (`*_tokens`) are numbers, not credentials, and are the only token-named fields kept. Ledger files never contain API keys by construction.

Integration contract:
- Input: ledger file `.ghostledger.jsonl` (default in the working directory, override with `--ledger` or `GHOSTLEDGER_FILE`), plus any Slice history / Proxy report / Bench report paths given to `import`.
- Output: `ledger-report.json` + `LEDGER.md` from `report`, and printed totals from `summary`. Both are reproducible from the ledger file + price table date alone.
- Entry shape (one JSON object per line): `id`, `at`, `day`, `project`, `model`, `agent`, `source` (manual|slice|proxy|bench), `kind`, `task`, `input_tokens`, `output_tokens`, `total_tokens`, `estimated_tokens` (or null), `ratio` (actual/estimated or null), `loop_warning` (bool), `cost_estimate_usd` (or null when model unknown), `price_table_as_of`, `note`.

## MVP (v0.1) - local CLI first, dashboard panel later
Rationale: same as Slice v0.1. CLI proves the ledger on real repos in days. A panel in Slice's dashboard is v0.2 once the numbers are trusted.

1. Manual entry: `ghostledger add --project P [--model M] [--agent A] [--task "..."] [--input-tokens N] [--output-tokens N] [--total-tokens N] [--estimated-tokens N] [--at ISO] [--note "..."]`
   - Appends one entry to the ledger. Cost estimate computed from the local price table when the model is known; unknown model = cost null and stated, never guessed.
   - `--total-tokens` alone is split as input (output 0) unless input/output are also given, and that is stated in the entry note data.

2. Import: `ghostledger import [--slice-history PATH ...] [--proxy-report PATH ...] [--bench-report PATH ...] [--source-file PATH]`
   - `--source-file` auto-detects by shape: `.jsonl` = Slice history, JSON with `tasks[]` = Bench, JSON with `requests[]`/request fields = Proxy.
   - Import is idempotent by content hash: re-importing the same file does not double-book. Each entry keeps `source_ref` (file name + line/task index, no file bodies, no credentials).
   - Malformed lines/records are counted and reported as skipped, never silently swallowed and never fatal to the good records.

3. Loop warning (the headline check)
   - When `estimated_tokens > 0` and `total_tokens > 3 * estimated_tokens`, the entry is flagged `loop_warning: true`, its ratio is shown, and it appears in a dedicated Warnings section in every report and summary.
   - 3x is a warning, not a verdict: legitimate retries happen. Copy says "exceeded 3x its estimate", never "looped" as a proven fact.

4. Report: `ghostledger report [--by project|model|agent|day] [--since DATE] [--until DATE] [--project P] [--out-dir DIR] [--json]`
   - Writes `ledger-report.json` + `LEDGER.md`: grand totals, grouped totals for all four dimensions, estimate-vs-actual (sum, delta, ratio) per group, loop warnings, unknown-model list, price table date + source.
   - Every dollar figure carries the line: "Costs are ESTIMATES from a local dated price table (as of <date>), never billed amounts."

5. Summary: `ghostledger summary [--since DATE] [--until DATE] [--project P] [--json]`
   - Printed quick view: entries, total tokens, estimated cost, estimate-vs-actual headline, warning count. Same filters as report, no files written.

6. Price table handling
   - Bundled dated snapshot at `src/ghostledger/prices.json` (snapshot of Slice's table, as of 2026-10-12 at build time), labelled a snapshot in the file itself.
   - Unknown models are listed in reports so the user knows which entries carry no cost estimate and why.

## Out of scope for v0.1
- Calling any model API, any provider billing API, or fetching live prices. No network at all in v0.1.
- Blocking, throttling, or killing an agent runaway run. Ledger reports the 3x warning; action stays with the human and Seatbelt.
- Storing or logging API keys, prompts, completions, or file bodies. Counts and labels only.
- Accounts, cloud sync, telemetry, paid layer, dashboards.
- Rewriting Slice history, Proxy logs, or Bench reports. Ledger reads them; it owns only `.ghostledger.jsonl` and its own reports.

## Build estimate
- Entry model + ledger IO + prices: 1-2 days
- Slice / Proxy / Bench importers + dedupe: 2-3 days
- Grouping, estimate-vs-actual, loop warning, report + summary: 2 days
- Tests (planted 3x overrun, unknown model, malformed imports, re-import dedupe), README, demo on GhostBus history: 2 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team rollups / hosted history. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Manual round-trip: `add` an entry with a known model and token counts; `summary` cost must equal hand-computed input/output rates from the dated table.
- Slice import test: import the real GhostSlice `.ghostslice-history.jsonl`; entry count equals valid lines, totals equal the sum of `after_tokens`, re-import adds zero.
- Loop test: an entry at 3.1x its estimate is flagged and listed; an entry at 2.9x is not.
- Unknown-model test: an entry with an unlisted model reports cost as unknown, never $0-as-fact and never a guessed rate.
- No-secrets test: a Proxy-shaped fixture carrying an `api_key` field imports with that field absent everywhere in the ledger and reports.

## Risks / honest notes
- Proxy and Bench report shapes are young and may drift; importers are deliberately tolerant and count what they skipped. A skipped record is visible, not hidden.
- Token counts from different sources are not perfectly comparable (Slice estimates vs Proxy actuals). Reports label the source per entry and per group so the mix is visible, not averaged away.
- A 3x overrun is evidence worth a look, not proof of a loop. Copy must keep that line.
- Cost estimates are only as current as the local table's `as_of` date, which is printed on every report.

## Next gate
Ryan's go on: (1) GhostLedger as working name, (2) CLI-first with commands add / import / report / summary, (3) 3x estimate as the loop-warning threshold in v0.1, (4) Wave 3 build order among the ten tools.
