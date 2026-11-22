# *** SAMPLE REPORT - NOT A REAL RUN ***

This is sample material shipped with GhostBench to show the report shape. It is not evidence from a real bench run.
Sample note: SAMPLE format example only. Numbers are illustrative and were NOT produced by a bench run. Do not quote as results.

# GhostBench Report - adversarial

- Run: SAMPLE-run-a
- Tier: A | Suite: slice
- Verification level: static-analysis - static analysis only (no tests executed, no live agent run)
- Tool: ghostbench 0.1.0
- Corpus: adversarial v0.1.0
- GhostSlice version: sample
- Estimator: sample-estimator-1 (source: sample)
- Price table date: sample (estimates only, never billed amounts)
- Tests run: False

## Honest scope

- Measured: A (static, no model, no spend), 2 task(s).
- Not measured: live agent task completion (Tier B, opt-in, not run)
- Not measured: answer quality (no LLM judge in v0.1)

## Totals

- Full tokens (estimated): 8400
- sliced: 2000 tokens, saving vs full: 76.2%, fit success rate: 100.0%
- Tasks: 2 (pass 1, fail 1, unknown 0)
- Hard gaps predicted (Verify): 1

## Per-task results

| Project | Task | Status | Level | Full | Sliced | Saving % | Hard gaps | Symbols | Patch files | Manifest (sliced) |
|---|---|---|---|---:|---:|---:|---:|---|---|---|
| adversarial | adv-001-fix-missing-route | pass | static-analysis | 4200 | 1000 | 76.2 | 0 | - | shop/helpers.py | sha256:21198084e68cf1118905c699c3b0a819b59029d4f026ed5f4b8d1eba5afc1dac |
| adversarial | adv-002-broken-patch-missing-symbol | fail | static-analysis | 4200 | 1000 | 76.2 | 1 | - | shop/helpers.py | sha256:21198084e68cf1118905c699c3b0a819b59029d4f026ed5f4b8d1eba5afc1dac |

## Failures (all shown)

- adversarial/adv-002-broken-patch-missing-symbol: verify predicted 1 hard gap(s)

## Traceability

- Every token number comes from the estimator stamped above or from a bundle manifest whose sha256 is in bench-report.json for the same run.
- Reported (provider) token figures are never blended with estimates; Tier A has no reported figures.
