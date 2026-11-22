# GhostScope - Seam Fix Report (ASIA secret-shape alignment)

Fix round Oct 14, 2026. Sole-owner folder: ~/workspace/ghostscope/.
No version bump (still 0.1.0), stdlib only, local only, no push,
no PyPI/publish, no announcements, no spend. No existing test was
edited, weakened, or deleted; the only test change is one new file.

## The seam

The Oct 14, 2026 ecosystem pass aligned AKIA-only AWS secret
patterns in four sibling tools, but undercounted: the parent's
verification grep found a fifth carrier. GhostScope's
`src/ghostscope/secretslite.py` still held the AKIA-only form
`\bAKIA[0-9A-Z]{16}\b`, while GhostSlice's canonical guard
(`ghostslice/src/ghostslice/secrets_scan.py`) covers AKIA and ASIA.
An ASIA temporary session key on an added diff line therefore
escaped Scope's risk scan: no finding, no "secret-shaped line
added" reason, no risk raise.

## The design contract, established before changing anything

`secretslite.py`'s own docstring defines what "lite" is for:

> "Secret-shaped line detection for *added* diff lines... Findings
> carry line number + type only; the value is never stored or
> printed... This is a deliberately small pattern set for risk
> signalling, not a replacement for `ghostslice secrets`."

IMPLEMENTATION_A.md confirms the same intent (one module, type +
line only). So the smallness of the SET is a documented design
contract, and silently filling every canonical absence would break
it. But PLAN.md states the sourcing rule for the shapes Scope does
carry: a secret-shaped line raises risk "using Slice rules, not
new ones." The audit line drawn from those two documents:

- A shape the lite set CARRIES must track the canonical pattern
  for that shape. A carried pattern that is character-identical to
  canonical minus one alternative (exactly the AKIA case) is drift,
  not design.
- Canonical classes whose detection needs line context, a full
  assignment parser, placeholder tables, or entropy scoring are
  absent (or approximated) BY DESIGN: a per-added-line, single-
  regex, self-contained scanner cannot host them without ceasing
  to be lite. Those are recorded as deliberate divergences below,
  not filled.

The module docstring now carries this alignment contract in short
form, so the next reader does not have to re-derive it.

## The fix (src/ghostscope/secretslite.py only)

- `aws-access-key`: `\bAKIA[0-9A-Z]{16}\b` ->
  `\b(?:AKIA|ASIA)[0-9A-Z]{16}\b`. Byte-identical to canonical.
  This was the required alignment.
- The audit found the same copied-but-narrowed signature in three
  more carried shapes; all three aligned to canonical (details in
  the table). Each alignment only widens matching toward the
  canonical guard; no pattern was narrowed, removed, or renamed,
  and finding types/keys are unchanged.

## Whole-list audit vs canonical (secrets_scan.py)

Canonical kinds: private-key, aws-access-key, github-token,
openai-or-anthropic-key, slack-token, aws-secret-key (context-
gated bare-40), password-in-url, sensitive-assignment (parser),
high-entropy-assignment (entropy).

| Lite entry | Verdict | Detail |
|---|---|---|
| aws-access-key | DRIFT, aligned | ASIA alternative missing. Now byte-identical to canonical. |
| github-token | DRIFT (minor), aligned | Body class was `[A-Za-z0-9]{20,}`, missing the underscore canonical includes (`[A-Za-z0-9_]{20,}`). A token whose alnum runs are split by `_` into sub-20 runs escaped. Now identical to canonical. |
| openai-or-anthropic-key | DRIFT (minor), aligned | Lite had `(?:ant-)?` and tail `{20,}`; canonical is `(?:ant-\|proj-)?` and `{16,}`. The proj- omission was effect-free (the tail class matches through `sk-proj-`), the `{20,}` threshold was the real narrowing. Now identical to canonical. |
| private-key | DRIFT (minor), aligned | Header alternation lacked DSA and PGP. Now identical to canonical: `(?:RSA \|EC \|OPENSSH \|DSA \|PGP )?`. |
| slack-token | PARITY | Identical to canonical modulo `-` escaping inside the class. No change. |
| password-in-url | DELIBERATE DIVERGENCE (form) | Lite's pattern is a from-scratch construction (scheme-anchored, min password 4 vs canonical 3, no quote exclusion in userinfo), not a narrowed copy of canonical. Equivalent for added-line risk signalling. Recorded, not rewritten. |
| sensitive-assignment | DELIBERATE DIVERGENCE (design) | Canonical is a full line parser: wide name set, placeholder filtering, code-vs-config rules. Lite is a single-regex approximation over a narrower name set (api-key, secret, passwd, password, access-token), which is what a per-line lite scanner can honestly do. Filling this would import the parser and break the lite contract. Recorded, not filled. |
| aws-secret-key | DELIBERATE ABSENCE (design) | Canonical itself context-gates this shape because the bare 40-char shape is "too noisy on its own". Omitting the noisiest heuristic from a risk-signalling lite set is the documented small-set contract. Recorded, not filled. |
| high-entropy-assignment | DELIBERATE ABSENCE (design) | Generic entropy detection is the opposite of a small known-shape set and needs Slice's placeholder machinery to stay usable. Recorded, not filled. |

## Regression tests (new file: tests/test_secretslite_asia.py)

14 tests added, zero existing tests touched:

- Unit, AWS: ASIA canary caught with type/line/path; AKIA control
  still caught; finding dict carries exactly {path, line, type}
  and never the value; lookalikes (too short, lowercase, 15-char
  tail) not caught.
- Unit, other aligned shapes: underscore-body GitHub token,
  16-char-tail `sk-` key, DSA and PGP private-key headers (plus
  RSA and bare-header controls).
- Unit, parity controls for untouched shapes: slack token,
  anthropic key, password-in-url, sensitive-assignment all still
  caught, proving the alignment broke nothing else in the set.
- Integration (pack flow, the one place secretslite is used):
  a temp git repo whose change commit adds a file containing the
  ASIA canary produces a scope.json finding of type
  `aws-access-key` for that file, REVIEW.md states the
  "secret-shaped line added" reason, and the canary value appears
  in neither artifact (findings stay type + line only; the packed
  file body itself is the diff content, as designed).

Discrimination proof: each aligned shape's canary was checked
against the OLD lite patterns before the fix - all four missed
(old matches: False for aws-access-key, github-token,
openai-or-anthropic-key, private-key), so the new tests fail on
the pre-fix code and pass after it. They are regression tests,
not vacuous ones.

## Before / after

- Before: `PYTHONPATH=src:. python3 -m pytest tests -q` ->
  24 passed, 1 skipped.
- After: 38 passed, 1 skipped (24 existing + 14 new; the skip is
  the pre-existing optional ghostslice-on-PATH cross-check,
  unchanged). New file also passes standalone under
  `python3 -m unittest tests.test_secretslite_asia` (14 tests OK),
  and `python3 -m compileall src` is clean.

## Files changed

- `src/ghostscope/secretslite.py` - four patterns aligned to
  canonical; docstring gained the alignment contract note.
- `tests/test_secretslite_asia.py` - new regression test file.
- `SEAM_FIX_REPORT.md` - this report.

Nothing else touched: no PLAN.md/README/pyproject changes, version
stays 0.1.0.
