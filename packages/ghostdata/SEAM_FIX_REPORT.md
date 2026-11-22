# GhostData - Seam Fix Report: top-level JSON objects (Oct 14, 2026)

Fix round for the coverage gap found by the ecosystem pass
(`~/workspace/ghostslice-companions/ECOSYSTEM.md`, seam 6): GhostData
refused a real tree's only data file with exit 2, "top level is not a
json array". The file was the GhostLogs tree's
`examples/incident-pack/manifest.json`, a top-level JSON object.
Config-shaped JSON, the most common JSON shape in real projects, had
no slicer in the ecosystem. It has one now.

Gates held: no version bump (still 0.1.0), stdlib only, local only,
no push, no PyPI, no publish, no announcements, no spend. No existing
test was edited, weakened, or deleted; the only test change is one
new file.

## Test counts

- Before: `python3 -m pytest tests -q` -> **47 passed, 0 failed**
  (the parent-verified count after the polish round).
- After: `python3 -m pytest tests -q` -> **63 passed, 0 failed**.
- Delta: +16 new tests, all in `tests/test_json_object.py`.

## The model

A top-level JSON object is a single record. Its keys are the column
list, in file order, and its one row is the values, so the existing
machinery (per-column inference, name/shape redaction decisions,
manifest, pack check) applies unchanged:

- Schema: per key, the same inferred types as everywhere else in the
  tool. Nested values are typed `object` or `array` and never
  flattened, which is exactly the honesty rule array records already
  use for nested fields. A null-valued key reports type `null` with
  null rate 1.0.
- Structure facts ride along in the manifest and schema output:
  `top_level_keys`, `total_keys` (counting nested objects), and
  `max_depth` (containers, root at depth 1).
- Sample: the object itself, redacted, then structurally bounded
  (below). Manifest strategy reads "whole object: the file is a
  single record, sampled in full and bounded structurally".
- Counts: 1 parsed, 0 malformed, 1 total, so the existing pack check
  (total = parsed + malformed; sample rows no more than parsed rows)
  verifies object packs unmodified.

Dispatch: `.json` files (and `--format json`) now peek at the first
non-whitespace character. `[` goes to the streaming array reader as
before; `{` goes to the new object reader; anything else is refused
by name (see Scalars). `--format json-object` forces the object
reader, which is also the documented route for an extensionless
object file, since extension sniffing still treats a leading `{` as
JSONL (unchanged).

## Redaction, identical rules at every depth

New `sensitive.redact_nested` applies the column rules recursively:
a key whose name matches a sensitive name pattern has its whole
value replaced; a string matching a sensitive shape (email, SSN,
Luhn-checked card, phone with the separator rule) is replaced; a
native integer matching the card shape via `shape_of_int` is
replaced. Replacements are `[REDACTED]`, recorded in the manifest
under `redaction.nested` by dotted path (list indices as `[i]`), and
surfaced in the CLI output, PROMPT.md, schema output, and MCP
payloads.

Whole-key redactions from the stats pass still land under
`redaction.columns` with their usual reasons (a card value under an
innocuous top-level key is caught by the 1-of-1 shape rule, min/max
suppressed, exactly as in the JSONL case the polish round fixed).

Adversarial pins in the new tests: a card-shaped string nested at
`payment.ref` (innocuous key, Luhn shape), a native-integer card at
`billing.acct`, a planted password at `database.password` (sibling
`host` stays visible), a planted token at a top-level `api_token`
key, and a leading-zero string (`zip: "00501"`, plus `"01234"` inside
an array) which infers as string and reaches the sample verbatim.
Every pack in those tests is scanned file by file, plus stdout and
stderr, for the planted values.

Consistency bonus, same leak class: nested values inside JSON array
and JSONL records now get the same recursive redaction in the sample
pass. Before this round, a secret nested inside an object-typed
field of an array record would have been dumped raw into the sample;
a new test pins the array case too. CSV/TSV cells are strings, so
their behavior is untouched, and the full pre-existing suite passes
unmodified, which is the evidence nothing else moved.

## Bounded memory, stated honestly

Arrays stream because their elements are independent. An object's
key set cannot be known without parsing it, so
`JsonObjectReader` parses the file whole, cached across the stats
and sample passes. The guard is explicit and in the error message:
files over **16 MiB** (`MAX_OBJECT_BYTES` in `readers.py`) with an
object top level are refused, naming the limit and noting that
array-shaped JSON streams without one. 16 MiB is far above any real
config file and bounds the parsed structure a single object can make
the tool hold. Everything else in the tool (CSV, TSV, JSONL, JSON
arrays, full-file token estimation, source hashing) still streams,
unchanged.

The sample is bounded the way the tool bounds everything: by a
stated discipline with the outcome recorded. `core.bound_object`
applies structural caps to the redacted object (redaction runs
first, so a cut can never expose part of a sensitive value):

- container depth 6 (root at depth 1); deeper containers are
  replaced with a `[TRUNCATED]` marker,
- 50 keys per nested object level (the top level's keys are never
  dropped: they are the schema),
- 20 items per array,
- 1000 characters per string (cut with a `[TRUNCATED]` suffix).

Every cut is counted (`keys_dropped`, `items_dropped`,
`depth_truncations`, `strings_truncated`, plus up to 20 path
details and the limits themselves) into `manifest.sample.truncation`;
`manifest.sample.truncated` is the boolean; PROMPT.md states the
truncation in words when it happens, and the CLI prints a line.
Tests pin a 9-deep object (depth cut, marker present, deepest leaf
absent), a 60-key nested object (exactly 10 dropped), a 25-item
array (exactly 5 dropped), a 1500-character string (exactly one
truncated), and a small object reporting `truncated: false`.

## What stayed refused, and why

- **Top-level scalars.** A `.json` file holding a bare `42`,
  `"hello"`, `true`, or `null` exits 2 with "top level is a json
  scalar, not an array or object: a lone number, string, boolean,
  or null has no fields to describe and no rows to sample". Kept
  refused deliberately: the tool's product is a schema plus a fair
  sample of a dataset, and a lone scalar is not a dataset. The
  JSONL/array "value" column exists for *streams* of scalars, where
  each line is a row; a single scalar document has no such reading,
  and inventing one would misdescribe the file. Pinned by test.
- **Empty objects** (`{}`): exit 2, "json object has no keys:
  nothing to describe", mirroring the empty-array and empty-file
  refusals.
- **Invalid JSON and trailing data** after the object: exit 2 with
  the parser's reason, same as before.

## Demonstration: the refused file, packed

Before (baseline, Oct 14, 2026):

    $ ghostdata pack ~/workspace/ghostlogs/examples/incident-pack/manifest.json -o <dir>
    ghostdata: top level is not a json array        (exit 2)

After (same command):

    GhostData pack: /tmp/gd-demo-after
      format json-object, rows parsed 1 of 1 (0 malformed)
      sample 1 rows, tokens sample 1664 vs full file 1673 (estimates)
      redacted: token_method (column name matches token)
      redacted: budget_tokens (column name matches token)
      redacted: pack_estimated_tokens (column name matches token)
      redacted: estimated_tokens_in (column name matches token)
    (exit 0)
    $ ghostdata check /tmp/gd-demo-after
    {"ok": true, "errors": [], "files_checked": 1}   (exit 0)

Manifest facts from that pack: 17 top-level keys, 112 total keys,
maximum depth 6, `sample.truncated: false`, source sha256 in the
manifest matches the file, and the source file's sha256 was
identical before and after (da3b8ec8... in both readings).

One honest observation from the demonstration: the name rule
redacts GhostLogs' four token-counter fields (`token_method`,
`budget_tokens`, `pack_estimated_tokens`, `estimated_tokens_in`)
because their key names contain "token". Those are counters, not
credentials; this is the documented name-match trade-off (the
manifest shows the reason so a human can judge, and `--no-redact`
exists for files the owner trusts), not a leak: the values are
hidden, never exposed. The schema still reports their types.

## Files changed

- `src/ghostdata/readers.py`: `JsonObjectReader` (whole-parse under
  the 16 MiB `MAX_OBJECT_BYTES` guard, cached; structure facts),
  `peek_json_shape`, shape dispatch for the `json` family and the
  `json-object` format, scalar refusal wording, module docstring.
- `src/ghostdata/sensitive.py`: `redact_nested` (recursive name and
  shape redaction returning path-addressed hits) and the shared
  `REDACTED` constant.
- `src/ghostdata/core.py`: `bound_object` with its stated limits;
  object sample branch (redact, then bound); nested redaction in the
  tabular sample pass; `structure` and `redacted_nested` in the
  analyze result.
- `src/ghostdata/pack.py`: object sample rendering and `.json`
  sample extension; manifest gains `structure`,
  `redaction.nested`, `sample.strategy` wording for objects,
  `sample.truncated` and `sample.truncation`; PROMPT.md object
  wording, truncation statement, and nested-redaction note.
- `src/ghostdata/cli.py`: `json-object` in `--format` choices,
  schema output gains `redacted_nested` and `structure`, pack output
  prints nested redactions and a truncation line.
- `src/ghostdata/mcp_server.py`: tool descriptions and payloads
  carry the object format, `redacted_nested`, and `structure`.
- `tests/test_json_object.py`: new, 16 tests. No existing test file
  was touched.
- `README.md`: supported formats, `--format` choices, nested
  redaction paragraph, manifest contents, and three honest-limit
  bullets (full-parse guard, structural bounds with stated
  truncation, scalar refusal and the extensionless route).
- `SEAM_FIX_REPORT.md`: this file.

Untouched: `pyproject.toml` (version still 0.1.0), PLAN.md,
IMPLEMENTATION_A.md, REPORT_B.md, POLISH_REPORT.md, examples, and
every pre-existing test.

## Deliberately left alone

- JSONL/CSV/TSV behavior: unchanged, suite-verified.
- Extension sniffing for `{`: still JSONL. Object support keys off
  the `.json` extension or an explicit `--format`, which is where
  the refused real-world file sat; changing the sniffer would
  misroute genuine JSONL files, whose first line is also an object.
- Nested values are still not flattened, expanded, or
  distinct-counted, in objects exactly as in arrays (plan-level
  limit, unchanged).
- Structural bounding applies to the object sample only. A tabular
  sample is already row-bounded; a pathological single nested cell
  inside an array record can still be large, as it could in v0.1.
  Nested *redaction* now covers those cells; nested *bounding*
  there is a separate change for a separate round, if ever.
