# GhostData v0.1 - Implementation Notes (Agent A, core)

Delivered under my ownership only: PLAN.md, pyproject.toml, src/**, and
this file. tests/**, README.md, and examples/** belong to Agent B and
were not touched.

## What was built
- `src/ghostdata/readers.py` - streaming, re-openable readers for CSV,
  TSV, JSONL, and JSON arrays (incremental JSONDecoder.raw_decode over
  chunks, buffer trimmed as it is consumed). Format detection by
  extension, with content sniffing for unknown extensions. Malformed
  rows are yielded as Malformed records carrying line numbers (CSV/JSONL)
  or element numbers (JSON), never silently skipped. Blank lines are
  counted separately, not as malformed.
- `src/ghostdata/infer.py` - per-column stats in one streaming pass:
  inferred type (integer, float, boolean, date, string, object, array,
  mixed, null), null count and rate, distinct count capped at 10,000
  (past the cap the count is a lower bound and distinct_capped is set),
  numeric min/max, string min/max length, sensitive shape counters.
- `src/ghostdata/sensitive.py` - redaction decisions: column name
  patterns (password, token, secret, api key, email, phone, ssn, card,
  credential, cvv, iban and kin) plus value shapes (email, SSN, payment
  card with Luhn check, phone). Detection stores counters only, never
  values. Redacted columns show [REDACTED] in samples, are named in the
  manifest with the reason only, and have min/max suppressed.
- `src/ghostdata/core.py` - analyze(): stats pass, then a sample pass
  selecting head + tail + evenly spaced middle row indices (default
  sample 60). Counts: rows_parsed, rows_malformed, rows_total,
  blank_lines, up to 20 malformed examples with reasons.
- `src/ghostdata/pack.py` - pack writer: manifest.json (source sha256,
  counts, schema, redaction record, sample file + sha256 + strategy +
  row indices, sample vs full-file token estimates with method stamp),
  PROMPT.md (schema table plus the sample in its native format), and
  files/<name>.sample.<ext>. check() verifies the sample hash and count
  consistency.
- `src/ghostdata/tokens.py` - token estimation delegated to GhostSlice
  (package, GHOSTDATA_GHOSTSLICE_SRC, or sibling checkout) with a
  documented chars/4 fallback and its own method string. Full-file
  estimate is a chunked sum over a streamed read, labelled an estimate.
- `src/ghostdata/mcp_server.py` - stdio MCP: data_schema, data_pack.
  Payloads carry schema and counts only, never sample rows, capped.
- `src/ghostdata/cli.py` - pack, schema, check, mcp. Exit codes: 0 ok,
  1 check failed, 2 input errors (missing file, unsupported shape,
  top level not a JSON array).

## Smoke results (all run by Agent A against the built core)
- CSV (300 rows, planted malformed 3-field row at line 302, password
  and email columns): pack reports 300 parsed of 301, malformed example
  names line 302 with "expected 7 fields, found 3". password and email
  redacted by name; grep for the planted password values across
  manifest.json, PROMPT.md, and the sample file: 0 hits. Types: id
  integer (min 1, max 300), amount float, joined date, note null rate
  0.2. Sample tokens 1,565 vs full file 9,263 (GhostSlice estimator).
- TSV (3 rows): packs whole, sample strategy reports all rows.
- JSONL (121 good records, 1 invalid line at 121, column named contact
  full of dashed phone-shaped values): 121 parsed, 1 malformed named by
  line; contact redacted by shape with reason "values match phone shape
  (121 of 121 checked)"; no phone string appears in the sample.
- JSON array (90 objects, card numbers in a column named ref, nested
  object field): ref redacted by card shape (Luhn) with reason; nested
  field types as object; no card number appears anywhere in the pack.
- JSON array truncated mid-element: 2 parsed, 1 malformed with the
  element number and "rest of file uncounted", truncated flag set.
- JSONL of bare scalars: value mode, single "value" column, round-trips.
- Distinct cap: 11,000 distinct keys report distinct_count 10000 with
  distinct_capped true.
- Large file (120,000-row CSV): 120,000 parsed, 0 malformed, sample 60,
  full-file estimate 1,079,906 tokens vs sample 495. Peak child RSS
  22.5 MB total (base interpreter included), so reads are bounded.
- Source immutability: sha256 of the 120k CSV identical before and
  after packing. check passes on fresh packs and fails (exit 1, sha
  mismatch named) after appending a line to a sample file.
- --no-redact: values appear in the sample and the manifest records
  redaction.enabled false.
- MCP: initialize, tools/list (data_schema, data_pack), and a
  data_schema tools/call all answered correctly over stdio.
- Fresh-venv install (venv --system-site-packages, pip install
  --no-build-isolation; a plain venv cannot fetch a build backend in
  this sandbox): installed ghostdata reports 0.1.0, checks and packs.
- Agent B's suite landed in parallel and was run against this core:
  final result **40 passed, 0 failed**. Two integration defects in the
  core were caught by B's tests and fixed core-side (tests untouched):
  (1) the sample-size bound was violated for tiny bounds (bound 1
  returned 2 rows; the head/tail split forced a minimum of 1 each) -
  the split is now ceiling-third head, floor-third tail, rest middle,
  and the requested size is a hard bound; (2) B's MCP client passes
  the file argument as "file" while the handler required "path" - the
  handler now accepts both spellings for data_schema and data_pack.

## Bugs caught during my own verification
1. Truncation note was captured after the sample pass, which resets the
   JSON reader state; a truncated array reported truncation_note null.
   The note is now captured immediately after the stats pass.
3. Sample bound and MCP argument-name defects caught by Agent B's
   suite, described in the smoke results above.
2. Phone shape matching fired on bare digit strings, which redacted a
   numeric column of squares (88,377 of 120,000 values are 10-15 digit
   numbers) in the large-file smoke. Phone shape now requires a
   separator or a leading +. Bare unseparated phone numbers are
   therefore NOT shape-detected (documented trade-off); name-based
   detection still covers phone-named columns.

## Known limits (honest)
- Types are inferred heuristics: long digit strings (card numbers,
  big ids) infer as integer; dates infer only in ISO-like shapes; a
  column mixing ints and floats reports float, other mixes report
  mixed with types_seen recorded.
- JSONL and JSON field union requires a pre-scan pass, so those formats
  are read three times in total (fields, stats, sample). Delimited
  files are read twice. All passes stream; none loads the file whole.
- A JSON array element that fails to parse ends the parse: earlier
  elements are counted, the failure is malformed, and the rest of the
  file is uncounted by design (stated in the manifest).
- Nested values are typed object/array and are not flattened or
  distinct-counted; min/max length applies to top-level strings only.
- Card shape detection accepts any 13-19 digit string passing Luhn;
  a non-card identifier that passes Luhn in a string column will be
  redacted. The manifest shows the reason so a human can judge.
- Sample PROMPT.md embeds the sample text; with --no-redact on a
  sensitive file the pack contains the values by the operator's
  explicit choice, recorded in the manifest.

## Gates held
Stdlib only (argparse, csv, hashlib, importlib, io, json, os, re, sys,
datetime). No network code anywhere under src/. No GitHub push, no
PyPI/publish, no announcements, no spend. Source data files are never
written to; the only writes are inside the requested pack directory.
