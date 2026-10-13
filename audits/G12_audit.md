# G12 Audit — Redact-in-place export (v0.17.0)

Goal: `export --redact` (plus profile `"redact": true`, `--no-redact`
override, task/fit/watch/MCP inheritance) replaces flagged secret
VALUES in the final slice text with `[REDACTED:<kind>:<fp>]`
placeholders — fingerprint = first 8 hex of sha256, only for values
>= 12 chars (short/low-entropy literals get a fingerprintless token,
because an 8-hex sha256 prefix of an 8-char password is a
brute-force oracle). Same scanner kinds as --exclude-secrets judges
(REDACTED_KINDS = every kind scan_text can emit; the scanner's
placeholder/entropy/name gates are the severity filter), different
remedy: exclude drops the file, redact keeps it. Precedence when
both are on: exclusion wins for flagged files (it resolves first, at
mode resolution); redaction covers the rest; the CLI prints that.
Baseline 488 tests; build brought the suite to 519 (31 new in
tests/test_v17_redact.py).

## Audit #1 (after build) — self-attack battery

Attack fixtures beyond the unit tests: trailing-comment and
full-line-comment keys, a PEM block inside a module-level string
constant (survives signatures slicing), a TS string-literal type in
interfaces mode, a Markdown heading + body key, a YAML webhook URL
in full and structure modes, copilot preset (its prompt.md embeds
content independently of PROMPT.md), byte-counted occurrence checks
across every bundle artifact.

### F1 [CRITICAL] Comment-line secrets ship in redacted bundles
The guard's reporting scan deliberately skips full-line comments
(`#`, `//`, `*`, `/*` — "documentation/examples far more often than
live secrets"; only private-key blocks are exempt). Redaction
inherited that scan verbatim, so a real key on a comment line ships
in a bundle that claims redaction: reproduced byte-exactly — a
Markdown HEADING (`# Project notes AKIA…`: content, not a comment,
but `#`-prefixed) carried the literal into files/c.md, PROMPT.md
and the copilot prompt.md in both full and headings modes; the same
hole covers `/* … */` block bodies and commented-out config lines
in full mode. The reporting heuristic is right for `ghostslice
secrets` (noise) and wrong for a publication artifact (leaks).
Fix (Improve #1): ONE detection core, one documented knob —
`_scan_rich(..., comments=False)` stays the reporting default
(guard, lint L005, watch warnings, config backstop all unchanged),
while `redact_text` and the validator's redaction check scan with
`comments=True`: comment lines are then judged like any other line
(known shapes, URL passwords, assignments). Redaction is a strict
superset of the guard, never weaker; placeholder-shaped examples
in docs comments (the scanner's placeholder filter still applies)
stay untouched, and with --redact off nothing changes anywhere.

### F2 [LOW] --fit + --redact print two different "after" totals
The fit ladder judges pre-redaction slices (it must: redaction
depends on the slice the ladder picks), so manifest["fit"]
after_tokens is a pre-redaction number, while the manifest totals
are post-redaction. The CLI printed both with no explanation.
Fix (Improve #1): when redaction changes the total, the manifest's
fit block gains an additive `redacted_after_tokens`, and the CLI
fit line adds "(after redaction: N; the ladder judged
pre-redaction slices)". The `fitted` verdict stays the ladder's —
documented in README.

### Categories audited with no findings
- Artifact coverage: with F1's class set aside, a grep-the-bundle
  test walks EVERY file of json and anthropic-xml bundles (files/,
  PROMPT.md, context.json/xml, manifest) — no literal anywhere;
  copilot prompt.md derives from the same redacted final_text.
- PEM: block replacement consumes BEGIN..END (or the trailing
  base64 body when a slice cuts the END line); the body chunk is
  absent from every artifact; one token line remains.
- Survival through slicing: signature default argument, docstring,
  TS string-literal type in interfaces mode, structure-mode YAML
  (configslice placeholder + redaction net agree) — all redacted.
- Fingerprint safety: 8-char password and 5-char URL password get
  fingerprintless tokens (pinned); >= 12 chars get the sha256
  prefix; identical literals map to identical tokens across files.
- Overlaps: a URL that is both a high-entropy assignment value and
  a password-in-url — rightmost-first span application with
  overlap skip; both findings counted, rescan clean.
- Same-line repeat: the scanner reports only the first match per
  pattern per line; redaction collapses further occurrences of the
  same literal on that line (pinned), so the rescan gate does not
  false-fire.
- Placeholder hygiene: the token itself never trips the scanner
  ("redacted" is a placeholder marker; leading "[") — pinned by
  rescan tests at text and bundle level; validate_bundle passes on
  genuine redacted bundles and `redaction_checked` is true.
- Validator adversarial: a planted literal with hash/token
  bookkeeping fixed up so ONLY the redaction check can fail —
  fails (pinned). Bundles that never claimed redaction validate
  exactly as before (pinned).
- Totals: manifest sliced tokens are recomputed from the shipped
  redacted bytes with the validator's own estimator call (pinned
  per-file); originals unchanged; ledger record gains "redactions".
- Split secrets: a key split across two lines (string concat) is
  not flagged — an inherited scanner boundary (the guard has the
  same limit; redaction judges exactly the guard's universe plus
  comment lines). Accepted, documented in README.
- Surfaces with no slice embedding: bundle diff (manifests only),
  HTML report (paths/lines/types + 4-char previews only), watch
  stderr warnings (previews only). The `slice` CLI and the
  dashboard /api/export do not apply redaction — the former is a
  raw utility that also ignores --exclude-secrets; the latter
  never passes a profile to build_bundle (pre-existing for every
  profile option). Accepted limitations, noted in the handoff.

## Improvement round 1 (from Audit #1)

- F1: `_scan_rich`/`scan_text` gained the `comments` knob (default
  False = every pre-v0.17 behaviour byte-identical; the full suite
  stayed green untouched). `redact_text` scans and re-scans with
  comments=True; the validator's redaction check scans with
  comments=True. Six regression tests: full-line-comment key in a
  full-mode file (guard still does not REPORT it — pinned both
  ways), Markdown heading in headings mode, `/* */` block body,
  a validator plant on a comment line, all now redacted/caught.
  Re-ran the attack battery: literal occurrences in the copilot
  bundle went from 3 artifacts x 1 to ZERO; guard findings on the
  same tree unchanged.
- F2: manifest fit block gains `redacted_after_tokens` when the
  post-redaction total differs; the CLI fit line prints it with
  the explanation. Pinned by API + CLI tests.

## Audit #2 (after Improve #1) — fixed-state review + new probes

### F3 [MEDIUM] The goal's own test file tripped the repo guard
`ghostslice secrets .` exited 1 on this repo: the first cut of
tests/test_v17_redact.py carried contiguous fake literals (the AKIA
constant, PEM header text, a 40-char AWS-shaped string, a URL
password) in its SOURCE, and the guard scans source text like any
other. Ironic and useful — the guard catches exactly the shapes
this goal redacts — but the constraint is a clean self-scan.
Fixed in Improve #2: fixtures assemble literals from parts
(concatenation breaks every pattern in the source while the
runtime values stay the real shapes); guard exits 0, all 37 tests
unchanged in what they assert.

### New probes, no findings
- Notebook (.ipynb) slice carrying a key: redacted, validates.
- False-positive sweep: redact_text (comments=True) over every
  .py/.md/.json/.txt/.yaml/.toml file in this repo — ZERO
  redactions applied, zero leftovers; the stricter scan does not
  damage real-world text (docs examples are placeholder-shaped).
- Self-export of this repo with --redact: validates; 0 redactions
  (test fixtures sit behind strip-tests slicing; src/ is clean).
- Comment-line assignment false positives are structurally
  unreachable: the assignment regexes anchor at line start and a
  comment marker breaks the anchor, so comments=True adds known
  shapes + URL passwords on comment lines, not prose rewrites.
- Watch's export_profile (dataclass replace) carries the new
  profile field; MCP redact argument round-trips (pinned).

## Improvement round 2 (from Audit #2)

- F3 fixture-source fix (above).
- Docs: README gained the "Redact in place" section (token format,
  fingerprint rule and its reason, precedence, validator, fit
  labelling, stated boundaries) and a profiles-section mention;
  CHANGELOG [0.17.0]; build_bundle's redact docstring now names
  the comment-context scan; CLI module docstring lists --redact
  for export/watch.

Final state: 525 tests passed (488 baseline + 37 new), full suite
green, `ghostslice secrets .` exit 0, version 0.17.0.
