# GhostExposure seam-fix report: secret-shape parity with GhostSlice

Oct 14, 2026. Sole-owner fix round for the cross-suite seam recorded as
Seams #1 in ~/workspace/ghostslice-companions/ECOSYSTEM.md and
parent-verified by grep: GhostSlice's canonical AWS pattern covers
AKIA and ASIA (temporary session keys); GhostExposure's aws_access_key
pattern was AKIA-only, so ASIA temporary keys shipped unredacted in
Exposure bundles.

Exposure's own docs claim the parity this audit measured against:
PLAN.md (secret handling inside the bundle) says the export "applies
Slice redaction to that value", and PLAN.md's secrets-guard item frames
the shape scan as the suite's guard sensor. Shapes are therefore
aligned to Slice's canonical list (ghostslice/secrets_scan.py) except
where a divergence is deliberate and recorded below.

## Test counts

- Before: 25 passed, 0 failed (`python3 -m pytest tests -q`).
- After: 34 passed, 0 failed. 25 existing tests untouched (no test
  edited, weakened, or deleted); 9 new tests in
  tests/test_seam_shapes.py (8 unit + 1 end-to-end).
- Version unchanged: 0.1.0. Stdlib only, local only, no push, no
  PyPI/publish, no announcements, no spend. Exposure remains
  evidence-only; no verdicts were added anywhere.

## The seam (fixed)

- aws_access_key: `\b(AKIA[0-9A-Z]{16})\b` became Slice's canonical
  `\b((?:AKIA|ASIA)[0-9A-Z]{16})\b`. An ASIA-shaped canary is now
  caught on every output surface, proven end to end by
  test_asia_canary_caught_on_every_output_surface: absent from the
  exported payload copy, PROMPT.md, EXPOSURE.md, exposure.json, and
  manifest.json; absent from CLI stdout/stderr and verify output;
  recorded in exposure.json redactions as path + line + type
  aws_access_key (value never recorded); the exported copy carries
  ***REDACTED***; the source project is byte-untouched; the bundle
  still verifies clean.

## Whole-list audit: per-shape record

Canonical source: GhostSlice `_KNOWN_PATTERNS` plus its special-case
kinds. Exposure type ids keep Exposure's snake_case convention; Slice
uses kebab-case for the same shapes. Naming differs, shapes align.

Aligned to parity in this round:

1. aws-access-key / aws_access_key: aligned (the seam, above).
2. github-token / github_token: Exposure's body class was
   [A-Za-z0-9]{20,}, missing the "_" in Slice's [A-Za-z0-9_]{20,}. A
   token with an underscore early in its body matched nothing (or
   matched only a prefix, leaving the tail unredacted). Aligned to
   Slice's exact pattern; regression test pins a full-span match on
   an underscore-bearing token.
3. openai-or-anthropic-key / openai_style_key: was sk- plus a flat
   {20,} body; Slice is sk-(?:ant-|proj-)? plus {16,}. Adopted Slice's
   exact pattern (prefix handling + the 16-char threshold);
   regression test pins an 18-char body the old pattern missed.
4. slack-token / slack_token: canonical Slice shape was missing from
   Exposure entirely. Added with Slice's exact pattern.
5. password-in-url / password_in_url: canonical Slice shape was
   missing. Added with Slice's exact pattern; group 1 is the password
   only, so redaction removes the password and leaves the URL's shape
   (scheme, user, host) visible as evidence.
6. aws-secret-key / aws_secret_key: canonical Slice rule was missing:
   a bare 40-char base64-ish value on a line that also names something
   AWS-secret-like. Added as the same special case Slice uses (context
   regex + bare-40), so an unquoted AWS secret in an env-style file is
   now redacted, and the same value with no AWS-secret context on its
   line is still not a finding (pinned by test both ways).
7. private-key / private_key_header: detection already covered the
   header, but Exposure redacted only the header line's span, leaving
   the base64 key body in the exported copy behind a redacted header.
   The finding span now covers the whole block (through the END line,
   or over the following bare-base64 body lines when no END line is
   present), mirroring Slice's _pem_block, and findings inside a block
   are subsumed by it. Deliberate micro-divergence: Exposure's header
   regex accepts any [A-Z ]* prefix wording where Slice enumerates
   RSA/EC/OPENSSH/DSA/PGP; Exposure's is a detection superset and was
   kept.

Deliberate divergences (recorded, not changed):

8. sensitive-assignment (Slice) vs generic_assignment (Exposure):
   Slice flags sensitive-name assignments with values of 8+ chars,
   with placeholder filtering and a bare-RHS-in-code rule. Exposure's
   heuristic layer requires a QUOTED value of 12+ chars under a
   sensitive name. Reason: Exposure rewrites exported evidence text,
   so a false redaction destroys the evidence the bundle exists to
   preserve; Slice's layer is tuned for reporting, where a loose flag
   costs nothing. Known consequence, stated plainly: unquoted
   assignment values, and quoted values of 8-11 chars, under sensitive
   names are flagged by Slice's guard but not redacted by Exposure.
   Aligning the thresholds is a policy call beyond this seam fix.
9. high-entropy-assignment (Slice): not adopted. Entropy-flagging any
   quoted 16+ char value would redact hashes, ids, and fingerprints
   that are themselves review evidence in an Exposure bundle. Recorded
   as a known coverage difference, not parity.
10. Placeholder filtering: Slice skips placeholder-shaped values
    (example/xxx/changeme/...) in every shape; Exposure has never
    placeholder-filtered, so a placeholder-shaped literal in an
    exported copy is redacted too. Standing deliberate divergence,
    unchanged by this round: in an export copy, over-redaction is the
    safe direction.

Exposure-only extra shapes (no Slice counterpart, kept):

11. bearer_token: "Bearer <token>" values; extra coverage.
12. long_hex_assignment: quoted 32+ hex under key/secret/token names;
    extra coverage for a common literal shape.

## Files changed

- src/ghostexposure/secrets.py: pattern alignment, three added
  shapes, PEM block spans, aws-secret context special case. Module
  docstring now records the parity stance.
- tests/test_seam_shapes.py: new, 9 tests.
- IMPLEMENTATION_A.md: dated addendum pointing here (build record
  itself unedited).
- SEAM_FIX_REPORT.md: this file.

Nothing else touched: no exporter/CLI/partition changes were needed,
because redactions already flow from find_literals to every surface
(payload copies, PROMPT.md, exposure.json records, EXPOSURE.md counts,
CLI stdout lines) by path + line + type.
