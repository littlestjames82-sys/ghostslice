"""GhostReview: plain-English verdict layer for GhostSlice changes.

Zero-dependency Python stdlib only. Local only, no network.
Reads a git diff, optionally cites a GhostVerify verify-report.json
and a GhostScope scope.json, and writes REVIEW.md + review.json.
Verdicts are template summaries over counted static facts only:
no LLM, no invented causes, no approval or merge decision.
GhostScope builds the review pack; GhostReview does not.
"""

__version__ = "0.1.0"
