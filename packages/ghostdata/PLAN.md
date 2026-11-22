# GhostData - Structured Data Slicer for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #33 for GhostSlice, Wave 4.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostData: plain job, plain name. It slices data files the way GhostSlice slices code: schema and a bounded, honest sample instead of the whole file.
- Checked against the family: GhostDocs (#12) slices prose corpora, GhostData slices row and field structure. The pair reads cleanly, Docs for documents, Data for datasets.
- Alternatives held in reserve: GhostRows (CSV-shaped only, JSON arrays and JSONL are first-class here), GhostTable (implies a database, this tool reads flat files only).

## The problem
Agents are routinely handed data files they cannot afford to read whole: a 40 MB CSV export, a JSONL event log, a JSON array with 200,000 records. Reading the file raw burns the context budget on rows the task never needed, and the first rows alone are a biased sample (sorted, truncated, or all from one day).

The useful context for most data tasks is small and specific:
- The schema: field names, inferred types, null rates, how many distinct values, numeric ranges.
- A fair sample: head, tail, and evenly spaced rows, with the sample size stated so nobody mistakes it for the file.
- The true counts: total rows, and how many rows were malformed, counted and reported rather than silently skipped.

Today a developer hand-cuts that with head, tail, and a spreadsheet, or pastes the whole file and pays for it. There is no Slice-shaped pack for structured data.

## Position in the Ghost stack
- GhostSlice governs what an agent READS from code.
- GhostDocs (#12) governs what it reads from prose corpora (Markdown, text, HTML, PDF text layers).
- GhostData governs what it reads from structured data files: CSV, TSV, JSON arrays, JSONL.
- GhostSchema (#30) covers API specs, GhostLogs (#31) covers log text. Data files with rows and fields are this tool's ground only.

Story: Slice for the code, Docs for the documents, Data for the datasets, one pack shape across all three.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Pack shape: a bundle directory with manifest.json and PROMPT.md in the Slice style, so the pack can sit next to a .claude_context bundle and be checked with the same habits.
- Token estimator: delegates to GhostSlice's estimator (package, sibling checkout, or a documented local fallback with its own method string) and stamps the method on every count. All counts labelled estimates.
- Estimator discipline: sample tokens and full-file tokens are both reported, so the saving is a measured number, not a claim.

Integration contract:
- Input: one local data file (CSV, TSV, JSON array, JSONL) plus options for sample size and output directory.
- Output: a pack directory containing manifest.json (schema, counts, redaction record, sample description, token estimates), PROMPT.md (schema summary plus the sample in its native format), and the sample file itself under files/.
- Source files are never modified. The tool only reads the source and writes the pack.

## MVP (v0.1) - local CLI first
1. Schema inference, streaming: `ghostdata schema <file>`
   - Per column or field: inferred type (integer, float, boolean, date, string, object, array, mixed, null), null count and null rate, distinct count with a stated cap (counts past the cap are reported as capped, never as exact), min and max for numeric columns, min and max length for string columns.
   - Bounded memory: the file is read as a stream in passes. Huge files are never loaded whole. Distinct sets are capped, sample buffers are capped, everything else is counters.
2. Bounded sample pack: `ghostdata pack <file> -o <pack-dir> [--sample N]`
   - Sample = head rows + tail rows + evenly spaced rows across the middle, default total 60, size and strategy stated in the manifest and in PROMPT.md.
   - Full-file counts ride along: total rows, parsed rows, malformed rows counted with the first offending line numbers recorded. Malformed rows are never silently skipped.
   - Token estimates for the sample versus the full file, estimator method stamped.
3. Sensitive columns redacted by default
   - A column is redacted when its name matches a sensitive pattern (password, token, secret, api key, email, phone, ssn, card, credential and kin) or when a stated share of its values matches a sensitive shape (email, phone, payment card with Luhn check, SSN).
   - Redacted columns appear in samples as [REDACTED], and the manifest names each one with the reason only (name match or shape match). No sensitive value is ever printed, sampled, or stored. Min and max are suppressed for redacted columns.
   - Redaction can be disabled only with an explicit flag, and the manifest records that it was.
4. Pack check: `ghostdata check <pack-dir>` verifies the sample file hash and totals against the manifest.
5. MCP tools (stdio, local only): data_schema and data_pack with capped summary payloads, sample rows never returned by default.

## Out of scope for v0.1
- Databases, SQL, parquet, Excel, and any binary format. Flat text data files only.
- Writing, converting, cleaning, or fixing data. The source is never modified and the sample is a read, not an edit.
- Statistics beyond schema facts: no distributions, correlations, or profiling verdicts.
- Joining or merging files, and nested-field expansion beyond top-level fields (nested values are typed object or array, not flattened).
- Cloud, accounts, telemetry, paid layer.

## Build estimate
- Streaming readers (CSV/TSV, JSONL, incremental JSON array) with malformed counting: 2-3 days
- Schema inference + sensitive detection and redaction: 1-2 days
- Sampler (two-pass head/tail/spaced) + pack writer + check: 1-2 days
- MCP server, tests, README, examples: 1-2 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice and the rest of the suite.
- Paid candidate later only: team data-pack libraries or CI schema drift gates. Do not build a paid layer before a free launch validates demand.

## Verification bar
- A CSV with a planted malformed row reports that row as malformed by line number and still packs the rest; no silent skip.
- A file with password, email, and card-shaped columns ships a sample where those columns read [REDACTED] and the manifest names each with its reason; no planted sensitive value appears anywhere in the pack.
- Sample honesty: manifest states sample size, strategy, and the full row count, and the token estimates carry the estimator method.
- A generated large file (100k+ rows) packs with bounded memory and correct total counts.
- The source file's hash is identical before and after every run.

## Risks / honest notes
- Type inference is heuristic: a column of numeric strings infers as numbers, a date column in an unusual format infers as string. The manifest labels types as inferred, never as declared.
- Value-shape detection can miss obfuscated sensitive values and can over-redact a look-alike column. The manifest shows the reason so a human can judge, and the explicit no-redact flag exists for local files the owner trusts.
- JSON arrays need an incremental reader; a malformed element mid-array ends the parse and is reported as malformed with the rest of the file uncounted. That limit is stated, not hidden.

## Next gate
Ryan's go on: (1) GhostData as working name, (2) the four formats only (CSV, TSV, JSON array, JSONL), (3) redaction on by default with the explicit opt-out flag, (4) Wave 4 build order as listed in the suite plan.
