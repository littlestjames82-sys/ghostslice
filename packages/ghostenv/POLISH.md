# GhostEnv v0.1 - Polish Round (Oct 14, 2026)

Ryan directed "Polishing" after Wave 3 parent verification
(29 tests passing, canary leak test clean). Sole folder owner for
this round. House loop: audit first, then two distinct improvement
passes, demonstrate-then-fix throughout. No version bump, no push,
no publish, no announcements, no spend, no network. Stdlib only.

Baseline before any change: 29 passed. Final: **41 passed**
(29 existing + 12 new regression tests), under both
`python3 -m pytest tests -q` and `python3 -m unittest discover`.

## Audit findings (each demonstrated on a throwaway fixture first)

Verdict layer:
- A1 (required fix). Duplicate-only project: exit 1, verdict read
  "contract complete: no missing names found by static scan".
  Exit code and verdict were computed from different conditions.
- A2. Case-mismatch-only project: exit 1, verdict claimed "hard
  findings present" while the hard count was 0. Same for the
  missing-example-file case. The verdict never named the actual
  blocking category.
- A3. Malformed `.env` lines were silently dropped - no finding
  existed for them at all, while the README table listed a
  "malformed line" finding. A malformed-only project exited 0.
- A4. Case-mismatch paired variants with identical membership in
  all three sets: code using both TOKEN and Token, both defined
  and documented, fired a blocking mismatch. PLAN defines the
  classification cross-set ("a name in one set differs from a
  name in another"); identical membership is a consistent (if
  ugly) contract, not a mismatch.

Parser-lite accuracy:
- P1. `os.environ.setdefault("X", default)` classified hard: the
  pattern never captured the comma that proves a default.
- P2. Python `or` fallback (`os.environ.get("X") or ...`,
  `os.getenv("X") or ...`) classified hard.
- P3. Bare `environ.get(...)` / `environ.setdefault(...)`
  (from `from os import environ`) were not scanned at all.
  (Bare `environ[...]` and bare `getenv(...)` already were.)
- P4. JS `??` nullish fallback classified hard; only `||` was
  detected.
- P5. Full-line comments were scanned in shell (`#` lines) and in
  JS/TS/Go/Rust (`//` lines), producing findings for names that
  appear only in comments.
- P6. Rust `env::var_os` / `std::env::var_os` not scanned;
  `env::var("X").unwrap_or(...)` classified hard.
- P7. Shell `${NAME-default}` / `${NAME=default}` (POSIX forms
  without the colon) were not matched at all - the regex required
  the colon, then expected `}` and failed. `${NAME:-...}` worked.
- P8. f-string env names (`os.getenv(f"{P}_KEY")`) vanished
  entirely instead of counting as dynamic read sites.

Docs accuracy:
- D1. README findings table omitted case-mismatch entirely and
  claimed malformed lines were reported (A3 made it true rather
  than deleting the row).
- D2. README said dynamic lookups are "invisible to this report";
  they are counted as dynamic read sites by file and line.
- D3. examples/README walkthrough claimed `check` on
  mini_project exits 0. It exits 1: examples deliberately ship no
  real `.env`, so two names are hard-missing. Verified live.

## Pass 1 - verdict correctness (doctor / envparse / reports)

- Verdict and exit code now derive from ONE enumerated
  `blocking_reasons` list (also exposed in the JSON report):
  hard missing names, missing example file with undocumented
  names, case-mismatch pairs, duplicate definitions, malformed
  lines. The verdict string names every blocking category that
  fired and nothing else ("contract incomplete: 1 duplicate
  definition(s)"). Exit 0 now always reads "contract complete:
  no blocking findings found by static scan".
- Malformed lines are a real finding: `findings.malformed`
  carries file label + line numbers ONLY. The line's content is
  never stored or printed - a malformed line may be a bare
  value. Malformed counts in `counts.malformed`, renders in the
  text report, and blocks (a silently ignored definition is the
  drift this tool exists to catch).
- Case-mismatch is now membership-aware: a variant group is
  reported only when its spellings do not all appear in exactly
  the same sets. Cross-set pairs (the original Api_Url/API_URL
  fixture shape) still fire.
- Soft, stale, and missing-in-example (file exists) findings
  remain non-blocking, per PLAN; the verdict no longer claims
  or hides any of them.

## Pass 2 - parser accuracy and docs

Scanner:
- setdefault captures its comma (default arg = soft), for both
  `os.environ.setdefault` and bare `environ.setdefault`.
- Python `or` fallbacks detected for environ.get / getenv
  (marker group is the word `or`; fallback text never captured).
- Bare `environ.get(...)` pattern added.
- JS `??` fallback patterns added for dot and subscript reads.
- Rust `var_os` added; `.unwrap_or(...)` / `.unwrap_or_default()`
  after `var()` marks a default (same dedupe merge as JS).
- Shell regex accepts the colon-less POSIX operators; default
  detection now reads the operator characters only: `-` and `=`
  (with or without colon) are defaults, `+` and `?` are not.
- Full-line comments are skipped in every language (`#` for
  Python/shell, `//`, `/*`, `*` for JS/TS/Go/Rust). Trailing
  comments after code on the same line are still scanned
  (parser-lite, now stated in the README limits).
- f-string read sites count as dynamic (file + line, name never
  guessed).

Docs:
- README findings table gained the case-mismatch row, a
  malformed row stating line-numbers-only, and a paragraph
  defining exactly which findings block (exit 1) and that the
  verdict names them. Quickstart exit-code comment corrected.
  Limits corrected on dynamic lookups and comment/string
  behaviour.
- examples/README walkthrough rewritten to the verified truth:
  plain check on mini_project exits 1 naming DATABASE_URL and
  DEMO_API_KEY (no real .env ships, by design); the clean run
  uses `--env-file examples/mini_project/.env.fake` and exits 0;
  deleting the whole example file blocks, removing one line is
  listed under missing-in-example and does not block on its own;
  generation step verified (3 names).

## Names-only invariant

Unchanged and re-verified. New surfaces (blocking_reasons,
malformed findings, verdict text) carry counts, names, file
labels, and line numbers only. They are covered by the existing
canary leak test, whose `check` and `check --json` runs over
canary_project exercise all three, plus a dedicated polish test
that plants a canary string inside a malformed line and asserts
it appears in no output on any surface while its line number is
reported. Canary leak test stays green.

## Regression tests added (tests/test_polish.py, 12)

- Duplicate-only verdict names the duplicate (JSON + text).
- Case-mismatch-only verdict names case, not hard-missing.
- Verdict enumerates multiple blocking reasons together.
- Both-spellings-everywhere passes with no mismatch.
- Clean fixture: verdict complete, blocking_reasons empty.
- Malformed: reported by line number, blocks, counts.
- Malformed line content never leaks on any surface.
- Python: setdefault / or-fallback / bare environ.get soft,
  plain getenv hard.
- JS: ?? soft, plain hard, // comment name absent.
- Rust: var_os found (hard), unwrap_or soft, plain hard.
- Shell: ${NAME-default} found with has_default true, plain
  $NAME false, # comment name absent.
- f-string name counts as a dynamic site, never guessed.

## Examined and left alone

- Example generation grouping: verified correct (prefix groups
  sorted, ungrouped names including leading-underscore names
  last). Cosmetic only; changing the grouping would churn every
  generated file for no correctness gain.
- Reads inside Python string literals can still be counted, and
  trailing same-line comments are still scanned. Parser-lite by
  design; now stated plainly in the README limits.
- Go LookupEnv stays hard: Go offers no default mechanism and
  the classification is about the contract, not the call shape.
- The `-` vs `_` arm of case-mismatch normalisation is inert
  (valid env names cannot contain `-`). Harmless, kept.
- No CLI flags, report fields (other than the additive
  blocking_reasons / malformed / counts.malformed), or exit
  code meanings were removed or renamed.
