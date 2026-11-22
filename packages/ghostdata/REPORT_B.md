# GhostData v0.1 - Agent B report (tests, README, examples)

Ownership respected: only `tests/**`, `README.md`, `examples/**`, and
this file were written. No edits to `src/**`, `pyproject.toml`, or
`PLAN.md`. No push, no publish, no announcements, no spend, no
network use. Python stdlib only (pytest as the runner, same as the
rest of the suite).

## Final result against the real core

    python3 -m pytest tests -q   ->   40 passed, 0 failed

Run twice consecutively on the final tree with identical results
(31 to 45 seconds per run; the large-file tests dominate). The CLI
was discovered via `python -m ghostdata` with `PYTHONPATH=src`
(`GHOSTDATA_CMD` and PATH installs are also honoured; tests skip
with "core not ready" if no CLI is discoverable).

## What the suite pins

- Schema stats match hand-computed fixture values exactly
  (`test_schema_stats.py`): types, null counts and rates, distinct
  counts, numeric min/max, string min/max length, across CSV, TSV,
  JSON array, and JSONL fixtures. Fixture raw facts are verified
  independently with the stdlib in `test_fixtures_sanity.py`, so a
  broken fixture cannot masquerade as a broken core.
- Malformed rows are counted, never silently skipped
  (`test_malformed.py`): the ragged CSV rows are reported at file
  lines 3 and 4 with parsed 3 of 5, and the invalid JSONL line at
  line 3 with parsed 3 of 4, in both `schema` output and the pack
  manifest. The clean fixture reports zero malformed.
- Redaction hard rules (`test_redaction.py`): every file in a pack
  tree plus command stdout and stderr is scanned for planted values
  (emails at a canary domain, password hashes, API tokens, a
  Luhn-valid test card number, an SSN-shaped sample). Columns are
  redacted by name (email, password_hash, api_token) and by value
  shape (contact holds emails, payment holds card numbers, ref holds
  SSN-shaped values), each named in the manifest with its reason,
  min/max suppressed, sample cells reading [REDACTED]. The explicit
  `--no-redact` run is also tested: values visible, and the manifest
  records `redaction.enabled: false`.
- Sample bound (`test_sample_pack.py`): default 60 on a generated
  120,000-row CSV with exact total counts; bounds 1, 7, 25, 100 never
  exceeded on a 5,000-row file (rows counted in the sample file on
  disk, not just the manifest); a bound above the row count returns
  all rows; the sample provably contains the head row, the tail row,
  and spaced middle rows; the manifest states strategy, strategy
  counts, full counts, and the token estimator method.
- Integrity (`test_integrity.py`): source sha256 identical before
  and after `schema` and `pack` for all five fixtures, and equal to
  the hash recorded in the manifest; `check` passes a fresh pack,
  fails (exit 1) on a tampered sample and on a missing pack; missing
  and empty sources exit 2 with an error, not a traceback.
- MCP (`test_mcp.py`): stdio initialize and tools/list return exactly
  data_schema and data_pack; a data_schema payload contains no
  planted values.
- Docs and examples (`test_docs_examples.py`): README present, no em
  dashes, states the limits; both shipped example packs pass
  `ghostdata check` and contain none of their sources' planted
  values.

## Defect found, and its outcome

D1. Sample bound violated at N=1 (FIXED by Agent A during the build;
my test is the record). First full run: 31 passed, 1 failed.
`ghostdata pack big.csv --sample 1` on a 5,000-row file produced a
2-row sample (`assert 2 <= 1`). Root cause in `src/ghostdata/
core.py`, `sample_indices()`: head and tail were each floored with
`max(1, sample_size // 3)`, so the smallest possible sample was 2
whenever the file had more rows than the bound. Manual confirmation
at the time: bounds 1, 2, 3, 4, 7 returned 2, 2, 3, 4, 7 rows; only
the bound of 1 was wrong. Agent A's landed fix splits the sample as
head `(sample_size + 2) // 3`, tail `sample_size // 3`, middle the
remainder; `--sample 1` now returns exactly 1 row (re-verified by
hand and by the suite). No test was weakened; the strict bound test
stands and passes.

## Test-side bug (mine, fixed in tests only)

The first MCP payload test called data_schema with argument `file`;
the tool's inputSchema requires `path`, and the server correctly
returned an error. Fixed in `tests/test_mcp.py`. One further
assumption I dropped rather than pinned: an unknown extension
(.parquet) is not an error, because the core sniffs extensionless
and unknown files from their first bytes by design. That behaviour
is documented in the README limits instead of asserted either way.

## Observations for the parent (not defects against the plan)

- Distinct counts for nested (object/array) values are reported as
  0, because the core deliberately does not distinct-count nested
  values. Documented in the README.
- Value-shape checks run on string values only, so a sensitive
  number stored as a native JSON number in an innocuously named
  field would not be shape-redacted. Name matching still applies.
  Documented in the README.
- Blank lines count separately (`blank_lines`) and are not included
  in `rows_total`; totals stay consistent as parsed + malformed,
  which `check` verifies.

## Files delivered

- tests/conftest.py, tests/test_fixtures_sanity.py,
  tests/test_schema_stats.py, tests/test_malformed.py,
  tests/test_redaction.py, tests/test_sample_pack.py,
  tests/test_integrity.py, tests/test_mcp.py,
  tests/test_docs_examples.py
- tests/fixtures/: people.csv, orders.csv, events.jsonl,
  records.json, temps.tsv
- README.md (plain words, honest limits, no em dashes)
- examples/: customers.csv, events.jsonl, README.md, and the
  prebuilt customers-pack/ and events-pack/ (both pass check, both
  free of their sources' planted values)
