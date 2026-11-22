# GhostHandoff seam fix report: redaction shapes aligned with GhostSlice

Date: Oct 14, 2026. Owner: sole-owner fix round for ~/workspace/ghosthandoff/.
Status: suite green, **35 passed before → 44 passed after** (9 new tests,
0 existing tests edited, weakened, or deleted). Version stays 0.1.0.

## The seam

Found by the Oct 14, 2026 ecosystem pass (~/workspace/ghostslice-companions/
ECOSYSTEM.md, Seams #1) and parent-verified by grep: GhostSlice's canonical
AWS access-key pattern is `\b(?:AKIA|ASIA)[0-9A-Z]{16}\b`, covering ASIA
temporary session keys, but GhostHandoff's `redact.py` used an AKIA-only
pattern. Marker lines and report excerpts are quoted into HANDOFF.md and
handoff.json through that redactor, so an ASIA temporary key appearing in
one would have shipped in the clear.

## What changed

Only `src/ghosthandoff/redact.py` changed behavior. The shape list was
aligned with the canonical guard (`ghostslice.secrets_scan`), the module
was restructured from positional pattern handling to named patterns, and
the docstring now records the alignment. `REDACTED`, `redact_text`, and
`clean_line` keep their exact contracts, so every caller (marker scan,
report excerpts, commit subjects, stash messages) is unaffected except
that more shapes are caught. New file `tests/test_seam_redaction.py`
carries the regression pins. This report is the third and last file
touched.

## Per-shape parity against the canonical guard

| Canonical shape (GhostSlice) | Verdict after this fix |
|---|---|
| aws-access-key `\b(?:AKIA\|ASIA)[0-9A-Z]{16}\b` | **Aligned**, canonical pattern verbatim. Was `AKIA[0-9A-Z]{16}` (no ASIA, no word boundaries). This is the seam fix. |
| github-token `\bgh[pousr]_[A-Za-z0-9_]{20,}\b` | **Aligned**, canonical verbatim. Was separate `ghp_`/`gho_` patterns with no underscore in the body charset; now also covers `ghu_`, `ghs_`, `ghr_` and underscore bodies. |
| openai-or-anthropic-key `\bsk-(?:ant-\|proj-)?[A-Za-z0-9_\-]{16,}\b` | **Aligned**, canonical verbatim. Was `sk-[A-Za-z0-9]{20,}`; real `sk-ant-` and `sk-proj-` keys escaped it because the prefix broke the alphanumeric run the old pattern required. |
| slack-token `\bxox[baprs]-[A-Za-z0-9\-]{10,}\b` | **Parity** (was already semantically identical; spelling normalized to canonical). |
| aws-secret-key (bare 40-char, context-gated) | **Aligned**. Absent before. Mirrors the guard's gate exactly (a line must match `aws.{0,20}secret` or `secret.{0,20}aws`); on a gated line every bare-40 token is replaced. Redactor-side strengthening vs the guard's first-match reporting, deliberately fail-closed. |
| password-in-url | **Aligned**. Absent before. Only the password group is replaced; the rest of the URL stays readable, as in the guard. |
| sensitive-assignment | **Partial parity, deliberate divergence in mechanics.** Handoff's named-assignment rule gained `credential` (canonical name) and keeps redacting the value on the spot. It does not adopt the guard's value-length floor, placeholder allow-list, or code/config file rules: those are scanner precision features for whole files, and this redactor sees quoted fragments where failing closed costs nothing. The canonical bare names `key`, `token`, `auth`, `private`, `pwd` stay excluded as too ambiguous in quoted prose (an env excerpt's `pwd: /home/...` or a usage excerpt's `token: 12345` are not credentials). |
| private-key (PEM block) | **Deliberate divergence, recorded gap.** The guard detects a multi-line block in a whole file; Handoff redacts truncated single-line fragments (140-200 chars), where a BEGIN header line carries no key material and body lines are bare base64 indistinguishable from other fragment text. Block semantics cannot be reproduced on fragments, and no half-measure was added. |
| high-entropy-assignment | **Deliberate divergence.** An entropy heuristic is a scanner detector, not a shape; Handoff's stated surface is shapes plus named assignments. Residual gap: a high-entropy value quoted under a non-sensitive name is not caught. Accepted and recorded. |
| Placeholder filtering (the guard's `_is_placeholder`) | **Deliberate divergence.** The guard skips placeholder-shaped values (example / fixture / not-a-real and kin); the redactor fails closed and redacts them too, including documented example keys such as AWS's `AKIAIOSFODNN7EXAMPLE` (behavior the pre-existing test in test_cli_pack.py already pins). Harmless in a pack. |
| `github_pat_` fine-grained PAT (Handoff only) | **Kept, unchanged.** Not in the guard's list; a real GitHub credential shape a fragment can carry. Divergence in the safe direction. |
| `bearer` token (Handoff only) | **Kept, unchanged.** Same reasoning. |

## Regression tests (tests/test_seam_redaction.py, 9 new)

End-to-end, through the real CLI on real fixture folders:

- `test_asia_canary_in_marker_line_is_redacted_in_both_pack_files`:
  ASIA canary in a code TODO line; absent from HANDOFF.md and from
  handoff.json, the marker is still listed, and the redaction token
  appears in both surfaces including the JSON marker items.
- `test_asia_canary_in_report_excerpt_is_redacted_in_both_pack_files`:
  ASIA canary in VERIFY.md's first line (the excerpt path); absent
  from both pack files, token present in the report summaries.

Unit pins for the aligned shapes: ASIA and AKIA both redacted
(including punctuation-adjacent), canonical GitHub prefixes and
underscore bodies, `sk-ant-` / `sk-proj-` / 18-char `sk-`, password-
in-URL redacting the password only, the AWS-secret context gate
(redacted with AWS+secret context, untouched without it), named
assignments including `credential`, and a benign line passing through
unchanged.

Mutation evidence: replaying the pre-fix pattern set over the five
canary lines (ASIA marker, sk-ant, ghs_, URL password, gated AWS
secret) leaves all five in the clear; the post-fix code redacts all
five, which is what the new tests assert.

## Gates held

Handoff remains propose-only and read-only on described projects (no
caller changed; the redactor is a pure text function). Stdlib only
(`re`). No version bump, no push, no PyPI/publish, no announcements,
no spend.
