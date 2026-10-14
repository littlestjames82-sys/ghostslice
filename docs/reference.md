# Reference

Part of the [GhostSlice README](../README.md). The honest labels and the limits.

## Honest labels

- **Token counts are estimates.** Method (v2, since v0.10): a BPE-like
  split (word and punctuation chunks count as 1 token up to 4
  characters, then 1 token per 4 characters; whitespace is not counted
  separately), multiplied by a per-language-family calibration factor.
  The raw split over-counts versus published tokenizer behaviour (it
  charges full price for substrings real BPE merges), so each family's
  factor brings the estimator's implied characters-per-token on the
  golden corpora in `tests/fixtures/calibration/` onto a published
  anchor: ~4 chars/token for English prose (OpenAI's published rule
  of thumb), with code/data families set denser as documented
  approximations in `src/ghostslice/tokens.py`. It is still not any
  model's exact tokenizer. Run `ghostslice calibrate <project>` to see
  raw vs calibrated totals per family on your own tree.
  **Migration note:** v0.10 totals are lower than v0.9 totals for
  calibrated families (the GhostBus demo moved 165,052 -> 129,555
  original and 53,339 -> 45,770 sliced estimated tokens). Old bundles
  remain valid and name the old method in their manifest; budgets set
  with `check-budget` or a profile under v0.9 compare against
  calibrated totals from v0.10 on, so re-check them once.
- **Prices are local and dated, never live.** There is one price
  table: `src/ghostslice/prices.json`, inside the package (shipped
  as package data), carrying an `as_of` date (currently 2026-10-12)
  and editable per-model input/output rates. A `prices.json` in the
  current directory overrides it for that run. Nothing is fetched.
  Verify rates with the provider before relying on a figure.
  Pre-flight cost counts context (input) tokens only.
- **TypeScript/JavaScript slicing is parser-lite.** Python uses the real
  `ast` parser. TS/JS uses line scanning, regexes, and brace matching;
  it handles conventional shapes (functions, arrow functions, classes,
  interfaces, types, enums, test blocks) and can slice exotic syntax
  imperfectly. Since v0.4 the brace matching is string/comment aware:
  braces inside `'...'`, `"..."`, and `` `...` `` template literals
  (including `${...}` interpolation and multi-line templates), `//`
  comments, and `/* ... */` comments do not affect depth, and the same
  awareness applies to the Go/Rust/Java/C# lite slicers (with a
  char-literal heuristic so Rust lifetimes like `'a` do not open a
  phantom string). Remaining known limit: braces inside regex literals
  (e.g. `/}/`) and nested backticks inside `${...}` expressions can
  still confuse the counter.
- **Secret scanning is a heuristic guard, not a guarantee** (see
  [Secret guard](commands.md#secret-guard-v04)): it favours not flagging placeholders over
  catching every possible secret shape.

## Encodings, malformed input, and limits

Since v0.21 every surface decodes source files through one shared
helper (`src/ghostslice/textio.py`), so a file means the same text
to the scanner, the slicers, and the exporter:

- **BOMs are honoured.** UTF-8, UTF-16 (LE/BE), and UTF-32 (LE/BE)
  byte-order marks are sniffed and decoded with the matching codec.
  Token counts and line counts are computed on the decoded text,
  and slicers see the real source (a UTF-16 file used to be skipped
  as "binary"; a UTF-8 BOM used to cost a phantom token and break
  Python parsing). Wide encodings are detected by BOM only — a
  BOM-less UTF-16 file is indistinguishable from binary data and
  is still skipped.
- **Bytes that are not valid UTF-8 decode as Latin-1** (every byte
  maps to a codepoint, so nothing is lost) instead of being mangled
  into U+FFFD replacement characters. The scanner records the
  source encoding per file, and bundle manifests carry
  `source_encoding` for any file that was not plain UTF-8. Bundles
  always ship the decoded text as UTF-8: a bundle is a normalized
  view, never a byte copy. (One format exception: `context.xml`
  content additionally passes through XML's own rules — characters
  XML cannot represent become U+FFFD there, and XML parsers
  normalize CR/CRLF line endings to LF when reading; `files/`
  always keeps the canonical slice bytes.)
- **Line endings are split with `splitlines()` semantics**: LF,
  CRLF, and CR-only files all slice and count lines correctly.
- **Malformed input degrades, never tracebacks.** A seeded fuzz
  corpus (`tests/fuzz_harness.py`, driven by
  `tests/test_v21_fuzz.py`) mutates real fixtures — truncations,
  bit flips, NUL and invalid-UTF-8 injection, BOM/EOL shuffles,
  unbalanced braces — plus malformed profiles, manifests, and
  ledgers, and drives every command over it. Broken profiles are
  exit 2 with the field named; broken bundles fail `check` with
  errors listed (validation reports, it does not raise); broken
  Python/JSON degrades to the line fallback / full text; a missing
  project or unknown `--model` is a clean exit 2 everywhere.
- **Limits.** There is no hard file-size cap: files are read fully
  into memory and processed at a measured ~0.4-0.8 s per MB in the
  parser-lite modes on modest hardware (linear, no pathological
  blowups — the fuzz suite pins a scaling bound), so a 50 MB
  source file costs tens of seconds, not a hang. Nesting depth is
  bounded by Python's recursion limit: deeper Python/JSON degrades
  to the fallback/full rendering (JSON structure shaping also
  placeholders beyond depth 100). Non-regular files (FIFOs,
  sockets, devices) are skipped by the scanner — opening a FIFO
  would block forever. Pathological inputs are a documented
  degrade, never a crash: if you find one that tracebacks, that is
  a bug — the fuzz corpus is the regression net.
