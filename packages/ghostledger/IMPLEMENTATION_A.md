# GhostLedger v0.1 - Implementation A (core)

Agent A deliverable, Oct 14, 2026. Agent B owns tests/README/examples (not written here).

## Files owned and delivered
- `PLAN.md` - full plan in GhostSlice format (problem, stack position, concrete pairing, MVP, out of scope, estimate, pricing draft NOT decided, verification bar, risks, next gate).
- `pyproject.toml` - ghostledger 0.1.0, MIT, Python >=3.10, zero dependencies, console script `ghostledger = ghostledger.cli:main`, bundled `prices.json` as package data.
- `src/ghostledger/__init__.py` - version 0.1.0, `LOOP_THRESHOLD = 3.0`.
- `src/ghostledger/__main__.py` - `python -m ghostledger`.
- `src/ghostledger/prices.py` - local dated price table. Resolution: explicit path, `GHOSTLEDGER_PRICES`, sibling GhostSlice checkout / installed ghostslice, bundled snapshot, minimal built-in fallback. `estimate_cost_usd()` returns None for unknown models (stated, never guessed).
- `src/ghostledger/prices.json` - bundled dated snapshot copied from GhostSlice's table (as of 2026-10-12, labelled a snapshot inside the file).
- `src/ghostledger/ledger.py` - entry model and ledger IO:
  - Entry: id (sha256 of core fields), at/day, project, model, agent, source, kind, task, input/output/total/estimated tokens, ratio, loop_warning, cost_estimate_usd, price_table_as_of, note, source_ref.
  - Secret stripping: recursive drop of credential-named keys (api_key/auth/secret/password/credential/bearer/session/cookie/private_key); `*_tokens` count fields explicitly kept.
  - Loop warning: total > 3.0 x estimated (estimated > 0).
  - Append with dedupe by entry id (re-import never double-books), load, date/project filtering, grouping by project/model/agent/day, estimate-vs-actual (sum, delta, ratio) per group, unknown-model list.
- `src/ghostledger/ingest.py` - tolerant importers, each returns (entries, skipped):
  - Slice history `.jsonl`: after_tokens = actual input, estimated = after_tokens, before_tokens kept in note. Malformed lines counted skipped.
  - Bench `bench-report.json`: tasks[]; sliced/proxied tokens as actual when present else full_tokens; full_tokens as estimate when a sliced actual exists; run_id in note.
  - Proxy report JSON: dict with requests/entries/records/calls list, a bare list, or a single request object; tolerant token key aliases (input/prompt, output/completion).
  - `import_source_file`: auto-detect by suffix/shape (.jsonl = slice, tasks[] = bench, else proxy).
- `src/ghostledger/report.py` - `ledger-report.json` + `LEDGER.md` (totals, all four groupings, warnings section, unknown models, price date/source, estimate disclaimer on every report).
- `src/ghostledger/cli.py` - commands below.

## CLI
- `add --project P [--model M] [--agent A] [--task T] [--input-tokens N] [--output-tokens N] [--total-tokens N] [--estimated-tokens N] [--at ISO] [--note TEXT]` - appends one manual entry; prints loop warning and unknown-model note when applicable.
- `import [--slice-history F ...] [--proxy-report F ...] [--bench-report F ...] [--source-file F ...] [--project P]` - parsed/added/skipped per file.
- `report [--by project|model|agent|day] [--since D] [--until D] [--project P] [--out-dir DIR] [--json]` - writes ledger-report.json + LEDGER.md and prints a summary; with `--json` it prints the full report JSON instead and writes no files.
- `summary [--since D] [--until D] [--project P] [--json]` - printed quick view, no files.
- Global: `--ledger` (else $GHOSTLEDGER_FILE, else ./.ghostledger.jsonl), `--prices` (else $GHOSTLEDGER_PRICES).
- Exit codes: 0 ok, 1 loop warning present (report/summary), 2 error.

## Gates honoured
Stdlib only (argparse, json, hashlib, re, os, datetime, pathlib). Local only, no network calls anywhere. No push, no publish, no announcements, no spend. API keys never stored or logged: importers strip credential-named fields before entry construction, verified by smoke test (grep for api_key in ledger = 0 on fixtures without keys; stripping is structural in `strip_secrets`). All dollar figures labelled estimates from the local dated table, never billed amounts. No other tool's folder touched.

## Smoke test performed (Agent A, /tmp/ledger-smoke, PYTHONPATH=src)
- `add` GhostBus / claude-sonnet / 1,000,000 in + 100,000 out: cost $4.5000, hand-checks against table ($3/M in + $15/M out = $3.00 + $1.50). Correct.
- `add` at 31,000 actual vs 10,000 estimated: ratio 3.1, loop WARNING printed, summary/report exit 1. Correct.
- `import --slice-history` on the real GhostSlice `.ghostslice-history.jsonl`: 21 parsed, 21 added, 0 skipped; identical re-import: 0 added (dedupe works).
- `import --bench-report` on GhostBench sample run A: 2 tasks parsed, 2 added.
- `summary`: 25 entries, 2,720,855 total tokens, $4.5930 est.; `report` wrote ledger-report.json + LEDGER.md with all four groupings.

## Known limits / notes for Agent B and parent verification
- Bench sample tasks carry no sliced-token field distinct from full_tokens, so their entries book estimated = actual (no false loop warnings by design).
- Slice history carries no model, so those entries have cost null / unknown rather than $0-as-fact; group tables render their cost contribution as 0.0000 with entries_with_cost counting only known-model entries in JSON.
- Proxy report shape is young; importer is deliberately tolerant and counts skipped records visibly.
- Tests, README, and examples are Agent B's surface and were not written here.
