# SAMPLE - illustrative shape only

This file is hand-written to document the REVIEW.md format defined in
PLAN.md. It is NOT captured output from a real GhostScope run.

# Review pack

Base: HEAD~1  Head: HEAD
Token totals (estimates): pack 1,240 / raw diff 1,180 / repo 48,900

## Reading order (riskiest first)

1. `shared.py` - `compute_total`
   Reasons: exported API, 6 callers, covering test present
2. `isolated.py` - `isolated_thing`
   Reasons: no covering test, no callers

## Notes (facts, not decisions)

- None in this sample.
