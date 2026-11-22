# GhostData v0.1 - Polish Report (Oct 14, 2026)

Polish round at Ryan's "Polishing", after Wave 4 parent verification
(40 passed, parent-verified Oct 14, 2026). House loop: audit first
(PLAN.md, IMPLEMENTATION_A.md, REPORT_B.md read in full, fixtures and
test assertions checked for interactions), then improve only what a
fixture proves better, each change pinned by new tests. No version
bump (still 0.1.0; releases are Ryan-gated), stdlib only, local only,
no push, no publish, no announcements, no spend.

## Test counts

- Before: `python3 -m pytest tests -q` -> **40 passed, 0 failed**
- After: `python3 -m pytest tests -q` -> **47 passed, 0 failed**
- Delta: +7 new tests in `tests/test_polish.py`. No existing test was
  edited, weakened, or deleted; the only test-file change is the new
  file. The full planted-value redaction scans in
  `tests/test_redaction.py` were re-run as part of the suite, plus a
  new leak scan for the native-integer card path (below).

## Change 1: leading-zero digit strings infer as string, not integer

Audit seed: IMPLEMENTATION_A.md lists "long digit strings infer as
integer" as an honest limit. The sharper defect inside it: a digit
string with a leading zero is a code (ZIP code, padded id), and
`int()` silently destroyed information.

- Before (probe, CSV column `00501, 10001, 01234`): type `integer`,
  min **501**, max 10001. The schema reported a numeric range the
  data never had.
- Fix (`src/ghostdata/infer.py`, `classify`): an integer-shaped
  string whose digit part (after an optional sign) has length > 1
  and starts with `0` classifies as `string` with no numeric value.
  A lone `"0"` still classifies as integer; plain values like
  `"10001"` are unaffected.
- After (same probe): the two padded values are strings; a uniformly
  padded column reports type `string` with length stats and no
  min/max; a column mixing one padded and one unpadded value reports
  the honest type `mixed`, with the numeric range covering only the
  true integer. Samples keep the zeros verbatim.
- Pinned by 4 new tests: uniform padded column, sample fidelity,
  mixed-column honesty, and a guard test that `0`/`42`/`7` still
  infer as integer with the correct range.

## Change 2: native JSON integers get the card shape check

Audit seed: REPORT_B.md observation, "value-shape checks run on
string values only, so a sensitive number stored as a native JSON
number in an innocuously named field would not be shape-redacted."

- Before (probe, JSONL field `acct_ref` holding the Luhn-valid test
  numbers 4111111111111111 and 5500005555555559 as JSON numbers):
  `redacted: false`, and schema output printed min/max equal to the
  card numbers themselves.
- Fix: new `shape_of_int` in `src/ghostdata/sensitive.py` returns
  the card shape only (13-19 digits, Luhn-valid, non-negative). A
  bare integer has no separators, so the email/SSN shapes cannot
  match, and phone detection keeps its documented separator rule, so
  this cannot resurrect the measured phone false positive on numeric
  columns (IMPLEMENTATION_A.md bug 2). `ColumnStats.add` in
  `infer.py` now runs it for native ints (bools excluded) and counts
  them in a new `shape_checked` denominator; for string-only columns
  the denominator is unchanged, so every pre-existing redaction
  reason string is byte-identical (the suite's exact reason
  assertions still pass).
- After (same probe): `acct_ref` is redacted with reason "values
  match card shape (3 of 3 checked)", min/max suppressed, and
  neither card number appears anywhere in the pack or in command
  output (asserted by scanning every pack file plus stdout/stderr).
  The control column `batch_no` (4111111111111112, one digit off,
  Luhn fails) is not redacted, stays typed integer with its true
  range, and its value remains visible in the sample: no
  over-redaction of ordinary big integers.
- Pinned by 3 new tests: pack-level redaction + full-tree leak
  scan, exact reason counting, and the Luhn-failing control.

## Docs updated to match

- `README.md` honest limits: the leading-zero behaviour is stated,
  and the stale line "Numeric (non-string) values are not shape
  checked" now reads that shape checks run on string values and on
  native JSON integers for the card shape only. The
  `test_docs_examples.py` contract (inferred / capped / luhn /
  estimates wording, no em dashes) still passes.

## Deliberately left alone

- **Unknown extensions are sniffed, not refused.** This is a design
  decision, not an oversight: Agent B explicitly dropped pinning it
  either way during the build, and the README documents it.
  Refusing extensionless files would be a behaviour regression, not
  an improvement, and no fixture proves otherwise.
- **Phone shape on bare digit strings.** The separator-or-plus rule
  stands; it was a measured false positive during the build (a
  numeric squares column redacted), and name-based detection still
  covers phone-named columns. Change 2 was scoped to the card shape
  precisely so it does not reopen this.
- **Float-shaped strings with leading zeros** (e.g. `"007.5"`).
  Numeric conversion loses nothing there (007.5 and 7.5 are the same
  measurement); the data-corruption case is integer codes, which
  Change 1 covers. Widening the guard without a proving fixture
  would be speculation.
- **Nested values not distinct-counted, the 10,000 distinct cap,
  JSON-array malformed-ends-parse, dates in non-ISO formats.** All
  documented plan-level limits with stated reasons; nothing in the
  audit showed a fixture-provable improvement inside v0.1 scope.

## Files changed

- `src/ghostdata/infer.py` (leading-zero guard; int shape counting)
- `src/ghostdata/sensitive.py` (`shape_of_int`; docstring accuracy)
- `tests/test_polish.py` (new; 7 tests)
- `README.md` (two honest-limits lines)
- `POLISH_REPORT.md` (this file)

Nothing else. `pyproject.toml` untouched, version still 0.1.0.
