# Examples

All files are local, illustrative, and free to re-run. No network,
no spend. The samples are format examples, never measured spend.

Two kinds of file live here, and they answer different questions:

- **Samples** (`sample-history.jsonl`, `sample-report.json`,
  `sample-report.md`) show the *finished shapes*: what a ledger
  file looks like, and what the report computed from it looks
  like. Read these to learn the formats.
- **Inputs** (`inputs/`) are *starting points*: one real-shaped
  file per source tool, ready to feed to `ghostledger import` in
  the demo below. Run the demo to learn the workflow.

| File | What it is |
|---|---|
| `sample-history.jsonl` | A ledger in the core entry shape: 8 entries covering all four sources (slice, proxy, bench, manual), 2 projects, 3 models, 3 agents, 2 days. Includes the planted teaching cases: led-007 at 3.6x its estimate (loop warning), led-008 at 2.9x (under threshold, not warned) on an unlisted `mystery-model` (cost null, unknown, never $0-as-fact), and zero-rate `local` entries whose $0.00 cost is genuine. |
| `sample-report.json` | The report for that history, in the core `summarise()` shape, recomputed from the history alone. Carries `"sample": true` and a sample note. |
| `sample-report.md` | The same report in the `LEDGER.md` shape the core report writer produces. |
| `inputs/slice-history.jsonl` | A GhostSlice `.ghostslice-history.jsonl` in the real shape (at / kind / before_tokens / after_tokens / saved_tokens / estimator). |
| `inputs/proxy-report.json` | A GhostProxy report in the real shape: top-level `requests` count plus `entries[]` with `tokens_in` / `tokens_out` and slicable-context totals kept separate. |
| `inputs/bench-report.json` | A minimal GhostBench `bench-report.json`: `tasks[]` with `full_tokens` and a `variants` block, plus corpus totals. |

## Five-minute demo (all local)

Run from the repo root. The demo uses the no-install form
(`PYTHONPATH=src python3 -m ghostledger`); if you installed the
package, plain `ghostledger` works identically.

```bash
cd ghostledger

# Start an empty ledger in /tmp and import one file per source
export GHOSTLEDGER_FILE=/tmp/demo-books.jsonl
rm -f "$GHOSTLEDGER_FILE"
PYTHONPATH=src python3 -m ghostledger import \
  --slice-history examples/inputs/slice-history.jsonl
PYTHONPATH=src python3 -m ghostledger import \
  --proxy-report examples/inputs/proxy-report.json
PYTHONPATH=src python3 -m ghostledger import \
  --bench-report examples/inputs/bench-report.json

# Add a manual entry that trips the loop warning (3.6x)
PYTHONPATH=src python3 -m ghostledger add --project demo-shop \
  --model claude-sonnet --agent loopy-agent \
  --task "retry-heavy refactor attempt" \
  --input-tokens 3400 --output-tokens 200 --estimated-tokens 1000 \
  --at 2026-10-14T10:47:00+00:00

# Summary exits 1 while a loop warning is present (warning, not error)
PYTHONPATH=src python3 -m ghostledger summary
PYTHONPATH=src python3 -m ghostledger report --out-dir /tmp/demo-report
cat /tmp/demo-report/LEDGER.md
```

What success looks like, step by step:

- Each import prints `2 entries parsed, 2 added, 0 skipped` for
  its file, then an `import complete` line. After the three
  imports the ledger holds 6 entries.
- The `add` prints `added entry ...` and then the warning line
  `WARNING: total 3600 exceeded 3x estimate 1000 (ratio 3.6)`,
  because 3,600 actual tokens against a 1,000 estimate is 3.6x.
  The add itself still exits 0: the warning is raised by
  `summary` / `report`, below.
- `summary` prints 7 entries and 79,570 total tokens, lists the
  same entry under `WARNING exceeded 3x estimate`, and **exits
  1**. That exit code is expected here, it is how scripts can
  notice a warning; it does not mean the command failed.
- `report` also exits 1, and writes both files to
  `/tmp/demo-report/`: `ledger-report.json` (the machine-readable
  report) and `LEDGER.md` (the same numbers as Markdown tables,
  with a dedicated loop-warnings section at the end).
- Clean up with `rm -f /tmp/demo-books.jsonl` and
  `rm -rf /tmp/demo-report` when you are done. Nothing outside
  `/tmp` was touched.

What to notice in the demo output:

- Slice entries book `after_tokens` as the actual (45,770 for the
  big export), with `before_tokens=129555` kept in the note.
- Proxy entries book `tokens_in + tokens_out` per request.
- Bench tasks book their `variants{}.sliced.tokens` as the actual
  (1000 per task here) with `full_tokens` (4200) as the estimate,
  since the Oct 14, 2026 polish closed finding F2. See `POLISH.md`
  in the repo root. The demo total is 79,570 tokens (it was 85,970
  under the v0.1 full-tokens booking).
- The summary headline separates estimated cost from tokens and
  names the price table date; costs are estimates, never bills.
- Re-running any import line adds 0 entries: imports never
  double-book.

## Try next

With the demo ledger still in place (`GHOSTLEDGER_FILE` still
exported):

```bash
# Group the printed report by day instead of by project
PYTHONPATH=src python3 -m ghostledger report --by day --out-dir /tmp/demo-report

# Machine-readable summary for a script or a jq pipeline
PYTHONPATH=src python3 -m ghostledger summary --json

# Filter to one project, or to the demo day only
PYTHONPATH=src python3 -m ghostledger summary --project demo-shop
PYTHONPATH=src python3 -m ghostledger summary --since 2026-10-14 --until 2026-10-14

# Book an entry on an unlisted model and watch it report honestly:
# the add prints "cost unknown, not guessed" and the summary lists
# the model under "unknown models (no cost estimate)"
PYTHONPATH=src python3 -m ghostledger add --project demo-shop \
  --model mystery-model --input-tokens 1000 \
  --at 2026-10-14T12:00:00+00:00
PYTHONPATH=src python3 -m ghostledger summary
```

Then compare `sample-history.jsonl` with your demo ledger side by
side: same entry shape, and the samples plant the same teaching
cases (a 3.6x warning, a 2.9x near-miss, an unknown model) in
finished form.
