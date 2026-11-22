# GhostProxy seam fix: Slice-absent secret fallback had drifted from the canonical guard

Oct 14, 2026. Sole-owner fix round for the cross-suite seam the ecosystem
pass found in `src/ghostproxy/slice_adapter.py`. No version bump (still
0.1.0), stdlib only, local only, nothing pushed or published.

## The seam

`slice_adapter.scan_secrets` is the adapter path `transform.py` calls on
every context file (transform.py:202): any finding drops the file from
the proxied request with reason `secret-guard`, and only the finding
types are recorded, never a value. When GhostSlice is importable the
adapter delegates to `ghostslice.secrets_scan.scan_text` and inherits
the canonical guard exactly. When GhostSlice is absent, a narrow
in-module fallback pattern list runs instead, and that list had drifted
from the canonical one (ghostslice/src/ghostslice/secrets_scan.py,
`_KNOWN_PATTERNS`):

- Its AWS pattern was `\bAKIA[0-9A-Z]{16}\b` (AKIA only). The canonical
  pattern is `\b(?:AKIA|ASIA)[0-9A-Z]{16}\b`: ASIA temporary session keys
  were missed entirely, so on the Slice-absent path a file carrying one
  was forwarded upstream instead of dropped.

## Before / after

- Suite before: **30 passed, 1 xfailed** (the known mid-SSE xfail in
  tests/test_fail_open.py; untouched by this round, still the only one).
- Suite after: **55 passed, 1 xfailed**. 25 new tests, all in the new
  file `tests/test_slice_adapter_fallback.py`; no existing test edited.
- Pre-fix probe (fallback forced, one line per case): ASIA key, DSA and
  PGP private-key headers, underscore-bearing GitHub token, Slack token,
  password-in-URL, YAML colon assignment, and the context-gated AWS
  secret shape were ALL missed. Post-fix probe: every one is caught,
  and the fallback's finding types match the canonical guard's exactly
  on every probed line, including both negative controls (the AWS
  documentation example key stays unflagged; a bare 40-char value with
  no AWS context stays unflagged).

## The fix (src/ghostproxy/slice_adapter.py only)

The fallback AWS pattern is aligned to canonical AKIA|ASIA, and the
rest of the fallback list was aligned per the audit below. The fallback
branch of `scan_secrets` additionally applies Slice's context gate for
the bare-40 `aws-secret-key` shape. Findings still carry exactly
`{path, line, type}`; values are matched and discarded, and a new test
pins that no canary value appears in any finding's repr.

## Per-shape audit against the canonical guard

| Canonical shape | Fallback before | After this fix | Verdict |
|---|---|---|---|
| private-key | Missing DSA and PGP header variants | Canonical pattern verbatim | Aligned |
| aws-access-key | AKIA only (the seam) | `\b(?:AKIA|ASIA)[0-9A-Z]{16}\b`, canonical verbatim | Aligned |
| github-token | Tail class lacked `_`; a token containing an underscore could never match (the trailing `\b` fails before `_`) | Canonical `[A-Za-z0-9_]{20,}` | Aligned |
| openai-or-anthropic-key | No `proj-` alternative; `sk-proj-` was caught only by accident (the prefix absorbed into the body class) | Canonical `(?:ant-\|proj-)?` | Aligned |
| slack-token | Absent | Canonical pattern added | Aligned |
| password-in-url | Absent | Canonical regex added (search-only; findings never carried the value anyway) | Aligned |
| aws-secret-key | Absent | Added with Slice's own gate: an `aws`/`secret` context within 20 chars on the line plus a bare 40-char value, minus placeholders | Aligned, one residual divergence below |
| sensitive-assignment | `=` separator only, quoted value, 5 names | Separator aligned to `[:=]` so YAML-style assignments are covered; name gate kept narrower than Slice's | Deliberate divergence (below) |
| high-entropy-assignment | Absent | Still absent | Deliberate divergence (below) |

Deliberate divergences, stated plainly:

1. **Placeholder filtering is a trimmed copy.** Slice's `_is_placeholder`
   also recognises env-var references, dotted variable references, and
   expression-shaped values. The fallback keeps the marker-substring,
   symbol-only, and repeated-pattern checks, which is what the bare-40
   gate needs to stay honest (it keeps the AWS docs example key
   unflagged, pinned by test). The residual risk is a placeholder-shaped
   40-char value on an AWS-secret line being flagged on the fallback
   path only: the failure mode is one file dropped from one proxied
   request, the safe direction for a secret guard.
2. **sensitive-assignment keeps a narrower name gate.** Slice matches 9
   sensitive-name terms as substrings, plus `:`/`=` separators, config
   bare-value rules, and placeholder judgement. The fallback keeps 5
   explicit names and requires a quoted value. Its failure mode is
   dropping a whole file from a live request, so the net stays narrow
   on purpose; the full heuristics are Slice's job and run whenever
   Slice is present, which is the normal deployment.
3. **No high-entropy-assignment.** Per-line entropy scoring is real
   work in a fail-open proxy's hot path and is the subtlest part of
   Slice's guard (entropy plus digit/alpha gates plus placeholder
   filtering). A half-copy would risk both noise and false confidence.
   The quoted sensitive-assignment net covers the common
   credential-assignment case.
4. **Comment lines are still scanned.** Slice's reporting scan skips
   full-line comments; the fallback never did and still does not. This
   predates the fix and errs toward flagging: a real key sitting in a
   comment drops the file. Slice itself treats comments as content in
   its redaction context for the same reason.

Also checked and left alone: `ledger.py`'s name list is a ledger-field
redaction list, not a value-shape scanner, so it is outside this audit.

Latency note: in the normal deployment (GhostSlice present) the fallback
never runs, so the added shapes cost nothing. On the fallback path the
additions are same-class regex searches plus one context regex per line.

## Regression tests (tests/test_slice_adapter_fallback.py, 25 tests)

- The seam: an ASIA canary on line 3 of a file is caught by the forced
  fallback with the exact finding `{path, line: 3, type: aws-access-key}`,
  and the canary appears nowhere in the findings. AKIA anchor alongside.
- The adapter path catches ASIA whichever path runs (delegated or
  fallback), so the seam cannot reopen by environment.
- All 10 audit parity cases, each also checked against the real
  canonical guard (`canonical types <= fallback types` per line), so
  future drift in either list fails a test instead of shipping.
- Negative controls: AWS docs example key and context-free bare-40 stay
  unflagged, matching canonical behaviour.
- Value hygiene: a mixed canary file yields findings whose repr contains
  none of the canary values and whose keys are exactly {path, line, type}.

## Gates held

Full suite green with the same single xfail; the mid-SSE xfail and its
test were not touched. Proxy stays fail-open (a slicing/scan failure
still passes content through; this fix only widens what the
Slice-absent guard recognises) and stores no keys anywhere. No push, no
PyPI, no announcements, no spend.
