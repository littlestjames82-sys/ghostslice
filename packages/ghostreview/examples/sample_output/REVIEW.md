# GhostReview - SAMPLE SHAPE ONLY

Hand-written to document the REVIEW.md format from PLAN.md.
Not captured output from a real run. Real runs write this file
next to review.json in the output directory you name.

**Verdict: needs-attention** (exit 1)

This change touches 4 file(s) (3 modified, 1 deleted), with 5
line(s) added and 16 line(s) deleted. The largest change is in
legacy.py (0 added, 10 deleted). 1 other project file(s) import
a changed file and are not in this diff. Risks flagged:
TEST-EDIT, SECRET-PATH, LARGE-DELETION. No GhostVerify report
was provided, so no Verify check is cited in this review.
Verdict: needs-attention.

## What changed

- `pricing.py` (modified): 1 line(s) added, 2 line(s) deleted.
- `tests/test_pricing.py` (modified): 1 line(s) added, 1 line(s) deleted.
- `.env` (modified): contents not shown, secret-shaped path.
- `legacy.py` (deleted): 0 line(s) added, 10 line(s) deleted.

## Risks

- [medium] TEST-EDIT in `tests/test_pricing.py`: a test file is
  modified in this diff.
- [high] SECRET-PATH in `.env`: the changed path is
  secret-shaped; its contents are not shown in this review.
- [high] LARGE-DELETION in `legacy.py`: a whole file is deleted
  in this diff.

## Honest limits

- This review summarises static evidence from the diff only.
  "No risks flagged by these rules" is not a guarantee that a
  change is safe, and the verdict is a summary, not a merge
  decision.
