# Expected output for the examples (what a correct run looks like)

These are **expectations written from the fixtures**, not captured tool
output. If a real run disagrees, the run (or this file) is wrong and the
disagreement is worth reporting.

Before you run: run all commands below from the repo root. If
`ghostreplay` is not installed, prefix each command with
`PYTHONPATH=src python3 -m` instead (for example
`PYTHONPATH=src python3 -m ghostreplay analyse ...`), or just run
`sh examples/run_demo.sh` for the first example. Report and proposal
output goes to `/tmp`; note that `analyse` also appends one record to
the sample project's trend ledger
(`examples/sample_project/.ghostreplay-history.jsonl`), as it does
for any project. Token figures are estimates throughout.

How to check a run: open the `REPLAY.md` (or `PROPOSAL.md`) the
command wrote and compare its findings, counts, and token figures
against the bullets under that example. Console output alone is only
a summary; the report files are the result.

## Analyse the planted-waste transcript

```bash
ghostreplay analyse examples/sample_project examples/transcripts/planted_waste_1.jsonl \
    --bundle examples/sample_bundle --out /tmp/replay-demo
```

A correct report in `/tmp/replay-demo/` (REPLAY.md + replay-report.json)
finds exactly the planted waste:

- **Re-reads**: `src/hot.py`, Read in **5 distinct turns** (extra
  reads: 4). Its manifest entry in
  `examples/sample_bundle/manifest.json` is 67 estimated sliced tokens,
  so the re-read waste is 4 x 67 = **268** estimated tokens under the
  report convention (distinct turns - 1) x sliced tokens each.
- **Not referenced in transcript**: `src/legacy.py`, at **86** estimated
  tokens (its manifest sliced_tokens). The report uses the qualified
  label "not referenced in transcript", never "not needed".
- `src/app.py` and `src/util.py` appear as referenced, with no findings.

## Propose from zero waste

```bash
ghostreplay propose examples/sample_project \
    tests/fixtures/sessions/zero_waste_1.jsonl \
    tests/fixtures/sessions/zero_waste_2.jsonl \
    tests/fixtures/sessions/zero_waste_3.jsonl \
    --bundle examples/sample_bundle --out /tmp/replay-prop
```

(The examples folder ships one zero-waste transcript; the test fixtures
carry all three, so the command above uses the fixture copies. Three
sessions are needed because a proposal requires at least 3 by
default; with fewer, the status is `insufficient-sessions` and no
changes are proposed.)

Expected: `ghostreplay-proposal.json` with an **empty** changes list. The session
referenced every bundle file exactly once, so any proposed "saving"
would be invented.

## Propose from planted waste (all 3 fixture sessions)

Expected: at least one change citing `src/legacy.py` with evidence in
the form "present in 3/3 bundles, referenced in 0/3" plus its per-session
token cost, and a re-read driven suggestion for `src/hot.py`. The
proposal changes nothing on disk until `ghostreplay apply` is run and
answered with an explicit yes.
