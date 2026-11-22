# GhostLogs v0.1 polish report

Polish round directed by Ryan ("Polishing"), Oct 14, 2026, after
parent verification of Wave 4 (26 tests passing, D1/D3 fix round
landed, strict-xfail markers already removed by the parent).
Sole folder owner for this round. In-tree only: no version bump,
no push, no publish, no announcements, no spend. Stdlib only.

## Test counts

- Before: `python3 -m pytest tests -q` -> **26 passed**
  (reproduced at the start of this round).
- After: **30 passed**, confirmed on two consecutive full runs.
- No existing test was edited, weakened, or deleted. Four tests
  were ADDED in `tests/test_polish.py`.

## Audit

Read PLAN.md, IMPLEMENTATION_A.md, REPORT_B.md, FIX_REPORT.md,
README.md, and the core (`pack.py`, `redact.py`, `cli.py`). The
seed candidates from the documented material were all real, and
the audit found one more: the README's honest limits still
described pre-D1 behaviour for repeated lines inside windows.

## What changed

### 1. The pack file itself now states an over-budget outcome
(`src/ghostlogs/pack.py`)
Before, an over-budget outcome lived only in the manifest
(`over_budget: true`), the terminal line, and the exit code.
INCIDENT.md, the file actually handed to a reader or an agent,
said nothing. Now, when a pack ships over budget, `build_pack`
appends a `## Pack status` section to INCIDENT.md stating the
outcome and why, then recomputes `pack_estimated_tokens` on the
final text so the manifest estimate still describes the pack
exactly as written.
Demonstrated: fixture at `--budget 150` -> tier anchors,
estimate 571, `over_budget: true`, counts reconcile, and
INCIDENT.md contains the Pack status section (pinned by
`test_polish.py::test_over_budget_pack_says_so_in_incident_md`).

### 2. Budget tier naming now explains itself
(`pack.py`, `cli.py`)
The manifest recorded `budget_tier` (`full` / `trimmed` /
`exemplars` / `anchors`) with no gloss anywhere a stranger
would find one, and INCIDENT.md never named the tier. Now:
- the manifest also carries `budget_tier_meaning`, a plain-words
  sentence per tier;
- INCIDENT.md states `Budget tier: <tier> (<short gloss>)` on
  its face whenever the shipped tier is below `full`;
- the CLI summary prints the tier and its meaning on every pack.
The tier ladder measures each rendered candidate for real, so
the added line is inside the measurement: honesty of the fit
decision is unchanged by construction, and the suite's budget
bars (sweep 500/600/850/2000, budget-600 fit, tight-budget
shrink) all still pass.
Demonstrated: fixture at `--budget 500` ships tier `anchors`
with the tier line in INCIDENT.md and the meaning in the
manifest; a default pack ships `full` with no tier line
(both pinned in `test_polish.py`).

### 3. Manifest limits updated to match (pack.py `LIMITS`)
The tier limit now also names `budget_tier_meaning` and the
on-face tier statement, and a new limit states the redaction
length exactness precisely (see 4). Manifest-only text: it does
not enter the pack estimate, which is measured on INCIDENT.md.

### 4. Length-sensitive shape matching: documented precisely,
not tightened (README + probe + tests)
Evidence: GhostSlice's own guard uses the identical AWS pattern
(`\b(?:AKIA|ASIA)[0-9A-Z]{16}\b` in
`ghostslice/src/ghostslice/secrets_scan.py`), and GhostLogs'
plan position is that its shapes follow the Slice guard. Real
AWS access key IDs are exactly 20 characters. Diverging inside
GhostLogs alone would break suite consistency to catch strings
that are not, in fact, that credential shape. So the matcher is
unchanged and the documentation is now exact instead of vague:
- README's "runs longer or shorter may not be recognised" is
  replaced with the precise rules: AWS shape is AKIA/ASIA plus
  exactly 16 chars (20 total); other provider shapes are
  minimum-length; a generic assignment needs a sensitive-looking
  name plus a value of at least 8 characters with at least 4
  distinct characters, not placeholder-shaped.
- Probed before documenting (`redact_line`): 20-char AKIA hit,
  22-char and 18-char AKIA look-alikes miss; `password=` values
  of 6 and 7 chars miss, 8 distinct chars hit, 8 identical chars
  miss (distinct-count rule). All four outcomes match the
  documented wording, and two new tests
  (`test_aws_shape_is_exact_length_by_design`,
  `test_generic_assignment_minimums`) pin them. Pinning the
  22-char miss is deliberate: it keeps the documented limit
  honest under test, the same way the suite pins other limits.

### 5. Path-length estimate quirk: measured, documented,
behaviour left alone (README)
Measured this round on the unchanged estimator: the example log
packed from a 10-character path estimated 702 tokens; the same
bytes from a 72-character path estimated 730, a delta of 28
tokens for 62 extra path characters. The README's quirk note
now carries those measured numbers and states the reason the
behaviour stays: the estimate counts the pack exactly as
written (the honest rule the D3 fix established), the header
path is provenance, and the manifest sha256 is the identity.
Removing the path from the header to chase reproducibility
would trade away provenance for a cosmetic property; making the
fit decision use a different text than the shipped pack would
be dishonest. Neither trade is justified by 28 tokens.

### 6. Stale README limit corrected (README)
The honest-limits entry for repeated lines inside windows
still said their counts live only outside windows, which the
D1 fix changed. It now states the post-D1 truth: window
repeats are counted as window duplicate groups with exact
occurrence counts in the manifest and listed in the pack, with
consecutive repeats collapsed in place inside the window.
The README's budget section also gained the tier ladder in
plain words, and the quick-start paragraph now names the
Pack status section from change 1.

## What was deliberately left alone

- **Redaction patterns**: unchanged (see 4). Suite consistency
  with GhostSlice's guard beats a speculative local tightening.
- **The estimate counting the pack as written, header path
  included**: unchanged (see 5).
- **Common-path output**: a full-tier pack within budget is
  byte-identical before and after this round. Verified: the
  example log at `--budget 2000` produced INCIDENT.md sha256
  `78b84ab7676966091cb1b1c53141dd894280ecc8af39686dbcfc9d5c44e18a8e`
  under both the pre-polish and polished code.
- **Version**: still 0.1.0 everywhere. Releases are Ryan-gated.
- **`examples/`**: untouched; change 6's README is the root
  README. The checked-in example pack is a full-tier pack, and
  per the byte-identity check above it is exactly what the
  polished code produces.
- **IMPLEMENTATION_A.md's known limits** (throughput, minimum
  pack size, signature-table growth): still accurate as written;
  the minimum-pack-size note (~370-470 tokens of scaffolding) is
  consistent with this round's measurements.

## Hard bars re-verified

- Manifest line accounting reconciles exactly at every tier
  probed (2000/850/600/500/150) and in the suite's accounting
  tests, including the over-budget anchors tier.
- Planted secret shapes (GitHub-token and AWS canaries in the
  fixture) appear in no pack file, manifest, stdout, or stderr:
  the suite's secrets tests pass unchanged.
- Full suite green twice consecutively: **30 passed**.
