# GhostReview seam fix report, Oct 14, 2026

## The seam

Found by the Oct 14, 2026 ecosystem pass (~/workspace/ghostslice-companions/
ECOSYSTEM.md, Seams #1) and parent-verified by grep: GhostSlice's canonical
AWS secret pattern covers AKIA and ASIA (temporary session keys), but
GhostReview's `risks.py` token-prefix pattern was AKIA-only, so an ASIA
temporary key in a reviewed diff escaped the risk scan.

Demonstrated before the fix: a diff adding `SESSION = "ASIA1234567890ABCDEF"`
and `LONGTERM = "AKIA1234567890ABCDEF"` flagged only the AKIA line (high,
SECRET-SHAPED-LINE). The ASIA line drew no flag at all. After the fix, both
lines flag, and neither value appears in any output.

## What changed (src/ghostreview/risks.py only)

- token-prefix: AWS alternative is now `(?:AKIA|ASIA)[0-9A-Z]{16}`, and the
  whole token group carries Slice's word boundaries at both ends.
- token-prefix: GitHub widened from `ghp_`-only to Slice's
  `gh[pousr]_[A-Za-z0-9_]{20,}`.
- token-prefix: `sk-` aligned to Slice's
  `sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}` (the old `[A-Za-z0-9]{16,}` tail
  excluded `-`/`_`, so a real sk-ant- key broke the match after 3 chars).
- private-key-header: DSA and PGP key types added to the alternation.
- New shape `password-in-url` (Slice's password-in-url): `://user:pass@`
  with a password of 3 or more chars.
- New shape `aws-secret-context`: Slice's context-gated aws-secret-key,
  a bare 40-char base64-ish token only when the same line names an AWS
  secret (`aws.{0,20}secret|secret.{0,20}aws`, case-insensitive).
- labelled-secret-assignment: name list extended with `credentials?`.
- Scan mechanics unchanged: added lines only, one flag per line,
  first matching shape wins, value never copied into any output.
- README rule table updated to name the two new shapes.

## Per-shape parity audit vs Slice's canonical list

Canonical source: ~/workspace/ghostslice/src/ghostslice/secrets_scan.py
(`_KNOWN_PATTERNS` plus its context-gated and assignment shapes).

| Canonical shape | Before | Verdict |
|---|---|---|
| aws-access-key `\b(?:AKIA\|ASIA)[0-9A-Z]{16}\b` | AKIA only | ALIGNED (the seam itself) |
| github-token `\bgh[pousr]_[A-Za-z0-9_]{20,}\b` | `ghp_` only | ALIGNED |
| openai-or-anthropic-key `\bsk-(?:ant-\|proj-)?[A-Za-z0-9_\-]{16,}\b` | `sk-[A-Za-z0-9]{16,}` | ALIGNED |
| slack-token `\bxox[baprs]-[A-Za-z0-9\-]{10,}\b` | same shape | PARITY already, untouched |
| private-key header (RSA/EC/OPENSSH/DSA/PGP) | RSA/EC/OPENSSH only | ALIGNED on key types; deliberate divergence below |
| aws-secret-key (bare 40, context-gated) | absent | ALIGNED, added as aws-secret-context |
| password-in-url | absent | ALIGNED, added |
| sensitive-assignment (name + value, placeholder-filtered) | labelled-secret-assignment (quoted only) | PARTIAL parity; deliberate divergences below |
| high-entropy-assignment (entropy >= 4.0) | absent | Deliberate divergence below |

### Deliberate divergences, with reasons

1. Private-key header dashes: Slice requires the full `-----BEGIN ...
   -----` frame; Review matches the header words without requiring the
   dash runs. A diff can show a wrapped or trimmed header line, and the
   words `BEGIN ... PRIVATE KEY` are distinctive enough on their own.
2. Labelled assignments stay quoted-only: a bare right-hand side in a
   diff line is usually a reference or expression, not a literal. The
   bare-value config case is largely covered anyway, because a change
   to a `.env` or credential-named file already draws the high
   SECRET-PATH flag for the file itself.
3. No placeholder filtering: Slice suppresses example/changeme/fixture
   shaped values because it gates exports. Review flags an added line
   for human attention, and a flag is not a block; a placeholder-looking
   literal in a real diff still merits a glance.
4. Assignment name list stays narrower than Slice's substring set
   (no bare `key`, no `auth`): across arbitrary code diffs those
   substrings false-positive (`auth` fires on `author =`, `key` on
   ordinary identifiers). Slice accepts that noise because it has
   additional downstream gates; Review's flag is the final output.
5. No high-entropy-assignment shape: Review's contract (risks.py
   docstring) is explicit named rules whose thresholds are printed in
   the report so a reader can judge them. An entropy score is not a
   rule a reader can judge from the report, and entropy detection
   remains the export gate's job (GhostSlice).

## Tests

- Before: 67 passed.
- After: 77 passed, 0 failed (`python3 -m pytest tests -q` from
  ~/workspace/ghostreview/).
- 10 new tests, all additive, in tests/test_seam_fix.py. No existing
  test was edited, weakened, or deleted. The new tests pin: the ASIA
  canary flags as token-prefix at the right line with the value absent
  from every output; the AKIA control; an ASIA near miss (15 chars)
  does not flag; gho_ and sk-ant- canaries; DSA and PGP headers;
  password-in-url; the credentials labelled assignment; the
  aws-secret-context gate both ways (flags with context, silent
  without).

## Gates

Version unchanged (0.1.0, no bump). Stdlib only, local only. No push,
no PyPI, no publish, no announcements, no spend.
